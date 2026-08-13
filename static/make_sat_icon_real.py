"""Realistic grey-scale satellite icon (48x48) — body + solar panels,
like real satellite imagery. White/grey tones so it reads as hardware."""
from PIL import Image, ImageDraw

SIZE = 48
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# --- solar panels (grey-blue, left and right) ---
panel = (150, 158, 168, 255)
panel_dark = (110, 118, 128, 255)
# left panel
d.rectangle([2, 18, 16, 30], fill=panel, outline=(90, 98, 108, 255), width=1)
d.line([2, 22, 16, 22], fill=panel_dark, width=1)
d.line([2, 26, 16, 26], fill=panel_dark, width=1)
# right panel
d.rectangle([32, 18, 46, 30], fill=panel, outline=(90, 98, 108, 255), width=1)
d.line([32, 22, 46, 22], fill=panel_dark, width=1)
d.line([32, 26, 46, 26], fill=panel_dark, width=1)

# --- satellite body (grey box) ---
d.rectangle([16, 14, 32, 34], fill=(200, 205, 212, 255), outline=(90, 98, 108, 255), width=1)
# body details
d.rectangle([18, 18, 30, 30], fill=(170, 176, 184, 255), outline=(120, 128, 138, 255), width=1)
# sensor/lens on front
d.ellipse([22, 20, 26, 24], fill=(60, 66, 74, 255))
d.ellipse([23, 21, 25, 23], fill=(140, 200, 255, 255))   # blue glint

# --- antenna dish (top) ---
d.ellipse([20, 4, 28, 12], fill=(180, 186, 194, 255), outline=(90, 98, 108, 255), width=1)
d.line([24, 12, 24, 14], fill=(90, 98, 108, 255), width=1)

# --- bottom sensor ---
d.ellipse([21, 36, 27, 42], fill=(120, 128, 138, 255), outline=(80, 88, 98, 255), width=1)

img.save("sat_icon.png")
print("saved realistic grey satellite icon")
