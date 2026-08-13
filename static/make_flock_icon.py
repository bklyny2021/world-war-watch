"""Flock ALPR icon — glowing amber license-plate reader crosshair (24x24)."""
from PIL import Image, ImageDraw

SIZE = 24
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
# glow ring
d.ellipse([0, 0, SIZE - 1, SIZE - 1], outline=(255, 170, 0, 110), width=2)
# amber square body with white border
d.rectangle([2, 2, SIZE - 3, SIZE - 3], fill=(255, 170, 0, 255))
d.rectangle([2, 2, SIZE - 3, SIZE - 3], outline=(255, 255, 255, 255), width=2)
# crosshair: white cross
d.line([12, 4, 12, 20], fill=(255, 255, 255, 255), width=2)
d.line([4, 12, 20, 12], fill=(255, 255, 255, 255), width=2)
# center dot (lens)
d.ellipse([9, 9, 15, 15], fill=(10, 14, 20, 255))
d.ellipse([10, 10, 14, 14], fill=(255, 220, 120, 255))
# corner ticks
for (x1, y1, x2, y2) in [(4,4,7,4),(4,4,4,7),(17,4,20,4),(20,4,20,7),(4,17,4,20),(4,20,7,20),(17,20,20,20),(20,17,20,20)]:
    d.line([x1, y1, x2, y2], fill=(255, 255, 255, 255), width=1)
img.save("flock_icon.png")
print("saved flock_icon.png")
