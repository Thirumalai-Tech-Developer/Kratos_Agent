---
name: frontend-testing-debugging
description: Diagnose rendered frontend issues and inspect interaction, responsive layout, browser errors, and accessibility evidence.
tags: frontend, browser, ui, debug, visual, testing
---

# Review a rendered frontend

Use when the user requests frontend debugging, visual QA, or validation of an interaction.

1. Identify the target route and the user interaction that should work. Inspect project scripts and current browser state before starting a server.
2. Reproduce the issue and capture the relevant state, console output, or screenshot when available.
3. Trace the UI state to its source: component, event handler, request, route, and data. Make the smallest useful fix.
4. Inspect desktop and narrow-screen behavior, keyboard access, labels, focus, and loading/error states relevant to the change.
5. Use the available browser or project verification tools only as authorized. Describe the evidence and environment; do not say a full browser suite passed when only a screenshot was inspected.
