# GUI Automation Architecture

## 1. Backends
Kratos incorporates multiple pluggable GUI backends:
* `WindowsUIABackend`: Native COM interface into `UIAutomationCore.dll` with pattern support (`Invoke`, `Value`, `Toggle`, `SelectionItem`, `Scroll`).
* `LinuxATSPIBackend`: AT-SPI accessible tree discovery for GNOME/KDE (X11 & Wayland).
* `PlaywrightBackend`: Semantic DOM extraction and role-based interaction.
* `CoordinateBackend`: Low-level coordinate fallback.

## 2. Confidence Scoring & Ambiguity Detection
Target matching uses weighted scoring:
* Exact semantic match: 1.00
* Unique accessibility match: 0.98
* DOM role/name match: 0.98
* Application adapter: 0.95
* Keyboard target: 0.92
* Vision grounding: 0.80
* Coordinate fallback: 0.60

If two or more candidates have close confidence (>0.80 and within 0.05 of each other), Kratos flags the target as ambiguous and halts rather than blindly clicking.

## 3. Stale Element Protection
Every UI element reference contains an incrementing `generation` number. When the environment state changes, the generation counter advances, preventing actions on stale references.
