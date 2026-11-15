"""Turns the DemoTest frames into docs/demo.gif, each frame with its caption on top.

    cd client && MEDSYNC_DEMO=1 ./gradlew --no-configuration-cache :desktopApp:test --tests '*DemoTest*'
    uv run --with pillow python scripts/demo_gif.py

Needs a CJK font; macOS ships Hiragino Sans GB. Pass another with --font.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FRAMES = ROOT / "client/desktopApp/build/demo"
FONTS = ["/System/Library/Fonts/Hiragino Sans GB.ttc", "/System/Library/Fonts/STHeiti Medium.ttc",
         "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines, line = [], ""
    for ch in text:
        if draw.textlength(line + ch, font=font) > width:
            lines.append(line)
            line = ch
        else:
            line += ch
    return lines + [line] if line else lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", default=next((f for f in FONTS if Path(f).exists()), None))
    parser.add_argument("--width", type=int, default=560)
    parser.add_argument("--out", type=Path, default=ROOT / "docs/demo.gif")
    args = parser.parse_args()
    rows = [line.split("\t", 1) for line in (FRAMES / "captions.tsv").read_text(encoding="utf-8").splitlines() if line]
    font = ImageFont.truetype(args.font, 22)
    frames, durations = [], []
    for i, (name, caption) in enumerate(rows, 1):
        shot = Image.open(FRAMES / name).convert("RGB")
        # Crop the empty bottom of the window, then scale down.
        bbox = Image.eval(shot, lambda v: 255 - v).getbbox() or (0, 0, *shot.size)
        shot = shot.crop((0, 0, shot.width, min(shot.height, bbox[3] + 24)))
        shot = shot.resize((args.width, round(shot.height * args.width / shot.width)), Image.LANCZOS)
        probe = ImageDraw.Draw(shot)
        lines = wrap(probe, f"{i}/{len(rows)}  {caption}", font, args.width - 32)
        band = 20 + 32 * len(lines)
        canvas = Image.new("RGB", (args.width, band + shot.height), (40, 36, 52))
        draw = ImageDraw.Draw(canvas)
        for j, line in enumerate(lines):
            draw.text((16, 12 + 32 * j), line, font=font, fill=(255, 255, 255))
        canvas.paste(shot, (0, band))
        frames.append(canvas)
        durations.append(2500 + 110 * len(caption))  # long enough to read the caption
    height = max(f.height for f in frames)
    frames = [_pad(f, height) for f in frames]
    frames[0].save(args.out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    print(f"{args.out} · {len(frames)} frames · {sum(durations) / 1000:.0f} s · {args.out.stat().st_size / 1e6:.1f} MB")


def _pad(frame: Image.Image, height: int) -> Image.Image:
    if frame.height == height:
        return frame
    canvas = Image.new("RGB", (frame.width, height), (254, 247, 255))
    canvas.paste(frame, (0, 0))
    return canvas


if __name__ == "__main__":
    main()
