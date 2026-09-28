---
name: security-audit
description: Review code for exploitable security weaknesses with scoped threat analysis, traceable evidence, and confidence-rated findings.
tags: security, audit, vulnerability, threat-model, review
---

# Security audit

Use for an explicitly requested security review or when a change touches authentication, authorization, untrusted input, secrets, network exposure, persistence, or privileged actions.

1. **Set scope:** Identify the target paths, entry points, trust boundaries, sensitive assets, and attacker-controlled inputs. State what is outside the review.
2. **Trace behavior:** Follow input through validation, authorization, processing, storage, and output. Check dependency and configuration boundaries where they affect the path.
3. **Verify candidates:** For every suspected issue, cite the exact code path and explain a plausible attacker action and concrete impact. Reject style concerns and unproven possibilities.
4. **Report findings first:** Give severity, confidence, affected location, preconditions, and a concise remediation. Separate confirmed findings from questions or hardening suggestions.
5. **Check the fix:** Re-read the changed path and its callers. Run scanners or tests only when available and requested; name tools that were not run.

Never print credential values, exploit a live third-party target, or claim a clean bill of health from a partial review. Follow the relevant project policy and permission checks. Trail of Bits tooling can be selected when its applicable MCP tools or local utilities are actually available.
