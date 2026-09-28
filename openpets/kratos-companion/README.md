# Kratos Companion for OpenPets

This local OpenPets plugin makes the pet climb screen edges, take occasional
bounded walks, and play a short reaction. OpenPets pauses its tick callback
while the pet is hidden or dragged, and its host enforces work-area movement bounds. The right-click
“Pause Kratos roaming” command pauses the behavior.

## Install locally

1. Install and open the OpenPets desktop app.
2. Open **Plugins**, enable **Developer Mode**, then choose **Load unpacked
   plugin folder** (OpenPets 3.x desktop).
3. Select this `kratos-companion` folder and approve its four requested
   capabilities: movement, reactions, curated host events, and a pet-menu
   command.
4. Leave the plugin enabled. Use the pet's right-click menu to pause or resume
   roaming.

Kratos also configures the pinned `@open-pets/mcp@4.0.0` server. Its `openpets`
tools report status, set reactions, and display a short bubble for each
explicitly marked `[[speak]]...[[/speak]]` phrase. The bubble and Gemini speech
receive the same sanitized phrase. Ordinary answer text stays on screen.

The desktop application itself must be installed and running; Kratos does not
install it. Set `KRATOS_OPENPETS_MCP=false` to disable the MCP server.
