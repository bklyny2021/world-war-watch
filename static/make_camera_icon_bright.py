"""Regenerate camera icons — BRIGHT high-contrast (spec: camera_icon_bright.png).
24x24 filled body, white outline, glow ring, camera glyph. Reads clearly over road imagery."""
from PIL import Image, ImageDraw

SIZE = 24


def make_cam(fill, name):
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # glow ring (outer halo)
    d.ellipse([0, 0, SIZE - 1, SIZE - 1], outline=fill + (90,), width=2)
    # bright filled body with white border
    d.rectangle([2, 2, SIZE - 3, SIZE - 3], fill=fill)
    d.rectangle([2, 2, SIZE - 3, SIZE - 3], outline=(255, 255, 255, 255), width=2)
    # camera body (white)
    d.rectangle([5, 9, 18, 16], fill=(255, 255, 255, 255))
    # lens (dark w/ blue glint)
    d.ellipse([8, 10, 15, 15], fill=(10, 14, 20, 255))
    d.ellipse([9, 11, 13, 14], fill=(140, 210, 255, 255))
    # top bump
    d.rectangle([10, 5, 13, 9], fill=(255, 255, 255, 255))
    img.save(name)
    print(f"saved {name}")


make_cam((56, 189, 248), "camera_icon_bright.png")       # bright cyan (NYC)
make_cam((255, 170, 40), "camera_icon_bright_nc.png")    # bright amber (NC)
