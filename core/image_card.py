"""本地 Pillow 卡片渲染：生成 PNG 文件，供 AstrBot 以图片消息发送。"""

from __future__ import annotations

import time
from functools import cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .models import Game
from .profiles import OPERATOR_PROFILE, GameProfile

SCALE = 2
WIDTH = 860
PADDING = 32
HEADER_H = 122
LABEL_H = 26
ROW_H = 72
GAP = 8
STATUS_H = 52
LEGEND_H = 30

BG_TOP = (11, 18, 32)
BG_BOTTOM = (16, 27, 45)
TEXT = (229, 231, 235)
MUTED = (148, 163, 184)
FAINT = (100, 116, 139)
ACCENT = (245, 158, 11)
BORDER = (148, 163, 184, 46)

GREEN_BG = (16, 74, 52, 255)
GREEN_BORDER = (34, 197, 94, 255)
GREEN_TEXT = (187, 247, 208)
YELLOW_BG = (74, 58, 10, 255)
YELLOW_BORDER = (234, 179, 8, 255)
YELLOW_TEXT = (253, 224, 71)
BLUE_BG = (16, 52, 92, 255)
BLUE_BORDER = (59, 130, 246, 255)
BLUE_TEXT = (191, 219, 254)
WRONG_BG = (70, 24, 28, 255)
WRONG_BORDER = (239, 68, 68, 255)
WRONG_TEXT = (254, 202, 202)

_FONT_CANDIDATES = {
    False: (
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ),
    True: (
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ),
}


@cache
def _font(size: int, bold: bool = False):
    for candidate in _FONT_CANDIDATES[bold]:
        path = Path(candidate)
        if not path.exists():
            continue
        try:
            return ImageFont.truetype(str(path), size * SCALE)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size * SCALE)
    except TypeError:  # Pillow < 10
        return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _line_height(font) -> int:
    return int(getattr(font, "size", 14) * 1.35)


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: float) -> str:
    if _text_width(draw, text, font) <= max_width:
        return text
    ellipsis = "…"
    while text and _text_width(draw, text + ellipsis, font) > max_width:
        text = text[:-1]
    return text + ellipsis


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    max_width: float,
    max_lines: int,
) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        if _text_width(draw, current + char, font) <= max_width:
            current += char
            continue
        lines.append(current)
        current = char
        if len(lines) >= max_lines:
            break
    if len(lines) < max_lines:
        if current:
            lines.append(current)
        return lines

    last = lines[-1]
    while last and _text_width(draw, last + "…", font) > max_width:
        last = last[:-1]
    lines[-1] = last + "…"
    return lines


def _draw_lines_centered(
    draw: ImageDraw.ImageDraw,
    center_x: float,
    top: float,
    lines: list[str],
    font,
    fill,
    line_gap: int = 2,
) -> float:
    line_h = _line_height(font)
    y = top
    for line in lines:
        draw.text((center_x, y), line, font=font, fill=fill, anchor="ma")
        y += line_h + line_gap * SCALE
    return y


def _tone(state: str) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int], tuple[int, int, int]]:
    if state == "correct":
        return GREEN_BG, GREEN_BORDER, GREEN_TEXT
    if state == "close":
        return YELLOW_BG, YELLOW_BORDER, YELLOW_TEXT
    if state in ("higher", "lower"):
        return BLUE_BG, BLUE_BORDER, BLUE_TEXT
    return WRONG_BG, WRONG_BORDER, WRONG_TEXT


def _mark(state: str) -> str:
    if state == "correct":
        return "√"
    if state == "close":
        return "~"
    if state == "wrong":
        return "×"
    return ""


def _arrow(state: str) -> str:
    if state == "higher":
        return "↑"
    if state == "lower":
        return "↓"
    return ""


def _draw_cell(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    text: str,
    state: str,
    sub: str = "",
) -> None:
    x0, y0, x1, y1 = box
    background, border, color = _tone(state)
    draw.rounded_rectangle(
        box,
        radius=12 * SCALE,
        fill=background,
        outline=border,
        width=2 * SCALE,
    )

    value_font = _font(14, bold=True)
    sub_font = _font(10)
    mark = _mark(state)
    display = f"{mark} {text} {_arrow(state)}".strip()
    inner_w = (x1 - x0) - 12 * SCALE
    value_lines = _wrap_text(draw, display, value_font, inner_w, 2)
    sub_lines = _wrap_text(draw, sub, sub_font, inner_w, 1) if sub else []

    line_h = _line_height(value_font)
    sub_block = (len(sub_lines) * _line_height(sub_font) + 3 * SCALE) if sub_lines else 0
    total = len(value_lines) * line_h + sub_block
    center_x = (x0 + x1) / 2
    y = y0 + (y1 - y0 - total) / 2

    _draw_lines_centered(draw, center_x, y, value_lines, value_font, color)
    if sub_lines:
        sub_top = y + len(value_lines) * (line_h + 2 * SCALE) + 1 * SCALE
        _draw_lines_centered(draw, center_x, sub_top, sub_lines, sub_font, MUTED)


def _draw_name(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    name: str,
    attempt: int,
) -> None:
    x0, y0, x1, y1 = box
    name_font = _font(17, bold=True)
    attempt_font = _font(10)
    lines = _wrap_text(draw, name, name_font, (x1 - x0) - 12 * SCALE, 2)
    line_h = _line_height(name_font)
    total = len(lines) * line_h + _line_height(attempt_font)
    y = y0 + (y1 - y0 - total) / 2
    _draw_lines_centered(draw, (x0 + x1) / 2, y, lines, name_font, (248, 250, 252))
    draw.text(
        ((x0 + x1) / 2, y + len(lines) * (line_h + 2 * SCALE)),
        f"#{attempt}",
        font=attempt_font,
        fill=FAINT,
        anchor="ma",
    )


def _status(
    game: Game,
    pool,
    profile: GameProfile,
) -> tuple[str, str]:
    answer = pool.by_id.get(game.answer_id)
    if game.status in ("won", "lost"):
        detail = profile.answer_line(answer) if answer else game.answer_id
        prefix = "猜中了！答案是" if game.status == "won" else "次数用尽，答案是"
        return f"{prefix} {detail}", game.status
    if game.max_attempts == -1:
        return f"次数不限 · 艾特机器人并发送{profile.item_label}名继续", "playing"
    remaining = game.max_attempts - len(game.guesses)
    return (
        f"还剩 {remaining} 次机会 · 艾特机器人并发送{profile.item_label}名继续",
        "playing",
    )


def render_board_image(
    game: Game,
    pool,
    output_dir: str | Path,
    profile: GameProfile = OPERATOR_PROFILE,
) -> Path:
    """绘制结果卡片并保存为 PNG，返回文件路径。"""
    rows = len(game.guesses)
    height = (
        PADDING * 2
        + HEADER_H
        + LABEL_H
        + rows * ROW_H
        + max(0, rows - 1) * GAP
        + 18
        + STATUS_H
        + 14
        + LEGEND_H
    )
    canvas_w = WIDTH * SCALE
    canvas_h = height * SCALE

    # 深色渐变 + 两处柔光
    base = Image.new("RGBA", (canvas_w, canvas_h), BG_TOP + (255,))
    gradient = ImageDraw.Draw(base)
    for y in range(canvas_h):
        ratio = y / max(1, canvas_h - 1)
        color = tuple(
            int(BG_TOP[index] + (BG_BOTTOM[index] - BG_TOP[index]) * ratio)
            for index in range(3)
        )
        gradient.line((0, y, canvas_w, y), fill=color + (255,))

    glow = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse(
        (-canvas_w * 0.25, -canvas_h * 0.35, canvas_w * 0.75, canvas_h * 0.35),
        fill=(37, 99, 235, 70),
    )
    glow_draw.ellipse(
        (canvas_w * 0.55, -canvas_h * 0.30, canvas_w * 1.30, canvas_h * 0.30),
        fill=(245, 158, 11, 38),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(110 * SCALE))
    image = Image.alpha_composite(base, glow)
    draw = ImageDraw.Draw(image)

    # 顶部强调线
    draw.rectangle((0, 0, canvas_w, 6 * SCALE), fill=ACCENT)

    x0 = PADDING * SCALE
    right = canvas_w - x0
    content_w = right - x0
    y = PADDING * SCALE

    # 头部
    kicker_font = _font(10)
    title_font = _font(28, bold=True)
    meta_font = _font(11)
    progress_font = _font(22, bold=True)

    draw.text((x0, y), "ARKNIGHTS · GUESS", font=kicker_font, fill=FAINT, anchor="la")
    title_y = y + 18 * SCALE
    title_left = "明日方舟 "
    draw.text((x0, title_y), title_left, font=title_font, fill=TEXT, anchor="la")
    draw.text(
        (x0 + _text_width(draw, title_left, title_font), title_y),
        profile.title,
        font=title_font,
        fill=ACCENT,
        anchor="la",
    )

    draw.text((right, y + 2 * SCALE), game.id, font=meta_font, fill=MUTED, anchor="ra")
    draw.text(
        (right, y + 18 * SCALE),
        f"{len(game.guesses)} / {'∞' if game.max_attempts == -1 else game.max_attempts}",
        font=progress_font,
        fill=TEXT,
        anchor="ra",
    )

    header_bottom = y + HEADER_H * SCALE
    draw.line((x0, header_bottom, right, header_bottom), fill=BORDER, width=1 * SCALE)
    y = header_bottom + 12 * SCALE

    # 列宽：按 profile 权重分配，支持 5 列（干员）与 6 列（敌人）
    cell_gap = GAP * SCALE
    label_count = len(profile.labels)
    name_w = (190 if label_count <= 5 else 168) * SCALE
    available = content_w - name_w - label_count * cell_gap
    unit = available / sum(profile.weights)
    cell_boxes: list[tuple[float, float]] = []
    cursor = x0 + name_w + cell_gap
    for weight in profile.weights:
        width = unit * weight
        cell_boxes.append((cursor, cursor + width))
        cursor += width + cell_gap

    label_font = _font(11)
    for label, (left, cell_right) in zip(profile.labels, cell_boxes, strict=True):
        draw.text(
            ((left + cell_right) / 2, y + 4 * SCALE),
            label,
            font=label_font,
            fill=FAINT,
            anchor="ma",
        )
    y += LABEL_H * SCALE

    # 猜测行
    for record in game.guesses:
        item = pool.by_id.get(record.item_id)
        if item is None:
            continue
        row_y = y
        row_bottom = y + ROW_H * SCALE
        _draw_name(draw, (x0, row_y, x0 + name_w, row_bottom), item.name, record.attempt)

        values = tuple(
            (cell.text, cell.state, cell.sub)
            for cell in profile.cells(item, record.result)
        )
        for (left, cell_right), (text, state, sub) in zip(cell_boxes, values, strict=True):
            _draw_cell(draw, (left, row_y, cell_right, row_bottom), text, state, sub)

        y = row_bottom + GAP * SCALE

    # 状态条
    status_y = y + (18 - GAP) * SCALE
    status_text, status_kind = _status(game, pool, profile)
    if status_kind == "won":
        status_bg, status_border, status_color = GREEN_BG, GREEN_BORDER, (187, 247, 208)
    elif status_kind == "lost":
        status_bg = (69, 26, 30, 255)
        status_border = (239, 68, 68, 255)
        status_color = (254, 202, 202)
    else:
        status_bg = (30, 41, 59, 255)
        status_border = (71, 85, 105, 255)
        status_color = (203, 213, 241)

    status_box = (x0, status_y, right, status_y + STATUS_H * SCALE)
    draw.rounded_rectangle(
        status_box,
        radius=12 * SCALE,
        fill=status_bg,
        outline=status_border,
        width=1 * SCALE,
    )
    status_font = _font(14, bold=True)
    status_text = _fit_text(draw, status_text, status_font, content_w - 32 * SCALE)
    draw.text(
        (x0 + 16 * SCALE, status_y + STATUS_H * SCALE / 2),
        status_text,
        font=status_font,
        fill=status_color,
        anchor="lm",
    )

    # 图例
    legend_y = status_y + STATUS_H * SCALE + 14 * SCALE
    legend_font = _font(10)
    legend_x = x0
    for color, label in (
        (GREEN_BORDER, "√ 完全正确"),
        (YELLOW_BORDER, "~ 部分命中"),
        (BLUE_BORDER, "↑↓ 方向提示"),
        (WRONG_BORDER, "× 错误"),
    ):
        draw.rounded_rectangle(
            (legend_x, legend_y + 2 * SCALE, legend_x + 9 * SCALE, legend_y + 11 * SCALE),
            radius=2 * SCALE,
            fill=color,
        )
        legend_x += 14 * SCALE
        draw.text((legend_x, legend_y), label, font=legend_font, fill=MUTED, anchor="la")
        legend_x += _text_width(draw, label, legend_font) + 18 * SCALE

    arrow_hint = "↑ 答案更高 / 更晚    ↓ 答案更低 / 更早"
    draw.text((right, legend_y), arrow_hint, font=legend_font, fill=FAINT, anchor="ra")

    # 缩小获得抗锯齿效果
    image = image.resize((WIDTH, height), Image.LANCZOS).convert("RGB")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{game.id}_{int(time.time() * 1000)}.png"
    image.save(path, "PNG", optimize=True)
    return path
