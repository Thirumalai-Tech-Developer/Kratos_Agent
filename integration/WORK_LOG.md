# Kratos Studio integration status

Implementation is in progress on `codex/kratos-omniroute`. This is not a completed parity report.

## Preserved inputs

- Original Kratos master and modified OmniRoute release/v3.8.51 checkouts remain separate.
- 13,272 OmniRoute source files imported; source hashes and local changes recorded in omniroute-source.json.
- Complete imported feature surfaces remain under services/omniroute.

## Implemented so far

- Shared launcher, service readiness, owned-process shutdown and bounded restart.
- Unified Next navigation and embedded Kratos workspace with authenticated local proxy.
- Kratos memory opt-out header, scoped session/request correlation, interrupted-stream rejection, no partial tool replay.
- Voice command execution and SSE completion; shared session owner and session mutation guards.
- Responses web-search fallback SSE lifecycle adapter.
- Email (Resend), PagerDuty Events v2, Teams Workflows adapters, configuration forms and delivery history.
- Connection TPM/TPD reservations and actual-usage reconciliation, persisted in migration 172. UTC minute/day windows. Interrupted/unknown usage retains its estimate until expiry.
- Isolated managed gateway data and persistent generated encryption/auth secrets.
- Kratos MCP server management API and dashboard page: add/import, update, enable/disable, remove, status, and redacted configuration overview. OmniRoute's existing native MCP and plugin pages remain available.
- Offline OmniRoute data import with consistent SQLite snapshot, source encryption key preservation, and a retained rollback directory; documented in STUDIO_OPERATIONS.md.

## Recorded checks, 2026-09-29

- Python SDK/web integration: 28 passed.
- Webhook adapters and existing regression/URL tests: 43 passed; outbound delivery mocked.
- Token reservations, local proxy and Responses stream: 13 passed.
- Core TypeScript check: passed after webhook and token changes.
- Kratos frontend production build: passed.
- OmniRoute production build and standalone assembly: final build passed after the browser-origin, service-worker, and MCP custom-port fixes.
- Native better-sqlite3 installed from npm and verified with an in-memory SQL query.
- Kratos MCP management tests: 4 passed; framework/MCP/web integration run: 22 passed.
- Data import and launcher supervisor focused tests: 5 passed.
- Python 3.12 full suite: 434 passed, 1 failed, 1 skipped; the Headroom failure was fixed and its 14 focused tests passed. SDK/web regression tests passed separately.
- Browser login and unified sidebar/page: passed. Embedded workspace and MCP management page rendered in the rebuilt production server; the MCP example used the active custom port.
- Existing OmniRoute store import into an isolated copy: passed (135 SQLite tables, quick_check ok, source encryption key preserved). Rollback and restore rehearsal passed without changing the original store.
- The same import was applied to this worktree's default Studio data directory. The former directory is preserved as a rollback sibling; the imported database passed quick_check and retained the source encryption key.
- The imported default store booted successfully on ports 20128/7860 with the final production bundle. The test process was stopped afterward.
- Silent SSE upstream cancellation: local HTTP integration test passed; 10 gateway stream contract tests passed.
- Dashboard TypeScript check reports existing OmniRoute errors in JSX namespace and test files; the production build does not enforce that check. Core TypeScript check passed.
- Broad OmniRoute unit suite stopped after 729 passing markers and 5 failures: three Adobe Firefly route tests plus their file-level result, and a catalog event-loop timing test under concurrent build load. The Adobe route suite unexpectedly opened a browser-backed provider session, so further broad runs require a strict offline boundary.
- Source ledger regenerated after final edits: 13,272 imported files and zero missing.

## Follow-up implementation, 2026-09-30

- Added `kratos mcp` and `kratos-studio mcp` commands for add/configure/import/list/check/enable/disable/remove. These dispatch without importing the agent runtime. Configuration changes require Reconnect or restart before the running agent adopts them.
- Added a remote MCP URL form to the Kratos MCP page. Existing connection names require the advanced update form; CLI replacement requires `--replace`.
- Focused CLI and MCP management tests: 12 passed. Live Context7 CLI connection check: connected, 2 tools. Authenticated MCP page returned 200 and rendered the new URL form.
- Changed optional OmniRoute background service bootstrapping to run without holding HTTP readiness. Source build compiled and packaged successfully; a separate user setup run subsequently produced an incomplete standalone tree. Restored its launcher and native/runtime dependencies without recompiling. An isolated first-start probe timed out after 60 seconds; a repeat using that temporary database reached health and login-page HTTP 200 within the 120-second deadline. The existing development server remains running. New MCP UI changes are currently served there and need a new production build to be included in the standalone bundle.
- Studio doctor now requires the standalone launcher wrapper as well as the Next build ID before reporting the gateway as built.
- Reset the imported Studio database's login password using the bundled reset command. Verified the stored bcrypt hash and a successful `/api/auth/login` response. A gateway restart clears its in-memory failed-login guard.
- Interactive MCP OAuth login and general plugin/skill installation are still pending; this addition provides configuration and connection management only.

## Remaining acceptance work

- Full feature-ledger validation (included source is not verified functionality).
- Plugin/skill management compatibility and agent operations integration beyond existing native OmniRoute pages.
- End-to-end model/combo capabilities and context/compression/CCR tests.
- Persisted task correlation and recovery checks beyond stream cancellation.
- Distributable packaging independent of the integration checkout.
- Complete unit/Vitest suites, full feature-ledger runtime validation, and launcher recovery tests.
- Live provider/webhook checks require configured services; no external test messages have been sent.

## Windows CLI failure fixes, 2026-09-30

- Diagnosed the pasted Tokyo planning run: absolute scratch paths were silently rewritten by clean_file_path, so the file writer and verifier disagreed. Paths now retain their requested destination, including nested scratch folders and leading letters r/f/b.
- Get-Date -Format no longer triggers the destructive-action approval category; disk formatting remains blocked.
- Explicit PowerShell -Command wrappers execute as encoded payloads without a parent PowerShell expanding variables. Inline node/python scripts with backslash quote escapes receive an actionable parsing error.
- Headroom uses deterministic compression with system instructions protected. Lazy tokenizer ImportError falls back once to estimated token counts; compression statistics use tokens_before. No transformers installation or model download is required in the base environment.
- Validation: 44 focused regression and existing tests passed, including actual PowerShell execution and the ds-web/deepseek-v4-pro compression path. Restart the CLI to load these changes.
- The earlier itinerary remains unverified: fixing runtime errors does not establish the accuracy of rates or schedules produced after its research failed.

## Integrated Studio CLI, 2026-09-30

- Added kratos-studio run --cli, kratos-studio cli, and gateway-only setup --cli. The original kratos --cli dispatches to the same launcher with workspace, port, and development-mode options. Help no longer initializes the runtime.
- Shared environment preparation loads the selected workspace settings before application defaults, supplies matching chat/model endpoints, and uses the same private gateway store in web/CLI modes. A persistent private deployment inference key authenticates newly launched gateways; explicit keys remain supported. Existing older gateways require an accepted key or a restart through this launcher.
- CLI mode reuses a healthy selected gateway or owns one until terminal exit. It does not start a second web agent or open the browser. Cold model-route timeouts retry within the startup deadline; authentication errors fail promptly.
- Interactive MCP commands support add/configure/check/enable/disable/remove as well as import/status/reload. Saved mutations apply to the CLI runtime. Shutdown handles a background event-loop closure race.
- Validation: 74 launcher/MCP/Windows/compression/shell tests passed. An additional focused run covering the launcher and live shutdown/components passed 53 tests (overlapping earlier coverage; existing mss deprecation warnings). An isolated real development gateway accepted the private key and listed ds-web/deepseek-v4-pro; the real CLI opened, handled help and disabled MCP add/status/remove, and exited with status 0 and no closed-loop error. External default MCP servers were disabled for that final lifecycle probe. No chat-completion request was made in the probe.
- The existing port-20128 instance was left running. Temporary smoke process trees/data were cleaned up; the transcript remains in .kratos/studio/logs/cli-smoke.log.

## Research execution and completion fixes, 2026-09-30

- Normalize redundant arguments envelopes before schema validation and approval, while preserving schemas with a declared arguments parameter. Compare actual wrapped command values in the repeated-failure guard; missing command values no longer block unrelated corrected calls.
- Exception .message property reads no longer trigger external-communication approval. Message/send methods, POST commands, and existing consequential-action gates remain enforced.
- Remove final-answer completion overrides that resurrected failed plan tasks. File presence cannot bypass failed verification. Unfinished tasks receive bounded continuation prompts and unresolved failures remain failures in the final result.
- Add research instructions requiring date-specific price evidence, source URLs, explicit estimates, and complete or clearly partial budgets. Correct tokyo_trip_summary.md to identify undated hotel estimates, include both transfer allowances, and exclude unpriced return airfare/extras from the partial amount. Later raw flight results use October 13, correcting the initial date search. Official hotel access confirms five minutes on foot and no on-site parking.
- Validation: 47 targeted completion, verification, risk, tool normalization, and CLI regression tests passed; scoped git diff --check passed. Exact-date hotel availability and return fares remain unconfirmed. Restart the CLI to load runtime changes.

## Corrected retries and disposable research storage, 2026-09-30

- The new session exposed provider `_nonce` arguments reaching the shell handler and failed steps being bypassed. Strip undeclared provider bookkeeping, retain failed steps for up to two corrected recovery attempts, and persist the required recovery tool in saved plans. Explicit continue reopens failed attempt latches; report writing alone cannot recover a failed shell/research call.
- Each agent turn owns an OS temporary directory. Relative scratch file operations map there; terminal scratch scripts run there using an explicit process working directory. The runtime supplies the directory in model instructions and cleans it in finally on successful, failed, or interrupted exits. Scratch helpers and raw extracts do not count as workspace deliverables or complete research steps merely by being written/read.
- Removed the 12 known helper/extract files from the submitted session, preserving the final report and unrelated existing scratch files. Marked the newly regenerated report incomplete because its October 17 return/check-out may conflict with the final conference day and its hotel price cannot be attributed to a property.
- Regression coverage includes real Python execution of a scratch probe, reading its extraction, retaining the final artifact, automatic cleanup, bounded retries, and saved-plan recovery. Existing approval and completion gates remain covered.

## Prose prompt, model speech, and persistent recovery memory, 2026-10-01

- Replace numbered behavioral instructions with prose rules, and share the model speech rule with normal chat. Deliver one explicitly marked acknowledgement before tool execution, while keeping final speech separate. Failed completion gates override a model's spoken success claim.
- Implement Reflexion-inspired recovery memory in the runtime. Supported failures become fixed lessons only after a changed successful attempt on the same task/tool and completed-plan verification. Terminal recovery requires an explicit zero exit code and a matching executor. Resumed tasks require a real persisted failed-call receipt; arbitrary metadata alone cannot establish recovery.
- Save at most 50 sanitized lessons atomically in the selected workspace's .kratos/recovery_memory.json. Recall at most three relevant lessons on future agent requests, including after restart. No extra model calls or weight updates are used. Add CLI /lessons and /lessons clear for inspection and reset.
- Keep each tool result bound to its task at dispatch, including parallel reads. A successful call from the same wave cannot recover a failure first observed in that wave. Prevent duplicate next-task starts. Bind unpublished lessons to task objects so reusing an ID in another plan cannot publish stale evidence.
- Add store, restart, loop, and isolated CLI regressions, including failed verification, unrelated writes, poisoned storage, bounded recall, secrets exclusion, workspace separation, saved-task resume, and parallel result attribution. Update the older rendering test's registry fixture to provide the lookup method used by the scratch runtime.
- Validation: 134 focused memory, CLI, parallel execution/rendering, scratch, speech, completion, tool-schema, and permission-policy tests passed. One directory-symlink test was skipped because Windows symlink creation was unavailable. Scoped git diff --check passed. Provider responses were simulated for the recovery/speech checks; a live model task was not used as validation. Restart the running agent to load these changes.
