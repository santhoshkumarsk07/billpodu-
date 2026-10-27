"""Draw the 83 MEN'S WEAR app icon (assets/app.ico + assets/app.png). Run: python packaging/icon/make_icon.py

Large sizes show "83" with "MEN'S WEAR"; small sizes show a bold "83" only so it stays readable.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
NAVY, GOLD, WHITE = (17, 24, 39, 255), (245, 180, 30, 255), (255, 255, 255, 255)
BOLD_FONTS = ["arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"]


def font(size: int) -> ImageFont.FreeTypeFont:
    for name in BOLD_FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def fit(draw, text, max_w, start):
    size = start
    while size > 6:
        f = font(size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 1
    return font(6)


def draw(size: int) -> Image.Image:
    s = 512  # draw large, then scale down smoothly
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((16, 16, s - 16, s - 16), radius=96, fill=NAVY)
    d.rounded_rectangle((40, 40, s - 40, s - 40), radius=76, outline=GOLD, width=10)
    if size >= 48:
        d.text((s / 2, 205), "83", font=font(250), fill=GOLD, anchor="mm")
        d.rectangle((120, 330, s - 120, 340), fill=GOLD)
        f = fit(d, "MEN'S WEAR", s - 130, 78)
        d.text((s / 2, 400), "MEN'S WEAR", font=f, fill=WHITE, anchor="mm")
    else:
        d.text((s / 2, s / 2 + 8), "83", font=font(330), fill=GOLD, anchor="mm")
    return img.resize((size, size), Image.LANCZOS)


def main():
    sizes = [256, 128, 64, 48, 32, 24, 16]
    images = [draw(n) for n in sizes]
    (ROOT / "assets").mkdir(exist_ok=True)
    images[0].save(ROOT / "assets" / "app.ico", sizes=[(n, n) for n in sizes], append_images=images[1:])
    images[0].save(ROOT / "assets" / "app.png")


if __name__ == "__main__":
    main()
