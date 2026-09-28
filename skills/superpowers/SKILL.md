---
name: superpowers
description: Use a dependable planning, execution, review, and verification workflow for multi-step engineering tasks.
tags: planning, execution, review, verification, engineering, coding
---

# Engineering workflow

Use this workflow for multi-step code changes, integrations, and substantial debugging. Keep small, obvious edits lightweight.

1. **Understand:** Inspect the workspace, active instructions, relevant files, and current Git changes. Separate facts from assumptions. Ask only for information that blocks a safe, correct result.
2. **Plan:** Break multi-step work into observable outcomes with `todo_write`. Keep the plan proportional to the task. If the user explicitly asks to approve a plan first, stop at that boundary.
3. **Execute:** Make the smallest coherent changes that meet the request. Follow existing architecture, reuse existing tools, and update task progress as work advances.
4. **Review:** Inspect the resulting diff and affected call paths. Look for regressions, security issues, stale docs, and changes outside the requested scope.
5. **Verify:** Gather direct evidence for the requested outcome. Run automated tests only when the user asks for tests or verification. State exactly what was and was not checked; never infer success from an action being started.

Use `read_skill` for a relevant specialist workflow such as `tdd`, `diagnose`, `security-audit`, `build-web-apps`, or `gitnexus`. These workflows do not replace Kratos's permission checks or the user's instructions. Keep reasoning on the configured Kratos model.
