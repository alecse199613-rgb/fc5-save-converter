#!/usr/bin/env python3
"""
FC5 Save Converter — Uplay ↔ CODEX
====================================
Bidirectional converter between Ubisoft Connect (.save) and CODEX (.sav)
save formats for Far Cry 5 (GameId 1803).

Mode u2c (default): Uplay → CODEX
  Wraps .save files in CDX headers so the CODEX emulator's built-in
  save converter (ConverterEnabled=1) can handle the key re-derivation.

Mode c2u: CODEX → Uplay
  Wraps .sav files using a reference .save file as a header template,
  producing .save files usable on Ubisoft Connect installations.

Usage:
  # Uplay → CODEX
  python fc5_save_converter.py --replacement "path\\to\\1803"

  # CODEX → Uplay
  python fc5_save_converter.py --mode c2u --replacement "path\\to\\saves" --reference "valid.save"
"""

import os
import sys
import shutil
import datetime
import argparse


# --- Constants ---

CDX_HEADER_SIZE = 0x110       # 272 bytes
UPLAY_HEADER_SIZE = 0x228     # 552 bytes
CDX_MAGIC = b'CDX\0'
UPLAY_MAGIC = b'\x24\x02\x00\x00'


# --- Shared helpers ---

def find_profile_suffix(save_dir):
    """
    Read a working CDX .sav file to extract the profile identifier
    (the numeric suffix in the CDX name field, e.g. '134261316324923516').
    """
    for slot_name in ['0x1.sav', '0x2.sav', '1.sav', '2.sav']:
        path = os.path.join(save_dir, slot_name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, 'rb') as f:
                data = f.read()
            if len(data) < CDX_HEADER_SIZE:
                continue
            if data[0:4] != CDX_MAGIC:
                continue
            name_end = data.find(b'\x00', 0x0C)
            if name_end < 0x0D:
                continue
            name_bytes = data[0x0C:name_end]
            name_str = name_bytes.decode('ascii', errors='replace')
            parts = name_str.split('.')
            if len(parts) >= 3 and parts[-1].isdigit():
                suffix = parts[-1]
                print(f"  [OK] Profile suffix found in {slot_name}: {suffix}")
                return suffix
        except Exception as e:
            print(f"  [!] Error reading {slot_name}: {e}")
            continue
    return None


def parse_cdx_name(data):
    """Extract (slot_number, profile_suffix) from a CDX header."""
    if data[0:4] != CDX_MAGIC:
        raise ValueError("Not a valid CDX file")
    name_end = data.find(b'\x00', 0x0C)
    if name_end < 0x0D:
        raise ValueError("CDX header missing name string")
    name = data[0x0C:name_end].decode('ascii', errors='replace')
    # name format: saveSlot<N>.sav.<profile_suffix>
    parts = name.split('.')
    if len(parts) < 3:
        raise ValueError(f"Unexpected CDX name format: {name}")
    slot_str = parts[0].replace('saveSlot', '')
    suffix = parts[-1]
    return slot_str, suffix


def extract_cdx_info(filepath):
    """Read a CDX file and return (slot, suffix, body_bytes)."""
    with open(filepath, 'rb') as f:
        data = f.read()
    if len(data) < CDX_HEADER_SIZE:
        raise ValueError(f"File too small ({len(data)} bytes)")
    slot, suffix = parse_cdx_name(data)
    body = data[CDX_HEADER_SIZE:]
    return slot, suffix, body


def make_cdx_header(slot_number, body_size, profile_suffix):
    """Build a CDX header matching the CODEX format."""
    header = bytearray(CDX_HEADER_SIZE)
    header[0:4] = CDX_MAGIC
    slot_val = int(slot_number)
    header[4:8] = slot_val.to_bytes(4, 'little')
    header[8:12] = body_size.to_bytes(4, 'little')
    name = f"saveSlot{slot_number}.sav.{profile_suffix}\0"
    name_bytes = name.encode('ascii')
    if len(name_bytes) > CDX_HEADER_SIZE - 0x0C:
        raise ValueError(f"Name too long: {name}")
    header[0x0C:0x0C + len(name_bytes)] = name_bytes
    return bytes(header)


def make_uplay_header_from_reference(ref_path, cdx_slot):
    """
    Read a reference .save file, extract the 0x228-byte header,
    and update the save slot name to match cdx_slot.
    """
    with open(ref_path, 'rb') as f:
        data = f.read()
    if len(data) < UPLAY_HEADER_SIZE:
        raise ValueError(f"Reference file too small ({len(data)} bytes)")

    header = bytearray(data[:UPLAY_HEADER_SIZE])

    # Find and update the UTF-16LE name at offset 0x28
    name_start = 0x28
    name_utf16 = bytes(header[name_start:])
    # Find null terminator (00 00 in UTF-16LE)
    end = 0
    for i in range(0, len(name_utf16), 2):
        if name_utf16[i] == 0 and name_utf16[i + 1] == 0:
            end = i
            break
    if end == 0:
        raise ValueError("Reference header missing null-terminated name string")

    existing_name = name_utf16[:end].decode('utf-16-le', errors='replace')
    parts = existing_name.split('.')
    if len(parts) < 3:
        raise ValueError(f"Unexpected reference name format: {existing_name}")
    suffix = parts[-1]

    new_name = f"saveSlot{cdx_slot}.sav.{suffix}"
    new_utf16 = new_name.encode('utf-16-le') + b'\x00\x00'

    # Zero old name, write new one
    for i in range(name_start, name_start + end + 2):
        header[i] = 0
    header[name_start:name_start + len(new_utf16)] = new_utf16

    return bytes(header)


# --- u2c: Uplay → CODEX (forward) ---

def _scan_folder_for_saves(folder):
    """Scan a single folder for 1.save/2.save, return slot->path dict."""
    result = {}
    for fname in os.listdir(folder):
        if fname.endswith('.save'):
            base = fname.replace('.save', '')
            if base in ('1', '2'):
                result[base] = os.path.join(folder, fname)
        if fname == '1803' and os.path.isdir(os.path.join(folder, fname)):
            sub = os.path.join(folder, fname)
            for sf in os.listdir(sub):
                if sf.endswith('.save'):
                    sbase = sf.replace('.save', '')
                    if sbase in ('1', '2'):
                        result[sbase] = os.path.join(sub, sf)
    return result


def find_save_files(replacement_path):
    """Find .save files in the given path. Supports single file, folder,
    folder with 1803/ subfolder, or parent folder with subfolders."""
    slot_files = {}

    if os.path.isfile(replacement_path):
        name = os.path.basename(replacement_path)
        if name.endswith('.save'):
            base = name.replace('.save', '')
            if base in ('1', '2'):
                slot_files[base] = replacement_path
        return slot_files

    if not os.path.isdir(replacement_path):
        print(f"  [!] Path not found: {replacement_path}")
        return slot_files

    slot_files = _scan_folder_for_saves(replacement_path)

    if not slot_files:
        candidates = []
        for entry in sorted(os.listdir(replacement_path)):
            subpath = os.path.join(replacement_path, entry)
            if os.path.isdir(subpath):
                found = _scan_folder_for_saves(subpath)
                if found:
                    candidates.append((entry, subpath, found))
        if len(candidates) == 1:
            name, subpath, found = candidates[0]
            print(f"  [OK] Found saves in: {name}")
            slot_files = found
        elif len(candidates) > 1:
            print(f"\n  Multiple save folders detected:")
            for i, (name, subpath, found) in enumerate(candidates, 1):
                slots = ', '.join(sorted(found.keys()))
                print(f"    [{i}] {name}\\ (slots {slots})")
            print(f"\n  Pass a specific folder with --replacement to pick one.")
            print(f"  Example: --replacement \"{replacement_path}\\030 Holland Valley\"")
            print(f"  Or: --replacement \"{replacement_path}\\030 Holland Valley\\1803\"")

    return slot_files


def validate_uplay_save(filepath):
    """Validate a .save file and return (body_offset, body_size)."""
    with open(filepath, 'rb') as f:
        data = f.read()
    if len(data) < UPLAY_HEADER_SIZE + 16:
        raise ValueError(f"File too small ({len(data)} bytes)")
    first_word = int.from_bytes(data[0:4], 'little')
    has_uplay_header = (
        first_word == 0x00000224 or
        data[0:2] == b'\x24\x02' or
        data[0:2] == b'\x02\x24'
    )
    if not has_uplay_header:
        if data[0:4] == CDX_MAGIC:
            raise ValueError("File appears to be in CDX format (.sav), not .save")
        print(f"  [!] Warning: {os.path.basename(filepath)} doesn't have standard Ubisoft header (0x2402)")
        print(f"      First bytes: {data[0:8].hex()}")
    body_offset = UPLAY_HEADER_SIZE
    body_size = len(data) - body_offset
    if body_size <= 0:
        raise ValueError(f"Empty body at offset 0x{body_offset:x}")
    return body_offset, body_size


def convert_u2c_save(replacement_path, save_dir, profile_suffix, dry_run=False):
    """Convert a single .save file to .sav (Uplay → CODEX)."""
    filename = os.path.basename(replacement_path)
    slot = filename.replace('.save', '')
    sav_filename = f"0x{slot}.sav"
    sav_path = os.path.join(save_dir, sav_filename)

    print(f"\n  Converting: {filename} -> {sav_filename}")

    try:
        body_offset, body_size = validate_uplay_save(replacement_path)
    except ValueError as e:
        print(f"  [FAIL] {e}")
        return False

    print(f"    Body at offset 0x{body_offset:x}, {body_size} bytes")

    with open(replacement_path, 'rb') as f:
        f.seek(body_offset)
        body = f.read()

    try:
        header = make_cdx_header(slot, len(body), profile_suffix)
    except ValueError as e:
        print(f"  [FAIL] Header error: {e}")
        return False

    new_sav = header + body

    if dry_run:
        print(f"  [DRY RUN] Would write {len(new_sav)} bytes to {sav_path}")
        return True

    if os.path.isfile(sav_path):
        backup_dir = os.path.join(save_dir, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"{sav_filename}.{timestamp}.bak"
        shutil.copy2(sav_path, os.path.join(backup_dir, backup_name))
        print(f"    Backup saved: {backup_name}")

    with open(sav_path, 'wb') as f:
        f.write(new_sav)
    print(f"  [OK] Written {len(new_sav)} bytes to {sav_filename}")
    return True


def run_u2c(repl_path, save_dir, dry_run=False):
    """Uplay → CODEX: find .save files, convert to .sav."""
    # Step 1: Extract profile suffix from existing CODEX saves
    print("── Step 1: Reading profile identifier from existing saves ──")
    profile_suffix = find_profile_suffix(save_dir)

    if not profile_suffix:
        print("\n  [!] Could not read profile suffix from save directory.")
        print("      If you know your CODEX AccountId from CODEX.ini,")
        print("      you can enter the numeric part here.")
        print("      (Press Enter to use a common default)")
        user_input = input("  Profile suffix: ").strip()
        if user_input:
            profile_suffix = user_input
        else:
            profile_suffix = "134261316324923516"
            print(f"  Using default suffix: {profile_suffix}")
            print("  (You may need to update CODEX.ini AccountId to match)")

    print(f"  Profile suffix: {profile_suffix}")

    # Step 2: Find and convert
    print("\n── Step 2: Converting saves ──")
    slot_files = find_save_files(repl_path)

    if not slot_files:
        print("\n  [!] No .save files found.")
        if os.path.isdir(repl_path):
            print(f"      Expected 1.save / 2.save in: {repl_path}")
            # Check for candidates
            candidates = []
            for entry in sorted(os.listdir(repl_path)):
                subpath = os.path.join(repl_path, entry)
                if os.path.isdir(subpath):
                    direct = os.path.join(subpath, '1.save')
                    sub1803 = os.path.join(subpath, '1803', '1.save')
                    if os.path.isfile(direct) or os.path.isfile(sub1803):
                        candidates.append(entry)
            if candidates:
                print(f"      Found subfolders with saves — use --replacement with one:")
                print(f"      --replacement \"{repl_path}\\{candidates[0]}\"")
            else:
                sub1803 = os.path.join(repl_path, '1803')
                if os.path.isdir(sub1803):
                    print(f"      Try: --replacement \"{repl_path}\\1803\"")
        return False

    print(f"\n  Found {len(slot_files)} save file(s):")
    for slot, fp in sorted(slot_files.items()):
        fsize = os.path.getsize(fp)
        print(f"    Slot {slot}: {os.path.basename(fp)} ({fsize:,} bytes)")

    success = 0
    for slot in sorted(slot_files.keys()):
        if convert_u2c_save(slot_files[slot], save_dir, profile_suffix, dry_run):
            success += 1

    print(f"\n  Result: {success}/{len(slot_files)} converted successfully")
    if success > 0 and not dry_run:
        print("\n  Next step: Launch Far Cry 5. The CODEX emulator's")
        print("  save converter (ConverterEnabled=1) will handle the")
        print("  final decryption/re-encryption automatically.")
    return success > 0


# --- c2u: CODEX → Uplay (reverse) ---

def find_cdx_files(repl_path):
    """Find .sav files in the given path. Returns dict of slot->path where
    slot is derived from the filename (0x1.sav -> '1', 0x2.sav -> '2')."""
    results = {}

    if os.path.isfile(repl_path):
        name = os.path.basename(repl_path)
        slot = _cdx_filename_to_slot(name)
        if slot:
            results[slot] = repl_path
        return results

    if not os.path.isdir(repl_path):
        print(f"  [!] Path not found: {repl_path}")
        return results

    for fname in os.listdir(repl_path):
        if fname.endswith('.sav') and os.path.isfile(os.path.join(repl_path, fname)):
            slot = _cdx_filename_to_slot(fname)
            if slot:
                results[slot] = os.path.join(repl_path, fname)

    return results


def _cdx_filename_to_slot(fname):
    """Extract slot number from CDX filename: '0x1.sav' -> '1', '0x2.sav' -> '2'."""
    base = fname.replace('.sav', '')
    # Handle 0x1, 0x2, 1, 2, etc.
    if base.startswith('0x'):
        slot = base[2:]
    else:
        slot = base
    return slot if slot in ('1', '2') else None


def convert_c2u_save(cdx_path, ref_path, output_dir, slot, dry_run=False):
    """Convert a single .sav file to .save (CODEX → Uplay)."""
    filename = os.path.basename(cdx_path)
    out_name = f"{slot}.save"
    out_path = os.path.join(output_dir, out_name)

    print(f"\n  Converting: {filename} -> {out_name}")

    # Read CDX file
    try:
        cdx_slot, cdx_suffix, body = extract_cdx_info(cdx_path)
        if cdx_slot != slot:
            print(f"    (CDX header says slot {cdx_slot}, using filename slot {slot})")
    except (ValueError, IOError) as e:
        print(f"  [FAIL] {filename}: {e}")
        return False

    # Build Uplay header from reference
    try:
        header = make_uplay_header_from_reference(ref_path, cdx_slot)
    except (ValueError, IOError) as e:
        print(f"  [FAIL] Reference header error: {e}")
        return False

    new_save = header + body

    if dry_run:
        print(f"  [DRY RUN] Would write {len(new_save)} bytes to {out_path}")
        return True

    os.makedirs(output_dir, exist_ok=True)

    # Backup existing
    if os.path.isfile(out_path):
        backup_dir = os.path.join(output_dir, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"{out_name}.{timestamp}.bak"
        shutil.copy2(out_path, os.path.join(backup_dir, backup_name))
        print(f"    Backup saved: {backup_name}")

    with open(out_path, 'wb') as f:
        f.write(new_save)
    print(f"  [OK] Written {len(new_save)} bytes to {out_name}")
    return True


def run_c2u(repl_path, ref_path, output_dir, dry_run=False):
    """CODEX → Uplay: find .sav files, convert to .save using reference header."""
    print("── Step 1: Validating reference .save file ──")
    if not os.path.isfile(ref_path):
        print(f"  [FAIL] Reference file not found: {ref_path}")
        return False

    try:
        validate_uplay_save(ref_path)
        print(f"  [OK] Reference: {os.path.basename(ref_path)}")
    except ValueError as e:
        print(f"  [FAIL] Invalid reference: {e}")
        return False

    print("\n── Step 2: Finding CDX saves ──")
    cdx_files = find_cdx_files(repl_path)

    if not cdx_files:
        print(f"  [!] No .sav files found in: {repl_path}")
        return False

    print(f"  Found {len(cdx_files)} CDX file(s):")
    for slot in sorted(cdx_files.keys()):
        fp = cdx_files[slot]
        fsize = os.path.getsize(fp)
        print(f"    {os.path.basename(fp)} (slot {slot}, {fsize:,} bytes)")

    print("\n── Step 3: Converting ──")
    success = 0
    for slot in sorted(cdx_files.keys()):
        if convert_c2u_save(cdx_files[slot], ref_path, output_dir, slot, dry_run):
            success += 1

    print(f"\n  Result: {success}/{len(cdx_files)} converted successfully")
    if success > 0 and not dry_run:
        print(f"\n  Output directory: {output_dir}")
    return success > 0


# --- CLI ---

def print_header():
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║    FC5 Save Converter — Uplay ↔ CODEX    ║")
    print("  ║          v1.1 — Far Cry 5 GameId 1803    ║")
    print("  ╚══════════════════════════════════════════╝")
    print()


def main():
    parser = argparse.ArgumentParser(
        description='Convert FC5 saves between Ubisoft Connect (.save) and CODEX (.sav) formats',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  u2c (default)  Uplay → CODEX  — Wraps .save files in CDX headers
  c2u            CODEX → Uplay  — Wraps .sav files using a reference .save header

Examples:
  %(prog)s --mode u2c --replacement "C:\\Users\\Me\\Downloads\\030 Holland Valley\\1803"
  %(prog)s --mode c2u --replacement "C:\\CODEX\\Saves\\FarCry5" --reference "C:\\Users\\Me\\valid.save"
  %(prog)s --mode c2u --replacement "C:\\CODEX\\Saves\\FarCry5\\0x1.sav" --reference "C:\\Users\\Me\\valid.save"
        """
    )

    parser.add_argument(
        '--mode', '-m',
        choices=['u2c', 'c2u'],
        default='u2c',
        help='Conversion direction (default: u2c)'
    )

    parser.add_argument(
        '--replacement', '-r',
        required=True,
        help='u2c: path to .save files (file, folder, or folder with 1803/ subfolder). c2u: path to .sav files'
    )

    parser.add_argument(
        '--save-dir', '-d',
        default=r'C:\Users\Public\Documents\uPlay\CODEX\Saves\FarCry5',
        help='u2c: CODEX save directory (default: %(default)s). c2u: output directory'
    )

    parser.add_argument(
        '--reference', '-ref',
        default=None,
        help='c2u: path to a valid .save file to use as header template (required in c2u mode)'
    )

    parser.add_argument(
        '--dry-run', '-n',
        action='store_true',
        help='Preview what would be done without writing any files'
    )

    args = parser.parse_args()
    print_header()

    repl_path = os.path.abspath(args.replacement)

    if args.mode == 'u2c':
        save_dir = os.path.abspath(args.save_dir)
        if not os.path.isdir(save_dir) and not args.dry_run:
            os.makedirs(save_dir, exist_ok=True)
            print(f"  [OK] Created save directory: {save_dir}")

        print(f"  Mode:          Uplay → CODEX")
        print(f"  Replacement:   {repl_path}")
        print(f"  Save directory:{save_dir}")
        print()

        success = run_u2c(repl_path, save_dir, dry_run=args.dry_run)

    else:  # c2u
        output_dir = os.path.abspath(args.save_dir)
        ref_path = os.path.abspath(args.reference) if args.reference else None

        if not ref_path:
            print("  [FAIL] --reference is required in c2u mode.\n")
            parser.print_help()
            return

        print(f"  Mode:          CODEX → Uplay")
        print(f"  Replacement:   {repl_path}")
        print(f"  Reference:     {ref_path}")
        print(f"  Output dir:    {output_dir}")
        print()

        success = run_c2u(repl_path, ref_path, output_dir, dry_run=args.dry_run)

    # Summary
    print("\n── Summary ──")
    if success:
        if args.dry_run:
            print("  DRY RUN — no files were written.")
        else:
            print("  Done.")
    else:
        print("  No files were converted. Check paths and try again.")

    print()


if __name__ == '__main__':
    main()
