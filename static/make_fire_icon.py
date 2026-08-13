"""Glowing fire/flame icon (24x24) — orange/red flame with glow."""
from PIL import Image, ImageDraw

SIZE = 24
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# outer glow
for r, a in [(11, 40), (9, 70), (7, 110)]:
    d.ellipse([12 - r, 12 - r, 12 + r, 12 + r], fill=(255, 120, 20, a))

# flame body (teardrop)
d.polygon([(12, 3), (17, 13), (17, 19), (7, 19), (7, 13)], fill=(255, 90, 10, 255))
# inner bright core
d.polygon([(12, 7), (15, 13), (15, 18), (9, 18), (9, 13)], fill=(255, 200, 40, 255))
# white-hot tip
d.ellipse([10, 5, 14, 9], fill=(255, 250, 200, 255))

img.save("fire_icon.png")
print("saved fire_icon.png")
