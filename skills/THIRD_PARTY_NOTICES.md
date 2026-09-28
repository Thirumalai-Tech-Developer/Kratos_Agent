# Third-party agent skills

## Vercel React Best Practices

- Source: <https://github.com/vercel-labs/agent-skills/tree/063bee94c3f4df8453406c830b0a7df0f2860278/skills/react-best-practices>
- Upstream revision: `063bee94c3f4df8453406c830b0a7df0f2860278`
- The skill's `SKILL.md` declares the MIT license. The upstream README also declares MIT; the selected revision does not contain a top-level license file.
- Upstream skill content is preserved in `vercel-react-best-practices/`.

## Vercel Web Design Guidelines

- Source: <https://github.com/vercel-labs/agent-skills/tree/063bee94c3f4df8453406c830b0a7df0f2860278/skills/web-design-guidelines>
- Upstream revision: `063bee94c3f4df8453406c830b0a7df0f2860278`
- The upstream README declares the repository MIT; the selected revision does not contain a top-level license file.
- The installation adapts the upstream `WebFetch` instruction to Kratos's existing `fetch_url` tool. Other skill content is preserved in `vercel-web-design-guidelines/`.

## Kratos-native workflow integrations

The workflow files added for this integration are authored for Kratos's `SKILL.md` loader and native MCP tools. Upstream skill files were not copied into this repository. These links identify the projects whose public workflows and capabilities informed the adapters:

- [Superpowers](https://github.com/obra/superpowers) — MIT.
- [Matt Pocock's Skills](https://github.com/mattpocock/skills) — MIT. Kratos keeps compatibility names for `to-prd` and `diagnose`; upstream currently uses `to-spec` and `diagnosing-bugs`, while `zoom-out` and `caveman` are no longer in its current catalog.
- [Trail of Bits Skills](https://github.com/trailofbits/skills) — CC BY-SA 4.0. No Trail of Bits skill source files are bundled here.
- [OpenAI Build Web Apps plugin](https://github.com/openai/plugins/tree/main/plugins/build-web-apps) — MIT. The Kratos adaptation uses Kratos's model and tool interfaces.
- [Context7](https://github.com/upstash/context7) — hosted MCP integration; no upstream package source is bundled.
- [Composio Connect](https://docs.composio.dev/docs/composio-connect) — hosted MCP integration; no upstream package source is bundled.
- [GitNexus](https://github.com/abhigyanpatwari/GitNexus) — the optional MCP integration downloads GitNexus `1.6.12` at runtime. The package is licensed under PolyForm Noncommercial 1.0.0; its source is not vendored here.
