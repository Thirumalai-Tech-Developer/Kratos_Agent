---
name: zoom-out
description: Step back from a local code issue to identify system boundaries, recurring causes, and high-impact architecture choices.
tags: architecture, codebase, systems, design, review
---

# Zoom out

Use when the user asks for a broad architecture review, a system-level diagnosis, or a higher-level view of a local change.

1. Restate the system outcome the user cares about and inspect the relevant project map, entry points, dependencies, and runtime boundaries.
2. Trace the current behavior across components. Use repository graph tools when available; otherwise follow imports, callers, and data flow in source.
3. Separate root causes from symptoms and record concrete evidence for each conclusion.
4. Compare a few options by impact, migration effort, reversibility, and risk. Recommend the smallest change that addresses the underlying issue.
5. Keep speculative opportunities separate from necessary fixes. Do not turn a focused request into an unsolicited rewrite.
