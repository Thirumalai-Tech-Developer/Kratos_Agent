---
name: claude-debugging
description: Systematic hypothesis-driven debugging methodology for isolating root causes, reproducing defects, and verifying fixes.
tags: debug, troubleshooting, root-cause, testing, diagnostics
source_url: https://github.com/Piebald-AI/claude-code-system-prompts
---

# Systematic Hypothesis-Driven Debugging

You are diagnosing and fixing a defect in the codebase using scientific, hypothesis-driven debugging rather than guess-and-check.

## 4-Step Debugging Protocol

### Step 1: Reproduce & Observe
1. **Understand Symptoms**: What is the actual behavior vs expected behavior?
2. **Collect Evidence**: Examine exact error logs, stack traces, return codes, and system state.
3. **Isolate Minimal Test Case**: Create a small script or unit test to reliably reproduce the failure on demand.

### Step 2: Formulate & Test Hypotheses
1. Trace the execution path backwards from the point of failure to the root input.
2. List 2-3 plausible root causes.
3. Add minimal targeted log assertions or check variable states along the code path to invalidate hypotheses one by one until the exact defect is pinpointed.

### Step 3: Implement Minimal Targeted Fix
1. Modify only the necessary lines to address the root cause.
2. Avoid shotgun debugging or wrapping entire blocks in silent `try/except` handlers that mask underlying logic bugs.
3. Ensure all edge cases and boundary conditions are handled.

### Step 4: Verify & Prevent Regressions
1. Re-run the reproduction test and observe successful execution.
2. Run full project test suite or build command (`npm run build`, `pytest`, etc.).
3. Verify that adjacent functionality remains unaffected.
