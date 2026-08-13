"""Generate the NC DOT camera icon (amber square + camera glyph)."""
from PIL import Image, ImageDraw

SIZE = 20
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# dark rounded body
d.rectangle([1, 1, SIZE - 2, SIZE - 2], fill=(16, 22, 32, 235))
d.rectangle([1, 1, SIZE - 2, SIZE - 2], outline=(255, 170, 40, 255), width=1)
# camera body
d.rectangle([4, 7, 15, 13], fill=(255, 170, 40, 255))
# lens
d.ellipse([7, 8, 12, 13], fill=(10, 14, 20, 255))
d.ellipse([8, 9, 11, 12], fill=(120, 200, 255, 255))
# top bump
d.rectangle([8, 4, 11, 7], fill=(255, 170, 40, 255))

img.save("camera_icon_nc.png")
print("saved camera_icon_nc.png")
