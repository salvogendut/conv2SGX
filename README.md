![Source image](pictures/manado-miyazaki.png)
![Amstrad CPC preview](pictures/manadOU_preview.png)
![MSX preview](pictures/MmanFH_preview.png)

# conv2SGX

Convert PNG/JPG images to SymbOS SGX graphic format, for use as wallpapers on [SymbOS](https://symbos.org) (Z80-based OS running on Amstrad CPC, MSX, and other platforms).

## Features

- **Machine presets** — one flag sets the resolution, colour depth, and 8.3 filename automatically
- **8.3 filename scheme** — `--8.3`: short filenames for machines without long filename support
- **4-colour mode** — CPC Mode 1 encoding (4 pixels/byte), 160px-wide chunks matching the SymbOS wallpaper loader layout
- **16-colour mode** — MSX Screen 5/7 encoding (2 pixels/byte), extended SGX chunks
- **Uncompressed by default** — raw SGX matching official wallpaper format; add `--compress` for ZX0
- **ZX0 compression** — opt-in with `--compress`; inverted ZX0 via Salvador optimal compressor with SymbOS Banking_Decompress wrapper; typically 40–70% size reduction
- **Dithering** — Floyd-Steinberg (default), Atkinson, ordered (Bayer), or none
- **Flexible scaling** — fit, stretch, scale factor, or exact dimensions
- **Batch conversion** — `convert-all.sh` converts everything in `sources/` to all presets

## Requirements

- Python 3 + Pillow (`pip install Pillow`)
- `zx0tool` binary (only needed for `--compress`) — build it once:

```bash
make zx0tool
```

The Makefile links against the [Salvador](https://github.com/emmanuel-marty/salvador) ZX0 optimal compressor. Salvador source must be present at `../rasm/salvador/src/`.

## Usage

```
conv2sgx.py [-h] [-o FILE] [-c {4,16}] [-d {none,floyd-steinberg,atkinson,ordered}]
            [-W PX] [-H PX] [-s FACTOR] [--fit WxH] [--no-aspect]
            [--preview] [--compress] [--8.3]
            [--cpc-m0 | --cpc-m1 | --cpc-m2 | --msx | --msx2-l-16 | --msx2-l-4 | --msx2-h-16 | --msx2-h-4]
            input
```

### Options

| Option | Description |
|--------|-------------|
| `-o FILE` | Output path (default: `<input>.SGX`) |
| `-c {4,16}` | Colour depth — 4 or 16, default 16 |
| `-d DITHER` | Dithering: `floyd-steinberg` (default), `atkinson`, `ordered`, `none` |
| `-W PX` | Target width |
| `-H PX` | Target height |
| `-s FACTOR` | Uniform scale factor (e.g. `0.5`) |
| `--fit WxH` | Fit within WxH preserving aspect ratio |
| `--no-aspect` | Stretch to exact size (use with `-W` / `-H`) |
| `--preview` | Save a PNG preview alongside the SGX |
| `--compress` | Apply ZX0 compression (default is uncompressed) |
| `--8.3` | Use 8.3 filename scheme: `{prefix}{3-letter-name}{dither}{L\|H}.SGX` |

### Machine presets

All presets imply `--8.3` naming and `--no-aspect` scaling.

| Preset | Resolution | Colours | 8.3 prefix | Notes |
|--------|-----------|---------|-----------|-------|
| `--cpc-m0` | 160×200 | 16 | `C0` | CPC Mode 0 |
| `--cpc-m1` | 320×200 | 4 | `C1` | CPC Mode 1 |
| `--cpc-m2` | 640×200 | 4 | `C2` | CPC Mode 2 (2-colour not yet supported) |
| `--msx` | 256×192 | 16 | `M1` | MSX1 |
| `--msx2-l-16` | 256×212 | 16 | `M5` | MSX2 Screen 5 |
| `--msx2-l-4` | 256×212 | 4 | `M6` | MSX2 Screen 6 low |
| `--msx2-h-16` | 512×212 | 16 | `M7` | MSX2 Screen 7 |
| `--msx2-h-4` | 512×212 | 4 | `M8` | MSX2 Screen 6 high |

### 8.3 filename scheme

Output filename: `{PP}{NNN}{D}{R}.SGX`

| Part | Values | Meaning |
|------|--------|---------|
| `PP` | `C0`–`C2`, `M1`, `M5`–`M8` | Preset (see table above) |
| `NNN` | first 3 chars of input filename | e.g. `man` from `manado.png` |
| `D` | `F` / `A` / `O` / `N` | Dither: Floyd-Steinberg, Atkinson, Ordered, None |
| `R` | `L` / `H` | Resolution: L = width ≤ 320, H = width > 320 |

Examples: `C1manFL.SGX`, `M7mekAH.SGX`, `M5sadOL.SGX`

### Examples

```bash
# CPC Mode 1 wallpaper (320×200, 4-colour)
python3 conv2sgx.py photo.png --cpc-m1
python3 conv2sgx.py photo.png --cpc-m1 -d atkinson
python3 conv2sgx.py photo.png --cpc-m1 --compress      # with ZX0 compression

# MSX2 wallpapers
python3 conv2sgx.py photo.png --msx2-h-16              # 512×212, 16-colour
python3 conv2sgx.py photo.png --msx2-l-4 -d ordered    # 256×212, 4-colour, ordered dither

# Manual control
python3 conv2sgx.py photo.png -c 4 -W 320 -H 200 --no-aspect           # uncompressed
python3 conv2sgx.py photo.png -c 4 -W 320 -H 200 --no-aspect --compress # ZX0 compressed
python3 conv2sgx.py photo.png -c 16 -d atkinson --fit 320x200
python3 conv2sgx.py photo.png -s 0.5 --preview

# Batch conversion (all presets, all dither modes, all sources)
./convert-all.sh
```

## SGX Format Notes

### 4-colour (simple chunks)

- Header: `[row_bytes] [width_px] [height_px]` (raw) or `[row_bytes|0x80] [width_px] [height_px]` (compressed)
- Compressed: followed by 2-byte LE payload size + ZX0 payload
- Raw: followed by pixel data directly
- `row_bytes` = width / 4; must be ≤ 63 (6-bit field)
- SymbOS wallpaper loader requires **160px-wide chunks** (row_bytes=40); 320px images split into two 160×200 chunks

### 16-colour (extended chunks)

- Header: `0x40 0x05 [row_bytes_lo] [row_bytes_hi] [w_lo] [w_hi] [h_lo] [h_hi]` (raw)
- Or `0xC0 0x05 ...` for compressed
- Compressed: followed by 2-byte LE payload size + ZX0 payload

### ZX0 / SymbOS wrapper

SymbOS uses **inverted ZX0** (V2). The Banking_Decompress wrapper format is:

```
[last 4 bytes of uncompressed data] [0x00 0x00] [ZX0 stream of all-but-last-4 bytes]
```

All SGX files end with a 3-byte null terminator (`00 00 00`).

## Directory layout

```
sources/         — input images; only manado-miyazaki.png is committed
output/          — convert-all.sh writes here (gitignored except placeholder.txt)
  cpc/           — CPC Mode 0/1/2 outputs
  msx/           — MSX1 outputs
  msx2/          — MSX2 Screen 5/6/7 outputs
samples/         — committed example outputs (manado-miyazaki.png, all presets)
pictures/        — committed example images for this README
convert-all.sh   — batch script: converts everything in sources/ into output/
```
