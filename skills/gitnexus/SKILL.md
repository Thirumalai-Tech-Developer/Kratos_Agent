---
name: gitnexus
description: Use GitNexus repository graphs to trace symbols, call paths, and change impact before editing unfamiliar or cross-cutting code.
tags: gitnexus, codebase, graph, symbols, impact, architecture
---

# Explore with GitNexus

Use for unfamiliar repositories, broad refactors, or changes where callers and dependencies are hard to follow.

1. Check that the GitNexus MCP server is connected and the index belongs to the active workspace and current revision.
2. Search for the relevant symbol or execution flow. Before editing a shared symbol, inspect its callers and downstream dependencies with impact analysis.
3. Read source files to confirm graph results and understand behavior. A graph is navigation evidence, not proof that a change is correct.
4. If the index is missing or stale, report that state. Re-index only the active workspace and preserve its instruction files.
5. After edits, review the source diff and use the graph again when the affected call graph materially changed.

Use GitNexus tools only when Kratos exposes them in the current tool catalog. Do not run analysis on a different repository or transmit project source to a hosted service.
