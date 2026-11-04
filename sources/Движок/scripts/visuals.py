"""Shared northern Freelearn components for still frames and moving footage."""
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps


def key_for(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def geometry(width, height):
    # Even coordinates keep the preview crop and YUV video layout in agreement.
    even = lambda value: round(value / 2) * 2
    x, y = even(width * .05), even(height * .06)
    right, bottom = width - x, even(height * .667)
    return {"media": (x, y, right, bottom),
            "widget": (x, even(height * .698), right, even(height * .913)),
            "radius": max(10, round(height * .0185))}


def font_at(path, size, weight=450):
    font = ImageFont.truetype(str(path), round(size))
    try:
        axes = font.get_variation_axes()
        values = [max(a['minimum'], min(a['maximum'], weight))
                  if a['name'] == b'Weight' else a['default'] for a in axes]
        font.set_variation_by_axes(values)
    except OSError:
        pass  # A static OFL font can also be used.
    return font


def wrapped(draw, text, font, width):
    lines, current = [], ''
    for word in text.split():
        if draw.textlength(word, font=font) > width:
            raise RuntimeError('Слово не помещается в шаблон; сократите текст')
        trial = f'{current} {word}'.strip()
        if current and draw.textlength(trial, font=font) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def text_block(draw, text, font, box, fill, max_lines, centered=False):
    x, y, right, bottom = box
    lines = wrapped(draw, text, font, right - x)
    line_height = round(font.size * 1.25)
    if len(lines) > max_lines or len(lines) * line_height > bottom - y:
        raise RuntimeError('Текст не помещается в шаблон; сократите текст')
    for line in lines:
        dx = x + (right - x - draw.textlength(line, font=font)) / 2 if centered else x
        draw.text((dx, y), line, font=font, fill=fill, anchor='lt')
        y += line_height
    return y


def brand(canvas, x, y, size, colors, font_path, word_size):
    """Same mountain geometry as the site, antialiased even in the small footer."""
    factor = 4
    tile_size = round(size * factor)
    tile = Image.new('RGBA', (tile_size, tile_size))
    td = ImageDraw.Draw(tile)
    td.rounded_rectangle((0, 0, tile_size - 1, tile_size - 1),
                         radius=tile_size * 9 / 32, fill=colors['accent'])
    scale, inset = tile_size * 21 / 32 / 32, tile_size * 5.5 / 32
    points = [(4, 23), (12, 10), (17.2, 18), (20.3, 13.2), (28, 23), (4, 23)]
    points = [(inset + px * scale, inset + py * scale) for px, py in points]
    stroke = max(1, round(scale * 1.9))
    td.line(points, fill=colors['accent_ink'], width=stroke, joint='curve')
    td.line((inset + 7 * scale, inset + 23 * scale,
             inset + 25 * scale, inset + 23 * scale), fill=colors['accent_ink'], width=stroke)
    tile = tile.resize((round(size), round(size)), Image.Resampling.LANCZOS)
    canvas.paste(tile, (round(x), round(y)), tile)
    draw = ImageDraw.Draw(canvas)
    font = font_at(font_path, word_size, 700)
    tx = x + size + size * 10 / 32
    draw.text((tx, y + (size - font.size) / 2), 'Freelearn', font=font,
              fill=colors['ink'], anchor='lt')


def ridges(draw, box, colors):
    x, y, right, bottom = box
    width, height = right - x, (bottom - y) * .23
    far = [(0, .62), (.07, .48), (.15, .57), (.23, .24), (.30, .41),
           (.38, .16), (.47, .44), (.56, .34), (.65, .58), (.75, .22),
           (.83, .43), (.92, .33), (1, .50)]
    near = [(0, .83), (.08, .64), (.14, .74), (.23, .42), (.30, .64),
            (.36, .53), (.44, .25), (.51, .61), (.60, .51), (.68, .73),
            (.77, .38), (.84, .58), (.92, .54), (1, .79)]
    for points, color in [(far, colors['ridge_far']), (near, colors['background_deep'])]:
        poly = [(x + a * width, bottom - height + b * height) for a, b in points]
        draw.polygon([(x, bottom), *poly, (right, bottom)], fill=color)


def make_slide(scene, fmt, cache, style, root, assets, run, binary):
    width, height = style['canvas'][fmt]
    colors, font_path = style['colors'], root / style['font']
    layout = geometry(width, height)
    mx, my, mr, mb = layout['media']
    wx, wy, wr, wb = layout['widget']
    mw, mh = mr - mx, mb - my
    media_id = scene.get('video_asset_id') or scene.get('asset_id')
    record = assets.get(media_id)
    source = None
    if record:
        media_path = root / record['file']
        if not media_path.is_file():
            raise RuntimeError(f'Не найден ресурс: {media_path}')
        with media_path.open('rb') as stream:content_hash=hashlib.file_digest(stream,'sha256').hexdigest()
        source = {'path': str(media_path), 'sha256': content_hash, 'preferred_crop': record.get('preferred_crop')}
    visual = {k: v for k, v in scene.items() if k != 'narration' and not k.startswith('_')}
    key = key_for({'renderer': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'scene': visual, 'format': fmt,
                   'style': style, 'font_sha256': hashlib.sha256(font_path.read_bytes()).hexdigest(), 'source': source})
    path = cache / f'slide-{key}.png'
    if path.is_file():
        return path
    im = Image.new('RGB', (width, height), colors['background'])
    draw = ImageDraw.Draw(im)
    kind = scene['kind']
    portrait = fmt == '9:16'
    if kind == 'nature':
        if not record:
            raise RuntimeError(f'Неизвестный asset_id: {media_id}')
        if record.get('media_type') == 'video':
            poster_time=float(scene.get('video_offset_seconds',0))
            poster = cache / f"poster-{key_for({'source':source,'time':poster_time})}.jpg"
            if not poster.is_file():
                run([binary('ffmpeg'), '-y', '-ss', str(poster_time), '-i', media_path,
                     '-frames:v', '1', '-q:v', '2', poster])
            if not poster.is_file() or not poster.stat().st_size:raise RuntimeError('Не удалось извлечь постер из выбранного диапазона видео')
            media_path = poster
        image = Image.open(media_path).convert('RGB')
        crop = scene.get('image_crop', record.get('preferred_crop')) if record.get('media_type') != 'video' else None
        if crop is not None:
            if not isinstance(crop, (list,tuple)) or len(crop)!=4:
                raise RuntimeError('image_crop: нужны четыре доли [left, top, right, bottom]')
            left,top,right,bottom=map(float,crop)
            if not (0<=left<right<=1 and 0<=top<bottom<=1):
                raise RuntimeError('image_crop выходит за границы фотографии')
            image=image.crop((round(left*image.width),round(top*image.height),round(right*image.width),round(bottom*image.height)))
        image = ImageOps.fit(image, (mw, mh), method=Image.Resampling.LANCZOS)
        image = ImageEnhance.Color(image).enhance(.78)
        image = ImageEnhance.Brightness(image).enhance(1.0 if style['theme'] == 'light' else .94)
        mask = Image.new('L', (mw, mh))
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, mw - 1, mh - 1), radius=layout['radius'], fill=255)
        im.paste(image, (mx, my), mask)
    elif kind in ('intro', 'outro'):
        ridges(draw, layout['media'], colors)
        size = round(width * (.065 if not portrait else .09))
        word = round(width * (.059 if not portrait else .07))
        word_width = draw.textlength('Freelearn', font=font_at(font_path, word, 700))
        total_width = size * 1.3125 + word_width
        brand(im, (width - total_width) / 2, my + mh * .29, size, colors, font_path, word)
        body = font_at(font_path, width * (.023 if not portrait else .035))
        text_block(draw, 'Учитесь в своём темпе', body,
                   (mx, my + mh * .52, mr, my + mh * .72), colors['muted'], 2, True)
    elif kind == 'card':
        draw.rounded_rectangle(layout['media'], radius=layout['radius'], fill=colors['raised'])
        inset = round(width * .045)
        label = font_at(font_path, width * (.015 if not portrait else .025), 650)
        draw.text((mx + inset, my + mh * .11), 'УЧИМСЯ ПО ШАГАМ', font=label,
                  fill=colors['subtle'], anchor='lt')
        heading = font_at(font_path, width * (.043 if not portrait else .053), 680)
        text_block(draw, scene.get('title', ''), heading,
                   (mx + inset, my + mh * .26, mr - inset, my + mh * .58), colors['ink'], 2)
        points = scene.get('points', [])
        if not isinstance(points, list) or len(points) > 3 or any(not isinstance(p, str) for p in points):
            raise RuntimeError('points: нужен список не более трёх коротких строк')
        point_font = font_at(font_path, width * (.020 if not portrait else .031), 500)
        for index, text in enumerate(points):
            py = my + mh * (.61 + index * .11)
            tile = point_font.size * 1.35
            draw.rounded_rectangle((mx + inset, py, mx + inset + tile, py + tile),
                                   radius=tile * .25, fill=colors['accent_soft'])
            draw.text((mx + inset + tile / 2, py + tile / 2), str(index + 1),
                      font=point_font, fill=colors['accent_soft_ink'], anchor='mm')
            text_block(draw, text, point_font, (mx + inset + tile * 1.6, py, mr - inset, py + tile),
                       colors['muted'], 1)
    else:
        raise RuntimeError(f'Неизвестный вид сцены: {kind}')

    # Prompt widget is below the media; footer logo is outside both components.
    draw.rounded_rectangle(layout['widget'], radius=round(height * .013),
                           fill=colors['card'], outline=colors['line'], width=max(1, round(width / 960)))
    inset = round(width * .025)
    wh = wb - wy
    title_font = font_at(font_path, width * (.017 if not portrait else .027), 600)
    title = scene.get('title', '')
    text_block(draw, title, title_font, (wx + inset, wy + wh * .13, wr - inset, wy + wh * .33),
               colors['muted'], 1)
    caption_font = font_at(font_path, width * (.023 if not portrait else .035), 500)
    text_block(draw, scene.get('caption', ''), caption_font,
               (wx + inset, wy + wh * .38, wr - inset, wb - wh * .10), colors['ink'],
               2 if not portrait else 3)
    footer_size = round(min(52, height * .034))
    footer_word = round(width * (.017 if not portrait else .028))
    brand(im, mx, height * .955 - footer_size / 2, footer_size, colors, font_path, footer_word)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


def make_media_overlay(frame, fmt, cache, style):
    """Opaque widget/footer with a rounded transparent window for actual video."""
    path = cache / f'overlay-{frame.stem}.png'
    if not path.is_file():
        image = Image.open(frame).convert('RGBA')
        layout = geometry(*style['canvas'][fmt])
        alpha = Image.new('L', image.size, 255)
        ImageDraw.Draw(alpha).rounded_rectangle(layout['media'], radius=layout['radius'], fill=0)
        image.putalpha(alpha)
        image.save(path)
    return path
