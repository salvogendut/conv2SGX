#!/usr/bin/env python3
"""
conv2sgx.py - Convert PNG/JPG images to SymbOS SGX format

SGX chunk formats (CPCWiki spec):

  Simple chunk (4-colour only, row_bytes in bits 0-6, max 63 = 252 px wide):
    byte 0: [bit0-6] width in bytes, [bit7] compressed flag
    byte 1: width in pixels
    byte 2: height in pixels
    (if compressed: 2-byte LE compressed-payload size, then SymbOS ZX0 payload)
    (if raw:        pixel data directly)

  Extended chunk (16-colour; bit0-6 of byte 0 = 0x40 marker):
    byte 0: 0x40 | [bit7] compressed flag
    byte 1: type  (0 = 4-colour, 5 = 16-colour)
    bytes 2-3: width in bytes  (little-endian word)
    bytes 4-5: width in pixels (little-endian word)
    bytes 6-7: height in pixels (little-endian word)
    (if compressed: 2-byte LE compressed-payload size, then SymbOS ZX0 payload)
    (if raw:        pixel data directly)

SymbOS ZX0 payload (Banking_Decompress wrapper):
    bytes 0-3: last 4 bytes of uncompressed data
    bytes 4-5: uncompressed prefix size (always 0x00 0x00)
    bytes 6+:  ZX0-compressed stream of (uncompressed data minus last 4 bytes)
               using the inverted ZX0 variant (FLG_IS_INVERTED=1)

4-colour images: always split into simple chunks of ≤ 252 px (63 bytes/row).
16-colour images: split into extended chunks so each uncompressed payload ≤ 16 384 bytes.
All chunks are always compressed.  A 3-byte null terminator (00 00 00) closes the file.
"""

import argparse
import os
import subprocess
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required: pip install Pillow")

# -----------------------------------------------------------------------
# SymbOS fixed palette (8-bit sRGB, from gfx2sgx.c)
# The first 4 entries are the 4-colour sub-palette (CPC Mode 1).
# -----------------------------------------------------------------------
PALETTE = [
    (0xf7, 0xf7, 0x90),  # 0  light yellow
    (0x06, 0x06, 0x06),  # 1  near black
    (0xf7, 0x90, 0x06),  # 2  orange
    (0x90, 0x06, 0x06),  # 3  dark red
    (0x06, 0xf7, 0xf7),  # 4  cyan
    (0x06, 0x06, 0x90),  # 5  dark blue
    (0x90, 0x90, 0xf7),  # 6  light blue/violet
    (0x06, 0x06, 0xf7),  # 7  blue
    (0xf7, 0xf7, 0xf7),  # 8  white
    (0x06, 0x90, 0x06),  # 9  dark green
    (0x06, 0xf7, 0x06),  # 10 green
    (0xf7, 0x06, 0xf7),  # 11 magenta
    (0xf7, 0xf7, 0x06),  # 12 yellow
    (0x90, 0x90, 0x90),  # 13 gray
    (0xf9, 0x90, 0x90),  # 14 light pink
    (0xf7, 0x06, 0x06),  # 15 red
]

_PR = [c[0] for c in PALETTE]
_PG = [c[1] for c in PALETTE]
_PB = [c[2] for c in PALETTE]


# -----------------------------------------------------------------------
# Colour matching
# -----------------------------------------------------------------------

def _nearest(r, g, b, n):
    best, best_d = 0, 1 << 30
    for i in range(n):
        d = (_PR[i] - r) ** 2 + (_PG[i] - g) ** 2 + (_PB[i] - b) ** 2
        if d < best_d:
            best_d = d
            best = i
            if d == 0:
                break
    return best


# -----------------------------------------------------------------------
# Dithering algorithms
# -----------------------------------------------------------------------

def _clamp(v):
    return 0 if v < 0 else (255 if v > 255 else int(v))


def quantize_none(rgb_rows, width, height, n):
    out = []
    for row in rgb_rows:
        out.append([_nearest(row[x][0], row[x][1], row[x][2], n)
                    for x in range(width)])
    return out


def quantize_floyd_steinberg(rgb_rows, width, height, n):
    r = [[float(rgb_rows[y][x][0]) for x in range(width)] for y in range(height)]
    g = [[float(rgb_rows[y][x][1]) for x in range(width)] for y in range(height)]
    b = [[float(rgb_rows[y][x][2]) for x in range(width)] for y in range(height)]
    out = [[0] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            rv, gv, bv = _clamp(r[y][x]), _clamp(g[y][x]), _clamp(b[y][x])
            idx = _nearest(rv, gv, bv, n)
            out[y][x] = idx
            er, eg, eb = rv - _PR[idx], gv - _PG[idx], bv - _PB[idx]
            if x + 1 < width:
                r[y][x+1] += er * 7 / 16
                g[y][x+1] += eg * 7 / 16
                b[y][x+1] += eb * 7 / 16
            if y + 1 < height:
                if x > 0:
                    r[y+1][x-1] += er * 3 / 16
                    g[y+1][x-1] += eg * 3 / 16
                    b[y+1][x-1] += eb * 3 / 16
                r[y+1][x] += er * 5 / 16
                g[y+1][x] += eg * 5 / 16
                b[y+1][x] += eb * 5 / 16
                if x + 1 < width:
                    r[y+1][x+1] += er / 16
                    g[y+1][x+1] += eg / 16
                    b[y+1][x+1] += eb / 16
    return out


def quantize_atkinson(rgb_rows, width, height, n):
    r = [[float(rgb_rows[y][x][0]) for x in range(width)] for y in range(height)]
    g = [[float(rgb_rows[y][x][1]) for x in range(width)] for y in range(height)]
    b = [[float(rgb_rows[y][x][2]) for x in range(width)] for y in range(height)]
    out = [[0] * width for _ in range(height)]
    offsets = [(0, 1), (0, 2), (1, -1), (1, 0), (1, 1), (2, 0)]
    for y in range(height):
        for x in range(width):
            rv, gv, bv = _clamp(r[y][x]), _clamp(g[y][x]), _clamp(b[y][x])
            idx = _nearest(rv, gv, bv, n)
            out[y][x] = idx
            er, eg, eb = (rv - _PR[idx]) / 8, (gv - _PG[idx]) / 8, (bv - _PB[idx]) / 8
            for dy, dx in offsets:
                ny, nx = y + dy, x + dx
                if 0 <= ny < height and 0 <= nx < width:
                    r[ny][nx] += er
                    g[ny][nx] += eg
                    b[ny][nx] += eb
    return out


_BAYER4 = [
    [ 0,  8,  2, 10],
    [12,  4, 14,  6],
    [ 3, 11,  1,  9],
    [15,  7, 13,  5],
]


def quantize_ordered(rgb_rows, width, height, n):
    out = [[0] * width for _ in range(height)]
    scale = 24
    for y in range(height):
        for x in range(width):
            offset = (_BAYER4[y & 3][x & 3] / 15.0 - 0.5) * scale
            rv = _clamp(rgb_rows[y][x][0] + offset)
            gv = _clamp(rgb_rows[y][x][1] + offset)
            bv = _clamp(rgb_rows[y][x][2] + offset)
            out[y][x] = _nearest(rv, gv, bv, n)
    return out


# -----------------------------------------------------------------------
# SGX pixel encoding
# -----------------------------------------------------------------------

def _encode_4color_row(row, width):
    """CPC Mode 1: 4 pixels per byte (matching gfx2sgx.c exactly)."""
    data = []
    x = 0
    while x < width:
        byte = 0
        for offset in range(4):
            c = row[x + offset] if x + offset < width else 0
            if offset == 0:
                byte |= ((c & 1) << 7) | ((c & 2) << 2)
            elif offset == 1:
                byte |= ((c & 1) << 6) | ((c & 2) << 1)
            elif offset == 2:
                byte |= ((c & 1) << 5) | ((c & 2))
            else:
                byte |= ((c & 1) << 4) | ((c & 2) >> 1)
        data.append(byte)
        x += 4
    return bytes(data)


def _encode_16color_row(row, width):
    """MSX Screen 5: 2 pixels per byte, high nibble = left pixel."""
    data = []
    x = 0
    while x < width:
        left = row[x] if x < width else 0
        right = row[x + 1] if x + 1 < width else 0
        data.append((left << 4) | (right & 0x0F))
        x += 2
    return bytes(data)


# -----------------------------------------------------------------------
# ZX0 compression (SymbOS inverted variant)
# -----------------------------------------------------------------------

# Path to the zx0tool binary (next to this script)
_ZX0_TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'zx0tool')

# Clean PATH so the system assembler/linker is used, not scc Z80 tools
_CLEAN_ENV = dict(os.environ)
_CLEAN_ENV['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + os.environ.get('PATH', '')


def _zx0_compress(data):
    """Compress bytes using ZX0 inverted format (SymbOS Banking_Decompress compatible)."""
    result = subprocess.run(
        [_ZX0_TOOL],
        input=bytes(data),
        capture_output=True,
        env=_CLEAN_ENV,
    )
    if result.returncode != 0:
        raise RuntimeError(f"zx0tool failed: {result.stderr.decode()}")
    return result.stdout


def _symsbos_zx0_payload(uncompressed):
    """
    Build the SymbOS ZX0 payload for a chunk:
      [last 4 bytes of uncompressed] [0x00 0x00] [ZX0 stream of rest]
    Returns the payload bytes.
    """
    data = bytes(uncompressed)
    if len(data) < 4:
        # Pad to 4 bytes so we can always take the last-4 tail
        data = data + b'\x00' * (4 - len(data))
    last4 = data[-4:]
    rest = data[:-4]
    zx0_stream = _zx0_compress(rest) if rest else b''
    return last4 + b'\x00\x00' + zx0_stream


# -----------------------------------------------------------------------
# SGX chunk building
# -----------------------------------------------------------------------

# Each uncompressed chunk payload must fit in one 16K SymbOS memory bank.
_MAX_CHUNK_BYTES = 16384

# 4-colour simple chunks: SymbOS wallpaper loader expects 160px-wide chunks (row_bytes=40),
# matching the CPC screen bank layout. Format allows up to 252px but wallpaper setter rejects it.
_MAX_4COLOR_CHUNK_PX = 160


def _build_pixel_data(chunk_pixels, chunk_w, height, num_colors):
    """Return raw (uncompressed) pixel bytes for one chunk."""
    encode_row = _encode_4color_row if num_colors == 4 else _encode_16color_row
    data = bytearray()
    for row in chunk_pixels:
        data += encode_row(row, chunk_w)
    return bytes(data)


def _write_chunk(buf, chunk_pixels, chunk_w, height, num_colors, compress=True):
    """Append one chunk (header + payload) to buf."""
    row_bytes = chunk_w // 4 if num_colors == 4 else chunk_w // 2
    raw = _build_pixel_data(chunk_pixels, chunk_w, height, num_colors)

    if num_colors == 4:
        # Simple chunk: row_bytes must be ≤ 63 (6 bits); bit7 = compressed flag
        assert row_bytes <= 63, f"4-colour chunk too wide: {chunk_w}px = {row_bytes} bytes/row"
        if compress:
            payload = _symsbos_zx0_payload(raw)
            buf.append(row_bytes | 0x80)
            buf.append(chunk_w & 0xFF)
            buf.append(height & 0xFF)
            buf.append(len(payload) & 0xFF)
            buf.append((len(payload) >> 8) & 0xFF)
            buf += payload
        else:
            buf.append(row_bytes)       # bit7 = 0: uncompressed
            buf.append(chunk_w & 0xFF)
            buf.append(height & 0xFF)
            buf += raw
    else:
        # Extended chunk
        if compress:
            payload = _symsbos_zx0_payload(raw)
            buf.append(0xC0)            # 0x40 marker | 0x80 compressed
            buf.append(0x05)            # type = 16-colour
            buf.append(row_bytes & 0xFF)
            buf.append((row_bytes >> 8) & 0xFF)
            buf.append(chunk_w & 0xFF)
            buf.append((chunk_w >> 8) & 0xFF)
            buf.append(height & 0xFF)
            buf.append((height >> 8) & 0xFF)
            buf.append(len(payload) & 0xFF)
            buf.append((len(payload) >> 8) & 0xFF)
            buf += payload
        else:
            buf.append(0x40)            # 0x40 marker, bit7 = 0: uncompressed
            buf.append(0x05)            # type = 16-colour
            buf.append(row_bytes & 0xFF)
            buf.append((row_bytes >> 8) & 0xFF)
            buf.append(chunk_w & 0xFF)
            buf.append((chunk_w >> 8) & 0xFF)
            buf.append(height & 0xFF)
            buf.append((height >> 8) & 0xFF)
            buf += raw


def build_sgx(pixels, width, height, num_colors, compress=True):
    """Return SGX file content as bytes."""
    buf = bytearray()

    if num_colors == 4:
        # 4-colour: simple chunks only, max 252 px wide
        max_chunk_px = _MAX_4COLOR_CHUNK_PX
    else:
        # 16-colour: split so uncompressed payload ≤ 16K
        px_per_byte = 2
        max_row_bytes = _MAX_CHUNK_BYTES // height
        max_chunk_px = (max_row_bytes * px_per_byte) & ~3
        if max_chunk_px < 4:
            max_chunk_px = 4

    x = 0
    while x < width:
        chunk_w = min(max_chunk_px, width - x)
        chunk_w = chunk_w & ~3
        if chunk_w == 0:
            chunk_w = 4
        chunk_pixels = [row[x:x + chunk_w] for row in pixels]
        _write_chunk(buf, chunk_pixels, chunk_w, height, num_colors, compress)
        x += chunk_w

    buf += b'\x00\x00\x00'
    return bytes(buf)


# -----------------------------------------------------------------------
# Preview
# -----------------------------------------------------------------------

def save_preview(pixels, width, height, path):
    img = Image.new('RGB', (width, height))
    flat = []
    for row in pixels:
        for idx in row:
            flat.append(PALETTE[idx])
    img.putdata(flat)
    img.save(path)


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------

DITHERS = {
    'none':            quantize_none,
    'floyd-steinberg': quantize_floyd_steinberg,
    'atkinson':        quantize_atkinson,
    'ordered':         quantize_ordered,
}


def parse_fit(s):
    parts = s.lower().split('x')
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("format must be WxH, e.g. 320x200")
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        raise argparse.ArgumentTypeError("format must be WxH, e.g. 320x200")


def main():
    p = argparse.ArgumentParser(
        description='Convert PNG/JPG images to SymbOS SGX format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  conv2sgx.py photo.png                         # 16-colour, Floyd-Steinberg, no scaling
  conv2sgx.py photo.png -c 4 -d atkinson        # 4-colour with Atkinson dither
  conv2sgx.py photo.png --fit 320x200            # scale to fit 320x200, keep aspect ratio
  conv2sgx.py photo.png -W 128 -H 64 --no-aspect # stretch to exactly 128x64
  conv2sgx.py photo.png -s 0.5 -d ordered        # half size, Bayer ordered dither
  conv2sgx.py photo.png --preview                 # also save a PNG preview
  conv2sgx.py photo.png --amstrad                 # Amstrad CPC preset: 320x200, 4-colour
  conv2sgx.py photo.png --msx                     # MSX preset: 512x212, 16-colour
""")

    p.add_argument('input', help='Input image (.png or .jpg)')
    p.add_argument('-o', '--output', metavar='FILE',
                   help='Output SGX file (default: <input>.sgx)')
    p.add_argument('-c', '--colors', type=int, choices=[4, 16], default=16,
                   help='Colour depth: 4 or 16 (default: 16)')
    p.add_argument('-d', '--dither',
                   choices=list(DITHERS.keys()), default='floyd-steinberg',
                   help='Dithering algorithm (default: floyd-steinberg)')
    p.add_argument('-W', '--width', type=int, metavar='PX',
                   help='Target width in pixels')
    p.add_argument('-H', '--height', type=int, metavar='PX',
                   help='Target height in pixels')
    p.add_argument('-s', '--scale', type=float, metavar='FACTOR',
                   help='Uniform scale factor (e.g. 0.5 for half size)')
    p.add_argument('--fit', type=parse_fit, metavar='WxH',
                   help='Fit within WxH preserving aspect ratio (e.g. 320x200)')
    p.add_argument('--no-aspect', action='store_true',
                   help='Stretch to exact size instead of preserving aspect ratio')
    p.add_argument('--preview', action='store_true',
                   help='Save a PNG preview alongside the SGX file')
    p.add_argument('--no-compress', action='store_true',
                   help='Write raw uncompressed SGX (no ZX0; matches official FantasyKeithParkinson format)')

    machine = p.add_mutually_exclusive_group()
    machine.add_argument('--amstrad', action='store_true',
                         help='Amstrad CPC preset: 320x200, 4-colour; auto-names output A{name}{dither}{L|H}.SGX')
    machine.add_argument('--msx', action='store_true',
                         help='MSX preset: 512x212, 16-colour; auto-names output M{name}{dither}{L|H}.SGX')

    args = p.parse_args()

    # Apply machine presets (only if the user hasn't explicitly set those options)
    if args.amstrad:
        if not args.width:
            args.width = 320
        if not args.height:
            args.height = 200
        if args.colors == 16:   # still at default — override
            args.colors = 4
        args.no_aspect = True
    elif args.msx:
        if not args.width:
            args.width = 512
        if not args.height:
            args.height = 212
        args.no_aspect = True

    if not args.no_compress and not os.path.exists(_ZX0_TOOL):
        sys.exit(f"ZX0 compressor not found: {_ZX0_TOOL}\n"
                 f"Build it with: cd {os.path.dirname(_ZX0_TOOL)} && make zx0tool")

    if args.output:
        outfile = args.output
    elif args.amstrad or args.msx:
        # Short filename scheme for machines with no long filename support:
        # {A|M}{3-letter-name}{dither-initial}{L|H}.SGX
        prefix = 'A' if args.amstrad else 'M'
        stem = os.path.splitext(os.path.basename(args.input))[0]
        name3 = stem[:3]
        dither_initial = {'floyd-steinberg': 'F', 'atkinson': 'A',
                          'ordered': 'O', 'none': 'N'}[args.dither]
        # Determine resolution tag after scaling is applied — use requested dims for now;
        # will be refined below once tw/th are known. Placeholder, overwritten later.
        outfile = None   # resolved after scaling
    else:
        base = os.path.splitext(args.input)[0]
        outfile = base + '.sgx'

    try:
        img = Image.open(args.input).convert('RGB')
    except Exception as e:
        sys.exit(f"Cannot load image: {e}")

    orig_w, orig_h = img.size
    print(f"Input : {args.input}  ({orig_w} x {orig_h})")

    tw, th = orig_w, orig_h

    if args.fit:
        fw, fh = args.fit
        ratio = min(fw / orig_w, fh / orig_h)
        tw = int(orig_w * ratio)
        th = int(orig_h * ratio)
    elif args.scale is not None:
        tw = int(orig_w * args.scale)
        th = int(orig_h * args.scale)
    elif args.width or args.height:
        if args.width and args.height:
            if args.no_aspect:
                tw, th = args.width, args.height
            else:
                ratio = min(args.width / orig_w, args.height / orig_h)
                tw = int(orig_w * ratio)
                th = int(orig_h * ratio)
        elif args.width:
            tw = args.width
            th = int(orig_h * args.width / orig_w) if not args.no_aspect else orig_h
        else:
            th = args.height
            tw = int(orig_w * args.height / orig_h) if not args.no_aspect else orig_w

    # Width multiple of 4; max 255 rows; max width depends on mode
    tw = max(4, (tw + 3) & ~3)
    th = max(1, min(255, th))

    # For 4-colour, total width can exceed 252 (it'll be split into chunks).
    # For 16-colour, extended chunks support large widths.
    if args.colors == 4:
        tw = min(tw, 1020)   # arbitrary max (4 × 255 chunks of 252px each)
    else:
        tw = min(tw, 1020)

    if (tw, th) != (orig_w, orig_h):
        img = img.resize((tw, th), Image.LANCZOS)
        print(f"Scaled: {tw} x {th}")
    else:
        print(f"Size  : {tw} x {th}  (no scaling)")

    # Resolve auto-generated filename now that final dimensions are known
    if outfile is None:
        prefix = 'A' if args.amstrad else 'M'
        stem = os.path.splitext(os.path.basename(args.input))[0]
        name3 = stem[:3]
        dither_initial = {'floyd-steinberg': 'F', 'atkinson': 'A',
                          'ordered': 'O', 'none': 'N'}[args.dither]
        res_tag = 'L' if (tw == 320 and th == 200) else 'H'
        outfile = f"{prefix}{name3}{dither_initial}{res_tag}.SGX"

    print(f"Colors: {args.colors}   Dither: {args.dither}")

    pix = img.load()
    rgb_rows = [[(pix[x, y][0], pix[x, y][1], pix[x, y][2])
                 for x in range(tw)]
                for y in range(th)]

    quantize_fn = DITHERS[args.dither]
    pixels = quantize_fn(rgb_rows, tw, th, args.colors)

    if not args.no_compress:
        print("Compressing...")
    sgx_data = build_sgx(pixels, tw, th, args.colors, compress=not args.no_compress)

    try:
        with open(outfile, 'wb') as f:
            f.write(sgx_data)
        print(f"Output: {outfile}  ({len(sgx_data)} bytes)")
    except Exception as e:
        sys.exit(f"Cannot write output: {e}")

    if args.preview:
        prev_path = os.path.splitext(outfile)[0] + '_preview.png'
        save_preview(pixels, tw, th, prev_path)
        print(f"Preview: {prev_path}")


if __name__ == '__main__':
    main()
