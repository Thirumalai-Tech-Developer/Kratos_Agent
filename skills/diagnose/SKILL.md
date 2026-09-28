---
name: diagnose
description: Investigate a specific bug or performance regression by reproducing it, testing ranked hypotheses, and proving the fix.
tags: diagnose, debugging, bug, regression, performance, investigate
---

# Diagnose a failure

Use for a concrete report such as an error, wrong result, broken interaction, or measurable slowdown.

1. Capture the exact symptom and expected behavior. Inspect logs, recent changes, relevant code, and the environment without exposing secrets.
2. Reproduce the failure using the least disruptive path. If it cannot be reproduced, identify what evidence is missing.
3. Write a short ranked list of hypotheses and choose the cheapest observation that can distinguish them.
4. Trace the failing value or control path to its cause. Do not treat a correlation or a plausible code smell as proof.
5. Make a targeted fix, inspect nearby paths for the same cause, and gather evidence that the original symptom is resolved.

Do not mask errors, broaden the rewrite, or claim a root cause without evidence. Run regression tests only when the user asks for testing or verification. This Kratos skill retains the requested `diagnose` name; upstream currently calls it `diagnosing-bugs`.
