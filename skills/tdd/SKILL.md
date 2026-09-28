---
name: tdd
description: Apply test-driven development to a feature or bug fix when the user requests a test-first workflow.
tags: testing, tdd, engineering, implementation, bugfix
---

# Test-driven development

Use when the user explicitly asks for TDD, test-first implementation, or a red-green workflow.

1. Identify the public behavior and the narrowest stable interface that can observe it.
2. State the behavior to test and inspect existing test conventions before editing.
3. Add one test for one user-visible behavior, run it, and confirm it fails for the expected reason.
4. Implement the smallest change that makes that behavior pass. Repeat for the next behavior only after the current one is green.
5. Review test quality: assert outcomes rather than implementation details; mock only external boundaries; avoid tests that duplicate production logic.

Do not add or run tests when this workflow was not requested. If a requested test cannot run, report the concrete blocker and leave its result unclaimed.
