# Brand assets

The mark: a house with a person drawn in dots - "somebody is home, but there is
no tracker for them". The house is Home Assistant blue (`#18BCF2`), the outline
is ink (`#191512`) on light surfaces and off-white (`#F3F1EE`) on dark ones.

| Light | Dark | |
| --- | --- | --- |
| `icon.png` (256) / `icon@2x.png` (512) | `dark_icon.png` / `dark_icon@2x.png` | Square app icon |
| `logo.png` / `logo@2x.png` | `dark_logo.png` / `dark_logo@2x.png` | Wordmark ("Virtual Presence Tracker" + descriptor) |

Each has a matching `*.svg` source. Home Assistant (2026.3+) loads these directly
from this folder - no `home-assistant/brands` PR needed - and picks the `dark_*`
variant in dark mode.

The PNGs are committed, rendered from the SVGs with
[resvg](https://github.com/RazrFalcon/resvg). Regenerate after editing an SVG:

```sh
for v in icon dark_icon; do
  resvg -w 256 -h 256 "$v.svg" "$v.png"
  resvg -w 512 -h 512 "$v.svg" "$v@2x.png"
done
for v in logo dark_logo; do
  resvg -h 256 "$v.svg" "$v.png"
  resvg -h 512 "$v.svg" "$v@2x.png"
done
```

The `logo` SVGs ask for Segoe UI and fall back to Arial / any sans-serif, so the
PNGs use whichever of those the renderer finds. That is fine for the README and
the HACS card. For a `home-assistant/brands` PR (only needed for HA < 2026.3 or
the public HACS store), convert the `<text>` to outlines first (Inkscape:
*Path -> Object to Path*).
