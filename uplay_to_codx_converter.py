#!/usr/bin/env python3
"""
Uplay to CODEX FC5 Save Converter
===================================
Converts Ubisoft Connect (.save) saves to CODEX (.sav) format
for Far Cry 5 (GameId 1803).

The CODEX emulator has a built-in save converter (ConverterEnabled=1)
that handles the actual decryption/re-encryption if you give it a
properly formatted .sav file. This tool creates that bridge.

How it works:
  1. Reads your existing working CODEX .sav files from the save directory
     to extract the profile identifier (suffix in the CDX header).
  2. Scans the replacement folder for .save files (1.save, 2.save, etc.)
  3. Extracts the encrypted body from each .save file (offset 0x228+)
  4. Wraps it in a CDX-compatible header with the correct profile suffix
  5. Backs up your original .sav files
  6. Writes the converted files back to the save directory
  7. When you launch FC5, the CODEX emulator's converter finishes the job

Usage:
  python uplay_to_codx_converter.py --replacement <path_to_1803_folder>

Examples:
  # Convert saves from a single location folder
  python uplay_to_codx_converter.py --replacement "C:\\Users\\Me\\Downloads\\030 Holland Valley\\1803"

  # Use a custom save directory
  python uplay_to_codx_converter.py --replacement "D:\\saves\\1803" --save-dir "D:\\CODEX\\Saves\\FarCry5"

  # Dry run (no files written)
  python uplay_to_codx_converter.py --replacement "D:\\saves\\1803" --dry-run

  # Scan all 1803 subfolders
  python uplay_to_codx_converter.py --replacement "C:\\Users\\Me\\Downloads\\save_far_cry_5"
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
SLOT_MAP = {'1': '0x1.sav', '2': '0x2.sav'}


# --- Core logic ---

def find_profile_suffix(save_dir):
    """
    Read a working CDX .sav file to extract the profile identifier
    (the numeric suffix in the CDX name field, e.g. '134261316324923516').
    Falls back to checking multiple slot files if needed.
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
            # Look for the CDX magic and name string
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


def _scan_folder_for_saves(folder):
    """Scan a single folder for 1.save/2.save, return slot->path dict."""
    result = {}
    for fname in os.listdir(folder):
        if fname.endswith('.save'):
            base = fname.replace('.save', '')
            if base in ('1', '2'):
                result[base] = os.path.join(folder, fname)
        # Also check immediate '1803' sub-folder
        if fname == '1803' and os.path.isdir(os.path.join(folder, fname)):
            sub = os.path.join(folder, fname)
            for sf in os.listdir(sub):
                if sf.endswith('.save'):
                    sbase = sf.replace('.save', '')
                    if sbase in ('1', '2'):
                        result[sbase] = os.path.join(sub, sf)
    return result


def find_save_files(replacement_path):
    """
    Find .save files in the given replacement path.
    Returns a dict mapping slot number -> file path.

    Supports:
      - Single file (1.save, 2.save)
      - Folder with 1.save/2.save directly, or an 1803/ subfolder
      - Parent folder with subfolders containing 1803/ — prompts user
    """
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

    # Direct scan
    slot_files = _scan_folder_for_saves(replacement_path)

    # If nothing found, scan first-level subdirectories
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
    """
    Validate that a .save file is a Uplay-format Far Cry 5 save.
    Returns (body_offset, body_size) or raises ValueError.
    """
    with open(filepath, 'rb') as f:
        data = f.read()

    if len(data) < UPLAY_HEADER_SIZE + 16:
        raise ValueError(f"File too small ({len(data)} bytes, need at least {UPLAY_HEADER_SIZE + 16})")

    # Check for Uplay magic (0x2402 at offset 0)
    # Some 1803 saves may have slightly different first bytes
    first_word = int.from_bytes(data[0:4], 'little')
    has_uplay_header = (
        first_word == 0x00000224 or  # 0x2402 as LE32 = 0x00000224
        data[0:2] == b'\x24\x02' or
        data[0:2] == b'\x02\x24'
    )

    if not has_uplay_header:
        # Relaxed check: just make sure the file is large enough and
        # doesn't look like a CDX file
        if data[0:4] == CDX_MAGIC:
            raise ValueError("File appears to be already in CDX format (.sav)")
        print(f"  [!] Warning: {os.path.basename(filepath)} doesn't have standard Ubisoft header magic (0x2402)")
        print(f"      First bytes: {data[0:8].hex()}")

    # The encrypted body is at offset 0x228 for 1803-format saves
    body_offset = UPLAY_HEADER_SIZE
    body_size = len(data) - body_offset

    if body_size <= 0:
        raise ValueError(f"Empty body at offset 0x{body_offset:x}")

    return body_offset, body_size


def make_cdx_header(slot_number, body_size, profile_suffix):
    """
    Build a CDX header matching the CODEX format.
    """
    header = bytearray(CDX_HEADER_SIZE)

    # CDX magic
    header[0:4] = CDX_MAGIC

    # Slot (LE32) — 0x1 -> slot 1, 0x2 -> slot 2
    slot_val = int(slot_number)
    header[4:8] = slot_val.to_bytes(4, 'little')

    # Body size (LE32)
    header[8:12] = body_size.to_bytes(4, 'little')

    # Name string: saveSlot<N>.sav.<profile_suffix> + null terminator
    name = f"saveSlot{slot_number}.sav.{profile_suffix}\0"
    name_bytes = name.encode('ascii')
    if len(name_bytes) > CDX_HEADER_SIZE - 0x0C:
        raise ValueError(f"Name too long: {name}")
    header[0x0C:0x0C + len(name_bytes)] = name_bytes

    # Rest is already zero-filled (bytearray default)
    return bytes(header)


def convert_save(replacement_path, save_dir, profile_suffix, dry_run=False):
    """
    Convert a single .save file and place the result in save_dir.
    Returns True on success.
    """
    filename = os.path.basename(replacement_path)
    slot = filename.replace('.save', '')  # '1' or '2'
    sav_filename = f"0x{slot}.sav"
    sav_path = os.path.join(save_dir, sav_filename)

    print(f"\n  Converting: {filename} -> {sav_filename}")

    # Validate the replacement file
    try:
        body_offset, body_size = validate_uplay_save(replacement_path)
    except ValueError as e:
        print(f"  [FAIL] {e}")
        return False

    print(f"    Body at offset 0x{body_offset:x}, {body_size} bytes")

    # Read the encrypted body
    with open(replacement_path, 'rb') as f:
        f.seek(body_offset)
        body = f.read()

    # Build CDX header
    try:
        header = make_cdx_header(slot, len(body), profile_suffix)
    except ValueError as e:
        print(f"  [FAIL] Header error: {e}")
        return False

    new_sav = header + body

    if dry_run:
        print(f"  [DRY RUN] Would write {len(new_sav)} bytes to {sav_path}")
        return True

    # Backup existing file
    if os.path.isfile(sav_path):
        backup_dir = os.path.join(save_dir, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"{sav_filename}.{timestamp}.bak"
        backup_path = os.path.join(backup_dir, backup_name)
        shutil.copy2(sav_path, backup_path)
        print(f"    Backup saved: {backup_name}")
    else:
        print(f"    No existing file to back up")

    # Write new file
    with open(sav_path, 'wb') as f:
        f.write(new_sav)

    print(f"  [OK] Written {len(new_sav)} bytes to {sav_filename}")
    return True


def convert_all(replacement_path, save_dir, profile_suffix, dry_run=False):
    """
    Find all .save files from replacement_path and convert them.
    """
    slot_files = find_save_files(replacement_path)

    if not slot_files:
        print("\n  [!] No .save files found. Expected files named '1.save' and '2.save'")
        print(f"      Checked: {replacement_path}")
        if os.path.isdir(replacement_path):
            # Check if there are subdirectories with 1803/ folders
            candidates = []
            for entry in sorted(os.listdir(replacement_path)):
                subpath = os.path.join(replacement_path, entry)
                if os.path.isdir(subpath):
                    # Quick check
                    direct = os.path.join(subpath, '1.save')
                    sub1803 = os.path.join(subpath, '1803', '1.save')
                    if os.path.isfile(direct) or os.path.isfile(sub1803):
                        candidates.append(entry)
            if candidates:
                print(f"      (hint: use --replacement with one of the subfolders, e.g.)")
                print(f"      --replacement \"{replacement_path}\\{candidates[0]}\"")
            else:
                sub1803 = os.path.join(replacement_path, '1803')
                if os.path.isdir(sub1803):
                    print(f"      (try: --replacement \"{replacement_path}\\1803\")")
        return False

    print(f"\n  Found {len(slot_files)} save file(s):")
    for slot, fp in sorted(slot_files.items()):
        fsize = os.path.getsize(fp)
        print(f"    Slot {slot}: {os.path.basename(fp)} ({fsize:,} bytes)")

    success = 0
    for slot in sorted(slot_files.keys()):
        if convert_save(slot_files[slot], save_dir, profile_suffix, dry_run):
            success += 1

    print(f"\n  Result: {success}/{len(slot_files)} converted successfully")
    if success > 0 and not dry_run:
        print("\n  Next step: Launch Far Cry 5. The CODEX emulator's")
        print("  save converter (ConverterEnabled=1) will handle the")
        print("  final decryption/re-encryption automatically.")
    return success > 0


def print_header():
    """Print the branding header."""
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║    Uplay → CODEX  FC5 Save Converter     ║")
    print("  ║          v1.0 — Far Cry 5 GameId 1803    ║")
    print("  ╚══════════════════════════════════════════╝")
    print()


def main():
    parser = argparse.ArgumentParser(
        description='Convert Uplay (.save) saves to CODEX (.sav) format for Far Cry 5',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --replacement "C:\\Users\\Me\\Downloads\\030 Holland Valley\\1803"
  %(prog)s --replacement "D:\\saves\\1803" --save-dir "D:\\CODEX\\Saves\\FarCry5"
  %(prog)s --replacement "D:\\saves\\1803" --dry-run
        """
    )

    parser.add_argument(
        '--replacement', '-r',
        required=True,
        help='Path to the replacement .save file(s) — a single file, a folder containing 1.save/2.save, or a folder with an 1803/ subfolder'
    )

    parser.add_argument(
        '--save-dir', '-d',
        default=r'C:\Users\Public\Documents\uPlay\CODEX\Saves\FarCry5',
        help='CODEX save directory (default: %%default)'
    )

    parser.add_argument(
        '--dry-run', '-n',
        action='store_true',
        help='Preview what would be done without writing any files'
    )

    args = parser.parse_args()

    print_header()

    save_dir = os.path.abspath(args.save_dir)
    repl_path = os.path.abspath(args.replacement)

    # Validate save directory
    if not os.path.isdir(save_dir):
        if args.dry_run:
            print(f"  [!] Save directory doesn't exist (will be created): {save_dir}")
        else:
            os.makedirs(save_dir, exist_ok=True)
            print(f"  [OK] Created save directory: {save_dir}")

    print(f"  Save directory: {save_dir}")
    print(f"  Replacement:    {repl_path}")

    # Step 1: Extract profile suffix from existing CODEX saves
    print("\n── Step 1: Reading profile identifier from existing saves ──")
    profile_suffix = find_profile_suffix(save_dir)

    if not profile_suffix:
        # Fallback: ask the user or use a common CODEX default
        print("\n  [!] Could not read profile suffix from save directory.")
        print("      If you know your CODEX AccountId from CODEX.ini,")
        print("      you can enter the numeric part here.")
        print("      (Press Enter to use a common default)")
        user_input = input("  Profile suffix: ").strip()
        if user_input:
            profile_suffix = user_input
        else:
            # Extract from default CODEX AccountId if possible
            profile_suffix = "134261316324923516"
            print(f"  Using default suffix: {profile_suffix}")
            print("  (You may need to update CODEX.ini AccountId to match)")

    print(f"  Profile suffix: {profile_suffix}")

    # Step 2: Find and convert replacement files
    print("\n── Step 2: Converting replacement saves ──")
    success = convert_all(repl_path, save_dir, profile_suffix, dry_run=args.dry_run)

    # Summary
    print("\n── Summary ──")
    if success:
        if args.dry_run:
            print("  DRY RUN — no files were written.")
        else:
            print("  Conversion complete.")
            print("  Launch Far Cry 5 and check for 'Continue' on the main menu.")
    else:
        print("  No files were converted. Check paths and try again.")

    print()


if __name__ == '__main__':
    main()
