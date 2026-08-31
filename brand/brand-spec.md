# WattNext — Brand Mark Spec

**Version:** 1.4 (primary + compact mark + raster favicons) · **Date:** 2026-08-30

WattNext is a proactive energy/utilities AI: it watches customer energy data, detects
anomalies before the customer complains, and delivers a resolution ahead of the problem.
The mark encodes that story in a single gesture.

---

## 1. The idea

A single continuous **pulse** enters as a calm monitoring baseline (the node = the signal
being watched), climbs through the peaks of a **W** (Watt) and an **N** (Next), then
**breaks out and up** — the proactive resolution launching before the issue lands.

- **Node** → detection / always-on monitoring
- **W + N peaks** → the energy data (Watt) and the forward move (Next) in the signal
- **Breakout arrow** → decisive, forward action ("Next", "AI THAT ACTS")

Narrates the tagline: **DETECT → DECIDE → DELIVER**.

---

## 2. Files in this folder

| File | Use |
|------|-----|
| `wattnext-primary-on-dark.svg` | Primary lockup on brand ink background. Default logo. |
| `wattnext-mark.svg` | Symbol only (no wordmark), transparent. For app headers, tight spaces, watermarks. |
| `wattnext-lockup-mono-white.svg` | Single-color white lockup, transparent. For photos, dark surfaces, one-ink print. |
| `wattnext-lockup-on-light.svg` | Gradient mark + dark wordmark, transparent. For white/light backgrounds. |
| `wattnext-favicon.svg` | Compact square app-icon / favicon on the ink tile. 256×256, scales to 16px. |
| `wattnext-favicon-transparent.svg` | Same compact mark, transparent, for a custom tile or colored surface. |
| `favicons/` | Deploy-ready raster bundle — see below. |

### `favicons/` bundle

| File | Size(s) | Use |
|------|---------|-----|
| `favicon.ico` | 16 / 32 / 48 | Legacy browser tab icon |
| `favicon-16.png` `favicon-32.png` `favicon-48.png` `favicon-64.png` | as named | Modern PNG favicons (rounded, transparent corners) |
| `apple-touch-icon.png` | 180 | iOS home screen (square, no alpha — iOS masks corners) |
| `icon-192.png` `icon-512.png` | 192 / 512 | Android / PWA (square ink bg) |
| `wattnext-favicon.svg` | vector | Modern SVG favicon |
| `site.webmanifest` | — | PWA manifest referencing the 192/512 icons |
| `head-snippet.html` | — | Ready-to-paste `<head>` `<link>` tags |

Regenerate with `scratchpad/render.js` (Node + `sharp` + `png-to-ico`) if the mark changes.

---

## 3. Color

| Role | Name | Hex |
|------|------|-----|
| Primary | Electric Blue | `#2563EB` |
| Accent | Cyan | `#06B6D4` |
| Wordmark "Next" (on dark) | Bright Cyan | `#22D3EE` |
| Tagline (on dark) | Sky | `#38BDF8` |
| "Next" / tagline (on light) | Deep Cyan | `#0891B2` |
| Background | Ink | `#0F172A` |
| Reversed / mono | White | `#FFFFFF` |
| Panel hairline (optional) | Slate | `#1E293B` |

**Mark gradient** — linear, along the baseline→arrow axis:

```
linearGradient (userSpaceOnUse) x1=155 y1=285  x2=521 y2=54
  stop 0%   #2563EB
  stop 45%  #2563EB
  stop 72%  #06B6D4
  stop 100% #22D3EE
```

The blue W holds through the first two peaks, then shifts through cyan to a bright-cyan
breakout — the color change reinforces "data → action." The node is blue `#2563EB` (it sits
at the blue end); the arrowhead is bright cyan `#22D3EE`. Do not alter the direction or stops.

**Glow (dark surfaces only):** the on-dark mark carries a soft outer glow —
`feGaussianBlur stdDeviation="3.5"` merged under the sharp strokes. Applied in
`wattnext-primary-on-dark.svg` and `wattnext-mark.svg`; omitted on light and favicon variants
(it muddies small sizes and halos on white).

---

## 4. Geometry (primary, in a 680×400 canvas)

Mark stroke: **width 13**, `stroke-linecap="round"`, `stroke-linejoin="round"`, `fill="none"`.

```
Pulse path:  M155,285 L245,285 L265,110 L305,250 L345,150 L385,250 L425,110 L465,250 L521,54
             (W = the three peaks 265/345/425; the breakout arrow (465,250)->(521,54) is
              parallel to the W's last up-leg (385,250)->(425,110): both are vector (2,-7))
Arrowhead:   polyline 498,76  521,54  529,85   (stroke #06B6D4, width 13, round)
Node:        circle cx=223 cy=285 r=8.5  (fill #06B6D4)
Wordmark:    "WattNext" 38px bold, centered x=340, baseline y=344
Tagline:     "DETECT · DECIDE · DELIVER" 12px, weight 600, letter-spacing 4, baseline y=370
```

Wordmark set in a geometric sans (mockups use Arial as a safe fallback; substitute the
brand's chosen sans — e.g. Inter / Plus Jakarta Sans — at build time). The tagline
`DETECT · DECIDE · DELIVER` is the only ALL-CAPS element; keep the wordmark itself
mixed-case as `WattNext`.

---

## 5. Clear space & minimum size

- **Clear space:** keep padding on all sides equal to the node diameter (**≈ 17px** at the
  680-wide canvas scale, i.e. `2 × r`). Nothing intrudes inside that margin.
- **Minimum size (primary lockup):** 160px wide on screen / 45mm in print. Below this the
  tagline drops legibility — use the mark-only file instead.
- **Minimum size (mark only):** 88px wide. Below this, switch to the compact favicon mark.
- **Compact mark (favicon):** designed to hold from 256px down to **16px**. Below 24px the node
  dot visually merges into the baseline — that is expected and fine.

---

## 6. Do / Don't

**Do**
- Keep the mark flat — the gradient is the only color treatment.
- Use `wattnext-lockup-mono-white.svg` on photos or busy/low-contrast backgrounds.
- Preserve the blue→cyan gradient direction and the round caps.

**Don't**
- Stretch, squash, or rotate the mark.
- Recolor the gradient, flip its direction, or swap in other colors.
- Add drop shadows, outer glow, bevels, or neon effects.
- Place the full-color mark on a background that kills contrast (use mono white/blue instead).
- Rebuild the pulse with different peak counts or heights — the rhythm is fixed.

---

## 7. Open / next

- [x] **Compact square mark** for app icon & favicon — done (`wattnext-favicon*.svg`). One spike +
      breakout arrow (parallel to the spike leg) + node in a rounded ink tile; holds to 16px.
- [x] Export favicon to raster/ICO — done. See `favicons/` (below).
- [ ] Final **bezier polish** in vector tooling (optical stroke tapering, exact peak angles).
- [ ] Confirm the production **wordmark typeface** and regenerate lockups with it embedded/outlined.

### Compact mark geometry (256×256 canvas)

```
Tile:      rect 0,0 256,256 rx=60  fill #0F172A  (omit in the transparent variant)
Spike:     M50,198 L86,198 L118,72 L150,198 L187,53   stroke url(#pg), width 20, round
Arrowhead: polyline 162,77  187,53  197,85   stroke #06B6D4, width 20, round
Node:      circle cx=68 cy=198 r=12  fill #06B6D4
Gradient:  linear (userSpaceOnUse) x1=50 y1=198  x2=187 y2=53 — #2563EB 0%, #2563EB 65%, #06B6D4 100%
```

The breakout arrow `(150,198)->(187,53)` is parallel to the spike's up-leg `(86,198)->(118,72)`,
keeping the compact mark consistent with the primary.
