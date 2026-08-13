"""3-tier rollback: strip shader/view-mode code, create v1_stable + v_working."""
import re, shutil, sys

SRC = r"C:\Users\bklyn\worldview\static\index.html"
V1 = r"C:\Users\bklyn\worldview\static\index.html.v1_stable"
VW = r"C:\Users\bklyn\worldview\static\index.html.v_working"

html = open(SRC, encoding="utf-8").read()

# 1) save current as v_working (pre-edit backup per rule)
shutil.copyfile(SRC, VW)
print("saved index.html.v_working (pre-edit)")

# 2) remove the JS shader/view-mode block (from its header to the satellite section)
start = html.find("   Post-processing view modes")
end = html.find("   Satellite selection & ground detection cones")
if start == -1 or end == -1:
    print("ERROR: shader block markers not found"); sys.exit(1)
# back up to the comment banner start
banner = html.rfind("/* ============================================================", 0, start)
html = html[:banner] + html[end:]
print("removed shader/view-mode JS block")

# 3) remove the viewMode select HTML
vm_start = html.find('<span id="viewModeLabel">')
vm_end = html.find("</select>", vm_start) + len("</select>\n")
if vm_start != -1:
    html = html[:vm_start] + html[vm_end:]
    print("removed viewMode select HTML")

# 4) remove the #viewMode CSS (keep satInfoCard CSS - satellite feature stays)
css_start = html.find("  /* ---------- view mode switcher ---------- */")
css_end = html.find("  /* ---------- satellite info card ---------- */")
if css_start != -1 and css_end != -1:
    html = html[:css_start] + html[css_end:]
    print("removed viewMode CSS")

# 5) make the atmosphere-off setting stick after async terrain load
old = """  viewer.terrainProvider = terrain;
  console.log("[worldview] 3D terrain loaded");"""
new = """  viewer.terrainProvider = terrain;
  // re-apply atmosphere-off AFTER terrain swap (terrain load resets it)
  viewer.scene.globe.showGroundAtmosphere = false;
  viewer.scene.globe.dynamicAtmosphereLighting = false;
  console.log("[worldview] 3D terrain loaded");"""
if old in html:
    html = html.replace(old, new)
    print("atmosphere-off re-applied after terrain load")
else:
    print("WARN: terrain .then() block not found")

open(SRC, "w", encoding="utf-8").write(html)
shutil.copyfile(SRC, V1)
print("saved index.html (cleaned) + index.html.v1_stable")
