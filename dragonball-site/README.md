# Dragon Ball — Saiyan Hub (Advanced Edition)

A single-page Dragon Ball fan hub built with **vanilla HTML, CSS and JavaScript**. No build step, no dependencies — open `index.html`.

## Files

| File | Purpose |
| --- | --- |
| `index.html` | Semantic markup for all sections, modal and toasts container. |
| `styles.css` | Theming via CSS custom properties, layout, animation, responsive rules. |
| `script.js` | All behaviour: roster, battle sim, radar, collection, ki game, stats, FX. |

## Features

### Hero
- Animated aura rings, glow title, typewriter tagline.
- Live counters that count up on load (fighters, peak power, balls collected).

### Fighter roster
- 10 fighters, each with 2–4 transformations.
- Live search across name / race / form.
- Race filter and sorting (strongest, weakest, A–Z).
- "Transform" cycles a fighter's form; power recalculates everywhere.
- "Transform all to max" pushes every fighter to their final form.
- 3D mouse-tilt on cards (disabled for touch / reduced-motion).

### Battle simulator
- Pick any two fighters, or hit **Pick** on a roster card.
- Single fight: round-by-round simulation with ±15% damage variance, 20-round cap.
- **Best of 5** series mode.
- Clash bar shows the power share between the two fighters.

### Dragon Radar
- Canvas radar with concentric rings, crosshair and rotating sweep beam.
- **Scan** finds signals for every uncollected ball; click a blip to collect it.
- **Auto Scan** recovers all remaining balls in sequence.

### Dragon Balls
- 7 collectible balls; state persists in `localStorage`.
- Summon button unlocks at 7/7 and opens the Shenron modal.
- 4 wishes; every granted wish is appended to a persistent wish log.

### Ki Arena
- 10-second tap challenge on a canvas-free DOM arena.
- Combo multiplier (x1–xN) with a 700 ms combo window.
- Best score persisted in `localStorage`.

### Power Analytics
- Total / average / strongest tiles.
- Horizontal bar chart drawn on canvas, DPR-aware, themed.

### Global
- 4 themes: Ki Orange, Namek Green, Super Blue, Light.
- WebAudio sound effects with a mute toggle (no audio files needed).
- Starfield + rising ki-particle canvas background, pauses when tab is hidden.
- Toast notifications, preloader, scroll-spy navigation, mobile hamburger nav.
- Keyboard accessible: focus styles, `Escape` closes the modal, ARIA labels throughout.
- Full `prefers-reduced-motion` support.

## Usage

Double-click `index.html`, or serve the folder:

```
python -m http.server 8000
# then open http://localhost:8000
```

## Data model

Fighters live in the `FIGHTERS` array in `script.js`:

```js
{
  id: 'goku',
  name: 'Goku',
  race: 'Saiyan',
  base: 9000,
  color: '#ff7a18',
  forms: [['Base', 1], ['Super Saiyan', 1.6], ['Super Saiyan Blue', 3.1], ['Ultra Instinct', 5]]
}
```

Effective power = `base * formMultiplier`. Add a fighter by appending one object — the roster, battle selects, chart and hero counters all pick it up automatically.

## Local storage keys

| Key | Contents |
| --- | --- |
| `db.balls` | Array of 7 booleans. |
| `db.wishes` | Last 12 granted wishes. |
| `db.kiBest` | Best ki score. |
| `db.theme` | Selected theme name. |
| `db.sound` | Sound on/off. |

---

Fan-made demo project. Dragon Ball is a trademark of its respective owners.
