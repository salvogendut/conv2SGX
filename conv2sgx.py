#!/usr/bin/env python3
"""
conv2sgx.py - Convert PNG/JPG images to SymbOS SGX format

SGX format (derived from gfx2sgx.c by Prodatron/SymbiosiS):

  4-colour header (3 bytes):
    byte 0: width / 4      (CPC Mode 1: 4 pixels per byte)
    byte 1: width in px
    byte 2: height in px
  16-colour header (10 bytes):
    byte 0: width / 2      (MSX Screen 5: 2 pixels per byte)
    byte 1: width in px
    byte 2: height in px
    bytes 3-6: 0x00 0x00 0x00 0x00
    bytes 7-8: data size (little-endian word)
    byte 9: 0x05           (encoding: 16-colour MSX)

Width must be a multiple of 4. Max size: 252 x 255.
"""

import argparse
import os
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required: pip install Pillow")

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False

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

# Pre-compute palette as flat list for quick indexing
_PR = [c[0] for c in PALETTE]
_PG = [c[1] for c in PALETTE]
_PB = [c[2] for c in PALETTE]


# -----------------------------------------------------------------------
# Colour matching
# -----------------------------------------------------------------------

def _nearest(r, g, b, n):
    """Nearest palette index (Euclidean RGB distance, same as gfx2sgx.c)."""
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
# Dithering algorithms  (all return a 2-D list[y][x] of palette indices)
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
    # Work on a mutable float copy
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
    # Atkinson: spread 6/8 of error to 6 neighbours (1/8 each, 2/8 lost)
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


# 4x4 Bayer matrix, values 0-15
_BAYER4 = [
    [ 0,  8,  2, 10],
    [12,  4, 14,  6],
    [ 3, 11,  1,  9],
    [15,  7, 13,  5],
]


def quantize_ordered(rgb_rows, width, height, n):
    out = [[0] * width for _ in range(height)]
    scale = 24  # dither intensity (tunable)
    for y in range(height):
        for x in range(width):
            offset = (_BAYER4[y & 3][x & 3] / 15.0 - 0.5) * scale
            rv = _clamp(rgb_rows[y][x][0] + offset)
            gv = _clamp(rgb_rows[y][x][1] + offset)
            bv = _clamp(rgb_rows[y][x][2] + offset)
            out[y][x] = _nearest(rv, gv, bv, n)
    return out


# -----------------------------------------------------------------------
# SGX encoding
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


def build_sgx(pixels, width, height, num_colors):
    """Return SGX file content as bytes."""
    buf = bytearray()
    if num_colors == 4:
        buf.append(width // 4)
        buf.append(width)
        buf.append(height)
        for row in pixels:
            buf += _encode_4color_row(row, width)
    else:
        row_bytes = width // 2
        data_size = row_bytes * height
        buf.append(row_bytes)
        buf.append(width)
        buf.append(height)
        buf += b'\x00\x00\x00\x00'
        buf.append(data_size & 0xFF)
        buf.append(data_size >> 8)
        buf.append(0x05)
        for row in pixels:
            buf += _encode_16color_row(row, width)
    return bytes(buf)


# -----------------------------------------------------------------------
# Preview (write a PNG showing the converted result)
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

    args = p.parse_args()

    # Output filename
    if args.output:
        outfile = args.output
    else:
        base = os.path.splitext(args.input)[0]
        outfile = base + '.sgx'

    # Load image
    try:
        img = Image.open(args.input).convert('RGB')
    except Exception as e:
        sys.exit(f"Cannot load image: {e}")

    orig_w, orig_h = img.size
    print(f"Input : {args.input}  ({orig_w} x {orig_h})")

    # ---- Compute target size ----
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

    # Enforce width multiple of 4, clamp to SGX limits
    tw = max(4, min(252, (tw + 3) & ~3))
    th = max(1, min(255, th))

    if (tw, th) != (orig_w, orig_h):
        img = img.resize((tw, th), Image.LANCZOS)
        print(f"Scaled: {tw} x {th}")
    else:
        print(f"Size  : {tw} x {th}  (no scaling)")

    # ---- Quantize ----
    print(f"Colors: {args.colors}   Dither: {args.dither}")

    # Build rgb_rows: list of rows, each row a list of (r,g,b) tuples
    pix = img.load()
    rgb_rows = [[(pix[x, y][0], pix[x, y][1], pix[x, y][2])
                 for x in range(tw)]
                for y in range(th)]

    quantize_fn = DITHERS[args.dither]
    pixels = quantize_fn(rgb_rows, tw, th, args.colors)

    # ---- Encode SGX ----
    sgx_data = build_sgx(pixels, tw, th, args.colors)

    try:
        with open(outfile, 'wb') as f:
            f.write(sgx_data)
        print(f"Output: {outfile}  ({len(sgx_data)} bytes)")
    except Exception as e:
        sys.exit(f"Cannot write output: {e}")

    # ---- Optional preview ----
    if args.preview:
        prev_path = os.path.splitext(outfile)[0] + '_preview.png'
        save_preview(pixels, tw, th, prev_path)
        print(f"Preview: {prev_path}")


if __name__ == '__main__':
    main()
