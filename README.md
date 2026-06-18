# FC5 Save Converter — Uplay → CODEX

Converts **Ubisoft Connect (.save)** saves to **CODEX (.sav)** format for **Far Cry 5** (GameId 1803).

If you downloaded someone else's FC5 saves in Ubisoft Connect format and play the CODEX cracked version, this script bridges the gap so the game recognises and loads them.

## How It Works

The CODEX emulator ships with a built-in save converter (`ConverterEnabled=1` in `CODEX.ini`). It can re-encrypt saves for your local profile — but only if the file is wrapped in a valid CODEX `.sav` container first.

This script:

1. Reads the **profile identifier** from your existing working CODEX saves
2. Extracts the **encrypted body** from the Ubisoft Connect `.save` file (skipping the 552-byte Ubisoft header)
3. Wraps it in a **CDX-format header** with the correct profile ID and save slot
4. Backs up the original files, then writes the converted files

After conversion, launching FC5 triggers the CODEX emulator to finish the job — decrypting with the original key and re-encrypting with your profile's key. The game then shows **"Continue"** instead of silently starting a new game.

## Requirements

- **Python 3.6+** (no extra packages needed — pure stdlib)
- **Far Cry 5 (CODEX)** with `ConverterEnabled=1` in `CODEX.ini`
- A **Ubisoft Connect (.save)** save file you want to convert

## Installation

```bash
git clone https://github.com/Timoteee/fc5-save-converter.git
cd fc5-save-converter
```

Or download `uplay_to_codx_converter.py` directly — it's a single-file script.

## Usage

### Basic conversion

```batch
python uplay_to_codx_converter.py --replacement "C:\path\to\030 Holland Valley\1803"
```

This:
- Reads your existing saves from the default CODEX directory
- Finds `1.save` and `2.save` in the replacement folder
- Converts both and writes them back

### Custom save directory

```batch
python uplay_to_codx_converter.py --replacement "D:\saves\1803" --save-dir "D:\CODEX\Saves\FarCry5"
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

1. The script **backs up** your existing `0x1.sav` and `0x2.sav` files to a `backups\` folder (timestamped)
2. Converted files are written in place
3. **Launch Far Cry 5** — the CODEX emulator's save converter detects the new files and re-encrypts them for your profile
4. You should see **"Continue"** on the main menu

> **Note:** The conversion may take a few seconds the first time you launch the game. If you still see "New Game" only, check that `ConverterEnabled=1` is set in your `CODEX.ini`.

## File Format Summary

| Format | Header Size | Magic Bytes | File Extension |
|--------|------------|-------------|----------------|
| CODEX  | 272 bytes  | `CDX\0`     | `.sav`         |
| Uplay  | 552 bytes  | `\x24\x02`  | `.save`        |

Both formats wrap an AES-256-CBC encrypted save body. The CDX format uses a profile-derived key while Uplay uses an account-derived key — the CODEX emulator handles the cross-wiring.

## License

MIT
