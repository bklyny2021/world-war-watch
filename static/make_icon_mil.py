"""Generate the military plane icon (amber, distinct from commercial cyan)."""
from PIL import Image, ImageDraw

SIZE = 64
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
c = (SIZE / 2, SIZE / 2)
color = (255, 60, 60)          # red
outline = (255, 200, 200)      # light red outline

# fuselage (vertical, pointing up/north)
d.polygon([(c[0] - 3.5, c[1] + 18), (c[0] + 3.5, c[1] + 18),
           (c[0] + 3.5, c[1] - 16), (c[0] - 3.5, c[1] - 16)], fill=color)
d.polygon([(c[0] - 3.5, c[1] - 16), (c[0] + 3.5, c[1] - 16),
           (c[0], c[1] - 26)], fill=color)
d.polygon([(c[0] - 4, c[1] + 14), (c[0] + 4, c[1] + 14),
           (c[0], c[1] + 28)], fill=color)
# wings
d.polygon([(c[0] - 4, c[1] - 5), (c[0] - 28, c[1] + 12),
           (c[0] - 28, c[1] + 6), (c[0] - 4, c[1] - 12)], fill=color)
d.polygon([(c[0] + 4, c[1] - 5), (c[0] + 28, c[1] + 12),
           (c[0] + 28, c[1] + 6), (c[0] + 4, c[1] - 12)], fill=color)
# stabilizers
d.polygon([(c[0] - 3.5, c[1] + 16), (c[0] - 16, c[1] + 23),
           (c[0] - 16, c[1] + 19), (c[0] - 3.5, c[1] + 12)], fill=color)
d.polygon([(c[0] + 3.5, c[1] + 16), (c[0] + 16, c[1] + 23),
           (c[0] + 16, c[1] + 19), (c[0] + 3.5, c[1] + 12)], fill=color)

# light outline
out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)]:
    tmp = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    tmp.paste(img, (dx, dy))
    out = Image.alpha_composite(out, tmp)
mask = img.split()[3]
outline_img = Image.new("RGBA", (SIZE, SIZE), outline + (255,))
base = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
base.paste(outline_img, (0, 0), mask)
base.paste(img, (0, 0), mask)
base.save("plane_mil.png")
print("saved plane_mil.png")
