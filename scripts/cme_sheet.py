# -*- coding: utf-8 -*-
"""生成讲义缩略图总览（带页码标签的网格图）。

用法: python cme_sheet.py <slides_dir> <out_prefix> [cols] [rows] [cell_w]
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

d = Path(sys.argv[1])
prefix = Path(sys.argv[2])
cols = int(sys.argv[3]) if len(sys.argv) > 3 else 3
rows = int(sys.argv[4]) if len(sys.argv) > 4 else 4
cell_w = int(sys.argv[5]) if len(sys.argv) > 5 else 640

files = sorted([p for p in d.iterdir() if p.suffix.upper() in (".JPG", ".JPEG", ".PNG")],
               key=lambda p: int(p.stem) if p.stem.isdigit() else 0)
print("slides:", len(files))

per = cols * rows
cell_h = int(cell_w * 0.72)
label_h = 34
sheets = []
for si in range(0, len(files), per):
    chunk = files[si:si + per]
    W = cols * cell_w
    H = rows * (cell_h + label_h)
    sheet = Image.new("RGB", (W, H), (255, 255, 255))
    dr = ImageDraw.Draw(sheet)
    for i, f in enumerate(chunk):
        r, c = divmod(i, cols)
        x = c * cell_w
        y = r * (cell_h + label_h)
        try:
            im = Image.open(f).convert("RGB")
            im.thumbnail((cell_w - 8, cell_h - 4))
            sheet.paste(im, (x + 4, y + label_h + 2))
        except Exception as e:
            dr.text((x + 8, y + label_h + 8), "ERR %r" % e, fill=(200, 0, 0))
        dr.rectangle([x, y, x + cell_w - 1, y + label_h - 1], fill=(30, 60, 120))
        dr.text((x + 8, y + 8), "PAGE %s" % f.stem, fill=(255, 255, 255))
    out = Path("%s_%02d.jpg" % (prefix, si // per + 1))
    sheet.save(out, quality=88)
    print("saved", out, sheet.size)
