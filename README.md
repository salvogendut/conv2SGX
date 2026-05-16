![Source image](pictures/manado-miyazaki.png)
![Amstrad CPC preview](pictures/manadOU_preview.png)
![MSX preview](pictures/MmanFH_preview.png)

# conv2SGX

Convert PNG/JPG images to SymbOS SGX graphic format, for use as wallpapers on [SymbOS](https://symbos.org) (Z80-based OS running on Amstrad CPC, MSX, and other platforms).

## Features

- **Amstrad CPC preset** — `--amstrad`: 320×200, 4-colour, ZX0-compressed; auto-named `A{name}{dither}L.SGX`
- **MSX preset** — `--msx`: 512×212, 16-colour, uncompressed; auto-named `M{name}{dither}H.SGX`
- **4-colour mode** — CPC Mode 1 encoding (4 pixels/byte), two 160×200 chunks matching the SymbOS wallpaper loader layout
- **16-colour mode** — MSX Screen 5/7 encoding (2 pixels/byte), extended SGX chunks
- **ZX0 compression** — inverted ZX0 via Salvador optimal compressor with SymbOS Banking_Decompress wrapper; typically 40–70% size reduction
- **Uncompressed output** — `--no-compress` produces raw SGX matching the official FantasyKeithParkinson/EroticPhotos wallpaper format (16009 bytes)
- **Dithering** — Floyd-Steinberg (default), Atkinson, ordered (Bayer), or none
- **Flexible scaling** — fit, stretch, scale factor, or exact dimensions

## Requirements

- Python 3 + Pillow (`pip install Pillow`)
- `zx0tool` binary (for compression) — build it once:

```bash
make zx0tool
```

The Makefile links against the [Salvador](https://github.com/emmanuel-marty/salvador) ZX0 optimal compressor. Salvador source must be present at `../rasm/salvador/src/`.

## Usage

```
conv2sgx.py [-h] [-o FILE] [-c {4,16}] [-d {none,floyd-steinberg,atkinson,ordered}]
            [-W PX] [-H PX] [-s FACTOR] [--fit WxH] [--no-aspect]
            [--preview] [--no-compress] [--amstrad | --msx]
            input
```

### Options

| Option | Description |
|--------|-------------|
| `-o FILE` | Output path (default: `<input>.sgx`, or auto-named with `--amstrad`/`--msx`) |
| `-c {4,16}` | Colour depth — 4 (CPC Mode 1) or 16 (MSX Sc5/7), default 16 |
| `-d DITHER` | Dithering: `floyd-steinberg` (default), `atkinson`, `ordered`, `none` |
| `-W PX` | Target width |
| `-H PX` | Target height |
| `-s FACTOR` | Uniform scale factor (e.g. `0.5`) |
| `--fit WxH` | Fit within WxH preserving aspect ratio |
| `--no-aspect` | Stretch to exact size (use with `-W` / `-H`) |
| `--preview` | Save a PNG preview alongside the SGX |
| `--no-compress` | Raw uncompressed output (no ZX0) |
| `--amstrad` | Amstrad CPC preset: 320×200, 4-colour, compressed; auto-names output |
| `--msx` | MSX preset: 512×212, 16-colour, uncompressed; auto-names output |

`--amstrad` and `--msx` are mutually exclusive.

### Auto-naming scheme (--amstrad / --msx)

Output filename: `{P}{NNN}{D}{R}.SGX`

| Part | Values | Meaning |
|------|--------|---------|
| `P` | `A` / `M` | Platform: Amstrad or MSX |
| `NNN` | first 3 chars of input filename | e.g. `man` from `manado.png` |
| `D` | `F` / `A` / `O` / `N` | Dither: Floyd-Steinberg, Atkinson, Ordered, None |
| `R` | `L` / `H` | Resolution: L = 320×200, H = anything higher |

Examples: `AmanFL.SGX`, `MmekAH.SGX`, `AsadOL.SGX`

### Examples

```bash
# Amstrad CPC wallpaper — all dither modes
python3 conv2sgx.py photo.png --amstrad
python3 conv2sgx.py photo.png --amstrad -d atkinson
python3 conv2sgx.py photo.png --amstrad -d ordered
python3 conv2sgx.py photo.png --amstrad -d none

# MSX wallpaper
python3 conv2sgx.py photo.png --msx
python3 conv2sgx.py photo.png --msx -d atkinson

# Manual control
python3 conv2sgx.py photo.png -c 4 -W 320 -H 200 --no-aspect          # compressed
python3 conv2sgx.py photo.png -c 4 -W 320 -H 200 --no-aspect --no-compress  # raw
python3 conv2sgx.py photo.png -c 16 -d atkinson --fit 320x200
python3 conv2sgx.py photo.png -s 0.5 --preview
```

## SGX Format Notes

### 4-colour (simple chunks)

- Header: `[row_bytes|0x80] [width_px] [height_px]` (compressed) or `[row_bytes] [width_px] [height_px]` (raw)
- Compressed: followed by 2-byte LE payload size + ZX0 payload
- Raw: followed by pixel data directly
- `row_bytes` = width / 4; must be ≤ 63 (6-bit field)
- SymbOS wallpaper loader requires **160px-wide chunks** (row_bytes=40); 320px images split into two 160×200 chunks

### 16-colour (extended chunks)

- Header: `0xC0 0x05 [row_bytes_lo] [row_bytes_hi] [w_lo] [w_hi] [h_lo] [h_hi]` (compressed)
- Or `0x40 0x05 ...` for uncompressed
- Compressed: followed by 2-byte LE payload size + ZX0 payload

### ZX0 / SymbOS wrapper

SymbOS uses **inverted ZX0** (V2). The Banking_Decompress wrapper format is:

```
[last 4 bytes of uncompressed data] [0x00 0x00] [ZX0 stream of all-but-last-4 bytes]
```

All SGX files end with a 3-byte null terminator (`00 00 00`).

## Output directory layout

```
sources/    — input images (gitignored)
samples/    — generated SGX files and PNG previews (gitignored)
pictures/   — committed example images and previews for this README
```
