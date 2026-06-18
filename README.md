# FC5 Save Converter — Uplay ↔ CODEX

Bidirectional converter between **Ubisoft Connect (.save)** and **CODEX (.sav)** save formats for **Far Cry 5** (GameId 1803).

## Problem

Far Cry 5 uses **encrypted save files** tied to a specific user profile ID. If you download a save from the internet or get one from a friend:

- **Ubisoft Connect** saves are encrypted with an account-derived key — another Uplay account can't read them.
- **CODEX (cracked)** saves use a different encryption key derived from the emulated profile ID. The crack wraps them in a custom `.sav` container (`CDX\0` header).

Attempting to use saves from one setup with the other produces either a **"Granite" error** (save decryption failure) or simply **shows "New Game"** with no "Continue" — the game silently rejects the save because the profile doesn't match.

The transfer is further complicated because:

- Both formats embed the user's **profile identifier** in the file header, which must match the running game's identity.
- The encrypted body is **AES-256-CBC** with a key derived from that profile ID — you can't just hex-edit the header and call it done.
- Existing conversion tools for FC5 saves are **non-existent or incomplete** — no dedicated utility handles this format bridge.

This tool solves the **format mismatch** by stripping the foreign wrapper and repackaging the encrypted save body in the correct container. In u2c mode, the CODEX emulator's built-in save converter (`ConverterEnabled=1`) then handles the actual key re-derivation the first time you launch the game.

## Modes

### u2c (default) — Uplay → CODEX

If you downloaded someone else's FC5 saves in Ubisoft Connect format and play the CODEX cracked version, this mode bridges the gap so the game recognises and loads them.

The CODEX emulator has a built-in save converter (`ConverterEnabled=1` in `CODEX.ini`). It can re-encrypt saves for your local profile — but only if the file is wrapped in a valid CODEX `.sav` container first.

This script:

1. Reads the **profile identifier** from your existing working CODEX saves
2. Extracts the **encrypted body** from the Ubisoft Connect `.save` file (skipping the 552-byte Ubisoft header)
3. Wraps it in a **CDX-format header** with the correct profile ID and save slot
4. Backs up the original files, then writes the converted files

After conversion, launching FC5 triggers the CODEX emulator to finish the job — decrypting with the original key and re-encrypting with your profile's key. The game then shows **"Continue"** instead of silently starting a new game.

### c2u — CODEX → Uplay

If you have CODEX saves and want to use them on a legitimate Ubisoft Connect installation, this mode wraps the `.sav` files using a valid `.save` file as a header template.

You need to provide a reference `.save` file from your Uplay account (any save works — it's used only for the header/profile metadata, not the game data):

1. Takes your existing CODEX `.sav` files
2. Extracts the **encrypted body** from each (skipping the 272-byte CDX header)
3. Wraps it in a **Uplay-format header** copied from your reference `.save` file (with the slot name updated)
4. Writes the converted `.save` files to the output directory

## Requirements

- **Python 3.6+** (no extra packages needed — pure stdlib)
- **Far Cry 5 (CODEX)** with `ConverterEnabled=1` in `CODEX.ini` (u2c mode only)
- A **valid .save or .sav file** depending on which direction you're converting

## Installation

```bash
git clone https://github.com/Timoteee/fc5-save-converter.git
cd fc5-save-converter
```

Or download `uplay_to_codx_converter.py` directly — it's a single-file script.

## Usage

### Uplay → CODEX (default)

```batch
python uplay_to_codx_converter.py --replacement "C:\path\to\030 Holland Valley\1803"
```

This:
- Reads your existing CODEX saves from the default save directory to extract the profile ID
- Finds `1.save` and `2.save` in the replacement folder
- Converts both and writes them back to the save directory

### CODEX → Uplay (reverse)

```batch
python uplay_to_codx_converter.py --mode c2u --replacement "C:\CODEX\Saves\FarCry5" --reference "C:\path\to\valid_uplay.save"
```

This:
- Finds `0x1.sav` and `0x2.sav` in the source folder
- Uses the reference `.save` file as a header template
- Writes `1.save` and `2.save` to the output directory (defaults to the same save dir path)

You can also convert a single file:

```batch
python uplay_to_codx_converter.py --mode c2u --replacement "C:\CODEX\Saves\FarCry5\0x1.sav" --reference "C:\path\to\valid_uplay.save"
```

### Custom output directory

In u2c mode, `--save-dir` is where the converted `.sav` files go (the CODEX save folder). In c2u mode, it's the output directory for `.save` files.

```batch
python uplay_to_codx_converter.py --mode c2u -r "C:\CODEX\Saves\FarCry5" -ref "valid.save" -d "C:\output"
```

### Preview without writing

```batch
python uplay_to_codx_converter.py --replacement "D:\saves\1803" --dry-run
```

### Auto-detect save folders

If you have a folder with multiple sub-folders (e.g., `030 Holland Valley`, `050 Henbane River`, etc.):

```batch
python uplay_to_codx_converter.py --replacement "C:\Users\Me\Downloads\save_far_cry_5"
```

The script scans for `.save` files and lists what it finds, then hints the exact command to use.

### Full help

```batch
python uplay_to_codx_converter.py --help
```

## Default Save Directory

The script assumes your CODEX saves live at:

```
C:\Users\Public\Documents\uPlay\CODEX\Saves\FarCry5\
```

Override with `--save-dir` if yours is different.

## What Happens After Running

### u2c mode

1. The script **backs up** your existing `0x1.sav` and `0x2.sav` files to a `backups\` folder (timestamped)
2. Converted files are written in place
3. **Launch Far Cry 5** — the CODEX emulator's save converter detects the new files and re-encrypts them for your profile
4. You should see **"Continue"** on the main menu

> **Note:** The conversion may take a few seconds the first time you launch the game. If you still see "New Game" only, check that `ConverterEnabled=1` is set in your `CODEX.ini`.

### c2u mode

1. Existing `.save` files in the output directory are backed up to a `backups\` folder
2. Converted files are written
3. Copy the `.save` files to your Ubisoft Connect save directory and launch FC5

## File Format Summary

| Format | Header Size | Magic Bytes | File Extension |
|--------|-------------|-------------|----------------|
| CODEX  | 272 bytes   | `CDX\0`     | `.sav`         |
| Uplay  | 552 bytes   | `\x24\x02`  | `.save`        |

Both formats wrap an AES-256-CBC encrypted save body with profile-specific key derivation. The CODEX emulator's built-in converter handles the key cross-wiring in u2c mode.

## License

MIT
