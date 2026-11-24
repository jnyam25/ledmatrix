"""Draw text, pictures, and the weather board onto a 16-pixel-tall canvas."""

from __future__ import annotations

import math
from io import BytesIO

from PIL import Image

from app.font import glyph, text_width

PANEL_H = 16
PANEL_W = 96
SIGN_W = PANEL_W * 2

Color = tuple[int, int, int]


def parse_color(value: str, fallback: Color = (214, 255, 74)) -> Color:
    text = (value or "").strip()
    if text.startswith("#") and len(text) == 7:
        try:
            return (int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))
        except ValueError:
            return fallback
    return fallback


def blank(width: int, height: int, color: Color) -> Image.Image:
    return Image.new("RGB", (width, height), color)


def draw_text(
    image: Image.Image,
    text: str,
    x: int,
    y: int,
    color: Color,
    scale: int = 1,
    tracking: int = 1,
) -> int:
    """Paint a single line. Returns the x position after the last glyph."""
    scale = max(1, scale)
    gap = tracking * scale
    pixels = image.load()
    cursor = x
    for char in text:
        rows = glyph(char)
        for row_index, row in enumerate(rows):
            for col_index, bit in enumerate(row):
                if bit != "#":
                    continue
                for sy in range(scale):
                    for sx in range(scale):
                        px = cursor + col_index * scale + sx
                        py = y + row_index * scale + sy
                        if 0 <= px < image.width and 0 <= py < image.height:
                            pixels[px, py] = color
        cursor += 5 * scale + gap
    if text:
        cursor -= gap
    return cursor


def layout_runs(runs: list[tuple[str, Color]], bg: Color, scale: int = 2) -> Image.Image:
    """Paint a message where each run keeps its own color."""
    scale = 2 if scale >= 2 else 1
    pieces = [(part.upper(), color) for part, color in runs if part]
    if not pieces:
        pieces = [(" ", (214, 255, 74))]
    message = "".join(part for part, _color in pieces)
    width = max(1, text_width(message, scale))
    image = blank(width, PANEL_H, bg)
    glyph_h = 7 * scale
    y = max(0, (PANEL_H - glyph_h) // 2)
    x = 0
    for index, (part, color) in enumerate(pieces):
        x = draw_text(image, part, x, y, color, scale=scale)
        if index < len(pieces) - 1:
            x += scale
    return image


def layout_text(text: str, color: Color, bg: Color, scale: int = 2) -> Image.Image:
    message = " ".join(text.upper().split()) or " "
    return layout_runs([(message, color)], bg, scale)


def fit_frames(
    content: Image.Image,
    viewport_w: int,
    bg: Color,
    step: int = 2,
    max_frames: int = 48,
    travel: bool = False,
) -> list[Image.Image]:
    """Scroll content from the left edge toward the right. A still is centered unless travel is set."""
    content = content.convert("RGB")
    if content.height != PANEL_H:
        content = content.resize((content.width, PANEL_H), Image.Resampling.NEAREST)
    if not travel and content.width <= viewport_w:
        frame = blank(viewport_w, PANEL_H, bg)
        frame.paste(content, ((viewport_w - content.width) // 2, 0))
        return [frame]

    span = content.width + viewport_w
    step = max(1, step)
    positions = list(range(0, span + 1, step))
    if len(positions) > max_frames:
        step = max(1, math.ceil(span / max_frames))
        positions = list(range(0, span + 1, step))
    frames: list[Image.Image] = []
    for pos in positions[:max_frames]:
        frame = blank(viewport_w, PANEL_H, bg)
        frame.paste(content, (pos - content.width, 0))
        frames.append(frame)
    return frames or [blank(viewport_w, PANEL_H, bg)]


def image_strip(source: Image.Image) -> Image.Image:
    """Scale a picture to the 16-pixel row height, keeping its width."""
    image = source.convert("RGBA")
    width = max(1, round(image.width * (PANEL_H / max(1, image.height))))
    resized = image.resize((width, PANEL_H), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (width, PANEL_H), (0, 0, 0, 255))
    canvas.paste(resized, (0, 0), resized)
    return canvas.convert("RGB")


def fit_image(source: Image.Image, width: int, height: int, mode: str) -> Image.Image:
    image = source.convert("RGBA")
    if image.width < 1 or image.height < 1:
        return blank(width, height, (0, 0, 0))
    mode = mode if mode in {"letterbox", "cover", "stretch"} else "letterbox"
    if mode == "stretch":
        return image.resize((width, height), Image.Resampling.LANCZOS).convert("RGB")
    scale = (
        max(width / image.width, height / image.height)
        if mode == "cover"
        else min(width / image.width, height / image.height)
    )
    resized = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    if mode == "cover":
        left = max(0, (resized.width - width) // 2)
        top = max(0, (resized.height - height) // 2)
        cropped = resized.crop((left, top, left + width, top + height))
        canvas.paste(cropped, (0, 0), cropped)
    else:
        canvas.paste(
            resized,
            ((width - resized.width) // 2, (height - resized.height) // 2),
            resized,
        )
    return canvas.convert("RGB")


def split_sign(image: Image.Image) -> tuple[Image.Image, Image.Image]:
    """Cut a 16x192 frame into the left and right 16x96 panels."""
    frame = image.convert("RGB")
    if frame.size != (SIGN_W, PANEL_H):
        frame = frame.resize((SIGN_W, PANEL_H), Image.Resampling.NEAREST)
    return frame.crop((0, 0, PANEL_W, PANEL_H)), frame.crop((PANEL_W, 0, SIGN_W, PANEL_H))


def frames_gif(frames: list[Image.Image], delay_ms: int) -> bytes:
    buffer = BytesIO()
    first, *rest = frames
    first.save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=rest,
        duration=max(20, delay_ms),
        loop=0,
        disposal=2,
    )
    return buffer.getvalue()


def frames_png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


_ICONS: dict[str, list[str]] = {
    "clear": [
        "..#.#.#.#...",
        ".#..###..#..",
        "...#####....",
        "#.#######.#.",
        "...#####....",
        ".#..###..#..",
        "..#.#.#.#...",
    ],
    "fair": [
        "..#.#.#.....",
        ".#.#####....",
        "..#######...",
        "##########..",
        "..#####.....",
        ".....###....",
        ".....###....",
    ],
    "cloud": [
        "............",
        "...#####....",
        "..#######...",
        ".#########..",
        ".#########..",
        "..#######...",
        "............",
    ],
    "fog": [
        "............",
        ".########...",
        "............",
        "..########..",
        "............",
        ".########...",
        "............",
    ],
    "rain": [
        "...#####....",
        "..#######...",
        ".#########..",
        "..#######...",
        "...#..#..#..",
        "..#..#..#...",
        ".#..#..#....",
    ],
    "snow": [
        "...#####....",
        "..#######...",
        ".#########..",
        "..#..#..#...",
        ".#..#..#..#.",
        "..#..#..#...",
        ".#..#..#..#.",
    ],
    "storm": [
        "...#####....",
        "..#######...",
        ".#########..",
        "....##......",
        "...##.##....",
        "....##......",
        "...##.......",
    ],
}

_ICON_COLOR = {
    "clear": (255, 210, 63),
    "fair": (255, 196, 87),
    "cloud": (198, 214, 224),
    "fog": (176, 186, 170),
    "rain": (126, 200, 255),
    "snow": (238, 246, 255),
    "storm": (214, 186, 255),
}


def weather_kind(code: int) -> str:
    if code == 0:
        return "clear"
    if code in {1, 2}:
        return "fair"
    if code == 3:
        return "cloud"
    if code in {45, 48}:
        return "fog"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or 85 <= code <= 86:
        return "snow"
    if code >= 95:
        return "storm"
    return "cloud"


def weather_label(code: int) -> str:
    return {
        "clear": "CLEAR",
        "fair": "FAIR",
        "cloud": "CLOUDY",
        "fog": "FOG",
        "rain": "RAIN",
        "snow": "SNOW",
        "storm": "STORM",
    }[weather_kind(code)]


def _blit_icon(image: Image.Image, kind: str, x: int, y: int) -> None:
    rows = _ICONS[kind]
    color = _ICON_COLOR[kind]
    pixels = image.load()
    for row_index, row in enumerate(rows):
        for col_index, bit in enumerate(row):
            if bit == "#":
                px = x + col_index
                py = y + row_index
                if 0 <= px < image.width and 0 <= py < image.height:
                    pixels[px, py] = color


def render_weather(obs: dict) -> Image.Image:
    """One 16x192 frame: icon and temperature on the left, details on the right."""
    image = blank(SIGN_W, PANEL_H, (0, 0, 0))
    kind = obs.get("kind") if obs.get("kind") in _ICONS else weather_kind(int(obs.get("code") or 0))
    feel = str(obs.get("feel") or weather_label(int(obs.get("code") or 0)))
    _blit_icon(image, kind, 1, 4)

    temp = int(round(float(obs["temperature"])))
    unit = "F" if obs.get("units") == "fahrenheit" else "C"
    draw_text(image, str(temp), 16, 1, (255, 244, 214), scale=2, tracking=1)
    unit_x = 16 + text_width(str(temp), scale=2, tracking=1) + 2
    draw_text(image, unit, unit_x, 8, (255, 196, 87), scale=1)

    place = str(obs.get("place") or "HERE").upper()
    clock = str(obs.get("clock") or "")
    clock_w = text_width(clock, scale=1) if clock else 0
    room = SIGN_W - (clock_w + 2 if clock else 0) - PANEL_W
    shown = place
    while shown and text_width(shown) > room:
        shown = shown[:-1]
    draw_text(image, shown, PANEL_W, 0, (232, 240, 226), scale=1)
    if clock:
        draw_text(image, clock, SIGN_W - clock_w, 0, (166, 214, 255), scale=1)
    if obs.get("humidity") is not None:
        detail = f"{feel} {int(round(float(obs['humidity'])))}%"
    else:
        high = int(round(float(obs["high"])))
        low = int(round(float(obs["low"])))
        detail = f"{feel} {high}/{low}"
    draw_text(image, detail[:16], PANEL_W, 8, (166, 214, 255), scale=1)
    return image


def welcome_frame() -> Image.Image:
    content = layout_runs([("BRIGHT ", (214, 255, 74)), ("BERRY", (255, 176, 32))], (0, 0, 0), scale=2)
    return fit_frames(content, SIGN_W, (0, 0, 0))[0]
