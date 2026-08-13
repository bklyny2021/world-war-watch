"""Regenerate plane billboard icons — NO dark glow halo (that was the black circle).

The old icons had a large translucent glow ellipse behind the plane; at small
scales on a dark globe it read as a solid black circle. New icons: big bright
plane silhouette with a strong light outline, no halo.
"""
from PIL import Image, ImageDraw

SIZE = 64


def make_plane(color, outline, name):
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = (SIZE / 2, SIZE / 2)

    # fuselage (vertical, pointing up/north) — bigger
    d.polygon([(c[0] - 3.5, c[1] + 18), (c[0] + 3.5, c[1] + 18),
               (c[0] + 3.5, c[1] - 16), (c[0] - 3.5, c[1] - 16)], fill=color)
    # nose
    d.polygon([(c[0] - 3.5, c[1] - 16), (c[0] + 3.5, c[1] - 16),
               (c[0], c[1] - 26)], fill=color)
    # tail
    d.polygon([(c[0] - 4, c[1] + 14), (c[0] + 4, c[1] + 14),
               (c[0], c[1] + 28)], fill=color)

    # wings (swept back) — bigger
    d.polygon([(c[0] - 4, c[1] - 5), (c[0] - 28, c[1] + 12),
               (c[0] - 28, c[1] + 6), (c[0] - 4, c[1] - 12)], fill=color)
    d.polygon([(c[0] + 4, c[1] - 5), (c[0] + 28, c[1] + 12),
               (c[0] + 28, c[1] + 6), (c[0] + 4, c[1] - 12)], fill=color)

    # horizontal stabilizers
    d.polygon([(c[0] - 3.5, c[1] + 16), (c[0] - 16, c[1] + 23),
               (c[0] - 16, c[1] + 19), (c[0] - 3.5, c[1] + 12)], fill=color)
    d.polygon([(c[0] + 3.5, c[1] + 16), (c[0] + 16, c[1] + 23),
               (c[0] + 16, c[1] + 19), (c[0] + 3.5, c[1] + 12)], fill=color)

    # strong light outline (paste silhouette on 8 offsets, then composite)
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
    base.save(name)
    print(f"saved {name}")


make_plane((56, 189, 248), (230, 240, 250), "plane.png")        # bright sky blue + near-white outline
make_plane((255, 204, 0), (255, 240, 200), "plane_sel.png")     # amber + light outline
