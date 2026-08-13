"""Hurricane/cyclone icon (24x24) — orange spiral with glow."""
from PIL import Image, ImageDraw

SIZE = 24
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# outer glow
for r, a in [(11, 40), (9, 70), (7, 110)]:
    d.ellipse([12 - r, 12 - r, 12 + r, 12 + r], fill=(255, 159, 67, a))

# spiral arms (approximate cyclone swirl with arcs)
d.arc([5, 5, 19, 19], start=20, end=200, fill=(255, 159, 67, 255), width=3)
d.arc([7, 7, 17, 17], start=210, end=340, fill=(255, 200, 120, 255), width=2)
# center eye
d.ellipse([10, 10, 14, 14], fill=(255, 250, 230, 255))

img.save("hurricane_icon.png")
print("saved hurricane_icon.png")
