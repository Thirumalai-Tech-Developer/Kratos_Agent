---
name: claude-design-sync
description: Design system synchronization, modern visual hierarchy, responsive layouts, data visualization, and UI component styling.
tags: design, frontend, ui, ux, tailwind, css, dataviz, components
source_url: https://github.com/Piebald-AI/claude-code-system-prompts
---

# UI/UX & Design System Excellence

You are building modern, state-of-the-art web interfaces and visual components following high-end design principles.

## Core Visual Principles

### 1. Curated Color Palette & Tokens
- Avoid generic plain RGB colors.
- Use cohesive dark/light mode surface palettes with rich contrast:
  - Deep surfaces (`#0D1117`, `#161B22`, `#21262D`)
  - Accent colors with harmonic contrast (`#E63946`, `#58A6FF`, `#3FB950`, `#D29922`)
  - Subtle borders (`#30363D`) and soft glassmorphism backdrop blurs.

### 2. Typography & Spatial Rhythm
- Pair modern sans-serif fonts (e.g., Inter, Outfit, Plus Jakarta Sans, Roboto) with crisp monospace fonts (JetBrains Mono, Fira Code).
- Establish clear type scales: `Hero > H1 > H2 > Body > Caption`.
- Maintain consistent 4px / 8px spacing scale (`p-2`, `p-4`, `p-6`, `gap-4`).

### 3. Micro-Interactions & Motion
- Subtle hover transitions (`transition-all duration-200 ease-in-out`).
- Smooth button active states, focus rings with accessible outline offsets, and loading skeletons.
- Interactive animations with Framer Motion or smooth CSS transitions.

### 4. Data Visualization & Dashboard Polish
- Clear axis labelling, legend positioning, and intuitive tooltips on hover.
- High contrast categorical palettes that are accessible and colorblind-safe.
- Stat tiles with delta indicators (`+12% vs last week`), mini trend sparklines, and clean metric cards.
