---
name: to-prd
description: Turn an idea or request into a concise product requirements document with outcomes, users, scope, constraints, and acceptance criteria.
tags: product, requirements, planning, prd, specification
---

# Write a PRD

Use when the user asks for a PRD, product brief, or requirements document.

1. Preserve the user's stated problem, audience, outcome, and constraints. Mark assumptions instead of presenting them as facts.
2. Inspect the existing project when available; note relevant architecture or behavior that affects the requirements.
3. Write only the sections the request needs: problem, users, goals, non-goals, user-visible behavior, requirements, constraints, risks, and observable acceptance criteria.
4. Keep requirements testable and distinguish required behavior from proposed implementation.
5. Save a file only when requested or when the task already calls for a project artifact. Otherwise return the PRD in the conversation.

Do not invent business rules or add scope to make the document look complete. This Kratos skill retains the requested `to-prd` name; the current upstream Matt Pocock skill uses `to-spec`.
