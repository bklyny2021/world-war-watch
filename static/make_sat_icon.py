"""Generate the satellite icon (purple, distinct from planes/cameras)."""
from PIL import Image, ImageDraw

SIZE = 40
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
c = (SIZE / 2, SIZE / 2)
color = (192, 132, 252)        # purple
outline = (240, 230, 255)

# satellite body (diamond-ish)
d.polygon([(c[0], c[1] - 12), (c[0] + 9, c[1]), (c[0], c[1] + 12), (c[0] - 9, c[1])], fill=color)
# solar panels (left/right)
d.rectangle([c[0] - 19, c[1] - 4, c[0] - 9, c[1] + 4], fill=color)
d.rectangle([c[0] + 9, c[1] - 4, c[0] + 19, c[1] + 4], fill=color)
# antenna
d.line([c[0], c[1] - 12, c[0], c[1] - 18], fill=color, width=2)
d.ellipse([c[0] - 2, c[1] - 20, c[0] + 2, c[1] - 16], fill=outline)

# light outline
out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
    tmp = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    tmp.paste(img, (dx, dy))
    out = Image.alpha_composite(out, tmp)
mask = img.split()[3]
outline_img = Image.new("RGBA", (SIZE, SIZE), outline + (255,))
base = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
base.paste(outline_img, (0, 0), mask)
base.paste(img, (0, 0), mask)
base.save("sat_icon.png")
print("saved sat_icon.png")
