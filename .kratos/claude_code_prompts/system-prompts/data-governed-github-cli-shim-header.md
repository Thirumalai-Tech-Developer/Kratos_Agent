<!--
name: "Data: Governed GitHub CLI shim header"
description: "Header comments for the per-session governed GitHub CLI shim that routes github.com gh traffic through the agent proxy while preserving customer-token and GitHub Enterprise traffic"
ccVersion: "2.1.202"
-->
#!/bin/sh
# claude agent-proxy governed-git gh shim (auto-generated; per-session).
# Routes gh-to-github.com through the session relay ONLY when the
# invocation carries no customer credential. GHE targets (GH_HOST,
# --hostname, a -R/--repo/GH_REPO naming a non-github.com host, or a
# non-github.com origin remote in the cwd checkout) and
# real-customer-token invocations exec directly on the
# customer's own egress, so customer credentials never transit the
# relay tunnel and gh-to-GHE keeps working.
# Real customer tokens decide alone, checked first (costs nothing):
# gh sends GH_TOKEN/GITHUB_TOKEN proactively, and the GHE-scoped
# enterprise pair means gh may target a GHE host in ways the checks
