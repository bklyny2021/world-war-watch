"""Regenerate camera icons — BRIGHT filled squares (no dark bodies that read as black dots)."""
from PIL import Image, ImageDraw

SIZE = 20


def make_cam(fill, lens, name):
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # bright filled body with white border
    d.rectangle([1, 1, SIZE - 2, SIZE - 2], fill=fill)
    d.rectangle([1, 1, SIZE - 2, SIZE - 2], outline=(255, 255, 255, 255), width=1)
    # camera body
    d.rectangle([4, 7, 15, 13], fill=(255, 255, 255, 255))
    # lens (dark)
    d.ellipse([7, 8, 12, 13], fill=(10, 14, 20, 255))
    d.ellipse([8, 9, 11, 12], fill=(120, 200, 255, 255))
    # top bump
    d.rectangle([8, 4, 11, 7], fill=(255, 255, 255, 255))
    img.save(name)
    print(f"saved {name}")


make_cam((56, 189, 248), (10, 14, 20), "camera_icon.png")       # bright cyan (NYC)
make_cam((255, 170, 40), (10, 14, 20), "camera_icon_nc.png")    # bright amber (NC)
