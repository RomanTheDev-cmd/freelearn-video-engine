#!/usr/bin/env python3
"""Render shared components in both themes/formats without voice synthesis."""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.dont_write_bytecode = True

import build_video as renderer
from visuals import font_at


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache = output / '.freelearn-cache'
    cache.mkdir(exist_ok=True)
    root = renderer.ROOT
    meditation = json.loads((root / 'assets/examples/meditation-preview.json').read_text())
    lesson = json.loads((root / 'assets/examples/lesson.json').read_text())
    scenes = [dict(meditation['scenes'][0], caption='Устройтесь удобно'),
              meditation['scenes'][1], lesson['scenes'][1], meditation['scenes'][-1]]
    font = font_at(root / renderer.STYLE['font'], 20, 600)
    for fmt in ['16:9', '9:16']:
        tw, th = (480, 270) if fmt == '16:9' else (270, 480)
        sheet = Image.new('RGB', (tw * 4 + 40, (th + 40) * 2 + 10), '#e9eff1')
        draw = ImageDraw.Draw(sheet)
        for row, theme in enumerate(['light', 'dark']):
            renderer.STYLE['theme'] = theme
            renderer.STYLE['colors'] = dict(renderer.STYLE['themes'][theme])
            draw.text((10, row * (th + 40) + 6),
                      'Светлая тема' if theme == 'light' else 'Тёмная тема', font=font, fill='#1b272e')
            for col, scene in enumerate(scenes):
                frame = renderer.make_slide(scene, fmt, cache)
                image = Image.open(frame).convert('RGB')
                image.save(output / f'{theme}-{fmt.replace(":", "x")}-{scene["kind"]}.png')
                sheet.paste(image.resize((tw, th), Image.Resampling.LANCZOS),
                            (10 + col * tw, row * (th + 40) + 34))
        sheet.save(output / f'components-{fmt.replace(":", "x")}.png')
    print(f'16 кадров и 2 обзора компонентов: {output}')


if __name__ == '__main__':
    main()
