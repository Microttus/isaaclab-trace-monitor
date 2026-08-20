#!/usr/bin/env python3
"""Generate the IsaacLab Trace Monitor application icon.

The generated PNG is used by Qt while the ICNS file is used by the macOS
application bundle. Pillow is only required when regenerating the assets.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


OUTPUT_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "isaaclab_trace_monitor" / "assets"
)
CANVAS_SIZE = 1024
SCALE = 4


def _scaled_point(point: tuple[float, float]) -> tuple[int, int]:
    return (round(point[0] * SCALE), round(point[1] * SCALE))


def _cubic_bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    samples: int = 160,
) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    for index in range(samples + 1):
        t = index / samples
        u = 1.0 - t
        x = (
            u**3 * p0[0]
            + 3.0 * u * u * t * p1[0]
            + 3.0 * u * t * t * p2[0]
            + t**3 * p3[0]
        )
        y = (
            u**3 * p0[1]
            + 3.0 * u * u * t * p1[1]
            + 3.0 * u * t * t * p2[1]
            + t**3 * p3[1]
        )
        points.append(_scaled_point((x, y)))
    return points


def _gradient_square(size: int, radius: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pixels = image.load()
    for y in range(size):
        vertical = y / max(size - 1, 1)
        for x in range(size):
            horizontal = x / max(size - 1, 1)
            radial = math.hypot(horizontal - 0.33, vertical - 0.2)
            mix = min(
                max(0.58 * vertical + 0.32 * horizontal + 0.10 * radial, 0.0), 1.0
            )
            start = (31, 52, 91)
            end = (14, 24, 45)
            red = round(start[0] * (1.0 - mix) + end[0] * mix)
            green = round(start[1] * (1.0 - mix) + end[1] * mix)
            blue = round(start[2] * (1.0 - mix) + end[2] * mix)
            pixels[x, y] = (red, green, blue, 255)

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=radius, fill=255
    )
    image.putalpha(mask)
    return image


def _draw_node(
    image: Image.Image,
    center: tuple[float, float],
    radius: float,
    fill: tuple[int, int, int, int],
) -> None:
    cx, cy = _scaled_point(center)
    r = round(radius * SCALE)

    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.ellipse(
        (cx - r, cy - r + 7 * SCALE, cx + r, cy + r + 7 * SCALE),
        fill=(0, 0, 0, 120),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(10 * SCALE))
    image.alpha_composite(shadow)

    draw = ImageDraw.Draw(image)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)
    highlight_r = max(round(radius * 0.33 * SCALE), 1)
    highlight_cx = cx - round(radius * 0.28 * SCALE)
    highlight_cy = cy - round(radius * 0.30 * SCALE)
    draw.ellipse(
        (
            highlight_cx - highlight_r,
            highlight_cy - highlight_r,
            highlight_cx + highlight_r,
            highlight_cy + highlight_r,
        ),
        fill=(255, 255, 255, 95),
    )


def generate_icon() -> None:
    work_size = CANVAS_SIZE * SCALE
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    icon = Image.new("RGBA", (work_size, work_size), (0, 0, 0, 0))

    shadow = Image.new("RGBA", icon.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    margin = 78 * SCALE
    shadow_draw.rounded_rectangle(
        (
            margin,
            margin + 18 * SCALE,
            work_size - margin,
            work_size - margin + 18 * SCALE,
        ),
        radius=214 * SCALE,
        fill=(0, 0, 0, 150),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(34 * SCALE))
    icon.alpha_composite(shadow)

    square_size = work_size - 2 * margin
    square = _gradient_square(square_size, 205 * SCALE)
    icon.alpha_composite(square, (margin, margin))

    overlay = Image.new("RGBA", icon.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    # Subtle trajectory-analysis grid.
    grid_left = 214
    grid_top = 230
    grid_right = 812
    grid_bottom = 806
    for x in range(grid_left, grid_right + 1, 100):
        overlay_draw.line(
            [_scaled_point((x, grid_top)), _scaled_point((x, grid_bottom))],
            fill=(163, 204, 231, 22),
            width=2 * SCALE,
        )
    for y in range(grid_top, grid_bottom + 1, 96):
        overlay_draw.line(
            [_scaled_point((grid_left, y)), _scaled_point((grid_right, y))],
            fill=(163, 204, 231, 22),
            width=2 * SCALE,
        )

    # Perspective coordinate axes.
    origin = (330, 706)
    x_axis = (724, 759)
    y_axis = (226, 425)
    z_axis = (420, 277)
    axis_width = 13 * SCALE
    overlay_draw.line(
        [_scaled_point(origin), _scaled_point(x_axis)],
        fill=(89, 222, 255, 205),
        width=axis_width,
    )
    overlay_draw.line(
        [_scaled_point(origin), _scaled_point(y_axis)],
        fill=(122, 247, 189, 190),
        width=axis_width,
    )
    overlay_draw.line(
        [_scaled_point(origin), _scaled_point(z_axis)],
        fill=(255, 189, 90, 205),
        width=axis_width,
    )

    for endpoint, color in (
        (x_axis, (89, 222, 255, 255)),
        (y_axis, (122, 247, 189, 255)),
        (z_axis, (255, 189, 90, 255)),
    ):
        ex, ey = endpoint
        ox, oy = origin
        angle = math.atan2(ey - oy, ex - ox)
        tip = _scaled_point(endpoint)
        wing_a = _scaled_point(
            (
                ex - 37 * math.cos(angle - 0.55),
                ey - 37 * math.sin(angle - 0.55),
            )
        )
        wing_b = _scaled_point(
            (
                ex - 37 * math.cos(angle + 0.55),
                ey - 37 * math.sin(angle + 0.55),
            )
        )
        overlay_draw.polygon([tip, wing_a, wing_b], fill=color)

    icon.alpha_composite(overlay)

    # Object/tool trajectory with a soft outer glow and a crisp center line.
    curve = _cubic_bezier(
        (272, 690),
        (315, 460),
        (635, 600),
        (756, 344),
    )
    glow = Image.new("RGBA", icon.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.line(
        curve,
        fill=(79, 222, 255, 150),
        width=42 * SCALE,
        joint="curve",
    )
    glow = glow.filter(ImageFilter.GaussianBlur(20 * SCALE))
    icon.alpha_composite(glow)

    path_layer = Image.new("RGBA", icon.size, (0, 0, 0, 0))
    path_draw = ImageDraw.Draw(path_layer)
    path_draw.line(
        curve,
        fill=(220, 250, 255, 255),
        width=16 * SCALE,
        joint="curve",
    )
    path_draw.line(
        curve,
        fill=(87, 218, 255, 255),
        width=8 * SCALE,
        joint="curve",
    )
    icon.alpha_composite(path_layer)

    _draw_node(icon, (272, 690), 37, (123, 245, 188, 255))
    _draw_node(icon, (450, 532), 31, (90, 223, 255, 255))
    _draw_node(icon, (625, 524), 31, (90, 223, 255, 255))
    _draw_node(icon, (756, 344), 44, (255, 184, 76, 255))

    # A small central cube indicates a tracked rigid object.
    cube = Image.new("RGBA", icon.size, (0, 0, 0, 0))
    cube_draw = ImageDraw.Draw(cube)
    top = [
        _scaled_point(point)
        for point in ((520, 348), (584, 314), (648, 350), (584, 386))
    ]
    left = [
        _scaled_point(point)
        for point in ((520, 348), (584, 386), (584, 465), (520, 425))
    ]
    right = [
        _scaled_point(point)
        for point in ((584, 386), (648, 350), (648, 428), (584, 465))
    ]
    cube_draw.polygon(top, fill=(196, 241, 255, 230))
    cube_draw.polygon(left, fill=(61, 160, 208, 230))
    cube_draw.polygon(right, fill=(84, 198, 237, 235))
    cube_draw.line(top + [top[0]], fill=(235, 253, 255, 210), width=5 * SCALE)
    icon.alpha_composite(cube)

    icon = icon.resize((CANVAS_SIZE, CANVAS_SIZE), Image.Resampling.LANCZOS)
    png_path = OUTPUT_DIR / "app_icon.png"
    icns_path = OUTPUT_DIR / "app_icon.icns"
    icon.save(png_path, optimize=True)
    icon.save(icns_path)

    print(f"Created {png_path}")
    print(f"Created {icns_path}")


if __name__ == "__main__":
    generate_icon()
