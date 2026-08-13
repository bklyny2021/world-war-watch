"""Ship icons by type (64x64, top-down, pointing up/north) — SAME SIZE as
plane icons (64x64) so ships are as visible as planes at any zoom.
cargo = cyan/blue, tanker = red/orange, military = gold, passenger = green, other = white."""
from PIL import Image, ImageDraw

SIZE = 64

def make_ship(color, outline, name):
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # hull (top-down ship shape: pointed bow up, flat stern)
    d.polygon([(32, 6), (44, 22), (46, 52), (18, 52), (20, 22)], fill=color, outline=outline, width=2)
    # bridge / superstructure
    d.rectangle([26, 26, 38, 40], fill=outline)
    # wake line at stern
    d.line([(22, 56), (42, 56)], fill=outline, width=2)
    img.save(f"ship_{name}.png")
    print(f"saved ship_{name}.png")

make_ship((56, 189, 248, 255), (200, 240, 255, 255), "cargo")      # cyan
make_ship((255, 100, 60, 255), (255, 220, 200, 255), "tanker")     # red/orange
make_ship((255, 200, 60, 255), (255, 240, 200, 255), "military")   # gold
make_ship((80, 220, 120, 255), (200, 255, 220, 255), "passenger")  # green
make_ship((220, 230, 240, 255), (255, 255, 255, 255), "other")     # white
