# Web provider integration status

Updated 2026-10-05. This records observed behavior, not a guarantee that a browser session or a free quota will remain valid. No cookie, token, or session identifier is stored here.

## Latest live verification — 2026-10-05

Studio is running from the integration checkout with `--dev`. Its previous development cache returned HTML 404 responses for `/v1/chat/completions` before any provider execution. A fresh, separate `.build/kratos-dev` cache restored the JSON inference route; the launcher now uses that development directory by default and preserves an explicit `NEXT_DIST_DIR` override. The production standalone directory remains `.build/next/standalone`.

Each result below comes from one short arithmetic request to the explicitly named consumer model. The diagnostic timeout was 35–40 seconds. No paid API fallback or account rotation was used.

| Provider and model | Observed result | Interpretation |
| --- | --- | --- |
| DeepSeek — `ds-web/deepseek-v4-pro` | HTTP 200, correct nonempty answer | Passed the live reply check |
| Perplexity — `pplx-web/pplx-auto` | HTTP 200, correct nonempty answer | Passed the live reply check |
| Gemini — `gemini-web/gemini-3.7-flash` | First request: HTTP 200, nonempty answer, exact answer check failed; follow-up: HTTP 400 `bad_request` | Not verified as reliable inference |
| Qwen — `qwb/qwen3.7-plus` | Diagnostic timeout | No answer verified within 40 seconds |
| Dola — `db/dola-speed` | HTTP 429 | Upstream rate limit remains active |
| Z.ai — `zw/x-preview-l` | Diagnostic timeout | No answer verified within 40 seconds |
| Kimi — `kimi-web/k3` | HTTP 401, `invalid_api_key` | Stored session rejected |
| Claude — `cw/claude-fable-5` | HTTP 403 | Stored session or upstream access rejected |
| Grok — `gw/fast` | Diagnostic timeout | No answer verified within 35 seconds |
| Meta AI — `ms-web/muse-spark` | Diagnostic timeout | No answer verified within 35 seconds |

These results supersede the historical observations below. A configured connection or synchronized cookie does not prove successful inference. Other imported providers have not passed a fresh live inference check in this run. Consumer sessions still require normal sign-in or human verification when the provider requests it, and automatic synchronization preserves quotas, cooldowns and bans.

The agent now validates complete JSON tool schemas before execution, including nested types and constraints, and repairs stale bundled tool parameter types from their handler signatures. Optional MCP startup, initialization and requests share the configured deadline. Extension version 1.1.1 preserves model observations through normal conversation navigation and session renewal, while observed account changes and explicit sign-out invalidate them. Reload an already installed unpacked extension once to activate the update.

After restarting the idle agent, its authenticated health endpoint returned `status: ok` and `busy: false`. GitDiagram, computer-use, OpenPets and Context7 connected. GitNexus reported `TimeoutError` during dependency startup and Composio reported `ValueError`; these optional failures did not prevent the agent from serving requests.

## Historical production verification — 2026-10-02

The webpack production gateway build completed successfully. `kratos-studio run --cli --workspace .` reached the interactive prompt with `ds-web/deepseek-v4-pro`. On that rebuilt gateway, DeepSeek and Claude each returned a correct nonempty arithmetic answer. Meta AI timed out within 40 seconds, and Grok returned HTTP 403. The test CLI was then exited normally.

## Implemented

- Browser session imports normalize provider cookies and tokens, reject expired or unrelated cookies, preserve required companion values, and store connection credentials in the local encrypted gateway database.
- Runtime connection selection passes imported cookie headers to executors that read `apiKey`. Token-based web providers receive their named bearer token in the expected connection field.
- Meta AI JSON imports retain the separate `ecto1:` websocket authorization. Grok JSON imports retain the browser user agent, and its client hint headers match that agent.
- Qwen has a dedicated signed-in browser adapter. Browser chat rotation opens a new conversation after ten completed Q&A and carries a bounded summary forward.
- Dola and Copilot M365 treat empty upstream responses as errors. Qwen browser waits have a bounded timeout and cancellable response reads.
- Qwen clicks the current Send button and captures its terminal answer event without waiting for an open SSE connection to close. Signed-out and age-verification states are explicit errors.
- Dola non-streaming replies finish at `SSE_REPLY_END` and release their reader. HTTP 429 is preserved with `Retry-After` when supplied; rate limits do not trigger a new conversation.

The 2026-10-02 Qwen/Dola source changes passed 51 focused tests, core type checking, and scoped ESLint. Live source checks found Qwen's imported session signed out (HTTP 401); sending on the consumer page displayed an age-confirmation dialog. Dola returned HTTP 429. These are account/provider blockers, so neither check establishes working inference. The changed sources still require a production rebuild before Studio uses them. The scope is free consumer web access; these changes do not add a paid API fallback.

## Historical live observations — 2026-10-02

| Provider | Last observed result | Current status |
| --- | --- | --- |
| Qwen browser | Latest source check returns HTTP 401; provider UI displays Log in and age confirmation | Send and stream-capture fixes tested; refresh the signed-in session and complete any required age confirmation before a live answer can be verified |
| DeepSeek web | Returned a nonempty correct answer on the rebuilt gateway | Working in the latest live check |
| Claude web | Returned a nonempty correct answer on the rebuilt gateway | Working in the latest live check |
| Kimi web | Returned a nonempty correct answer earlier; latest credential health check says session expired | Needs a fresh signed-in session |
| Dola web | Latest source check returns HTTP 429 | Stream-completion fixes tested; retry after the provider allowance recovers |
| Grok web | HTTP 403 on the rebuilt gateway | Browser clearance or upstream challenge; imported user agent handling is fixed, but this stored session is still rejected |
| Perplexity web | HTTP 401 | Stored session was rejected upstream |
| Gemini web | HTTP 502 | Upstream protocol or session needs further diagnosis |
| Z.ai web | Chat is created, then Z.ai displays a security verification modal before issuing its completion request | Adapter now detects the modal and returns a clear verification-required error; a live answer remains blocked until a human completes Z.ai's challenge in the provider session |
| Meta AI web | Timed out within 40 seconds on the rebuilt gateway | Separate websocket token import fixed; live inference remains unverified |
| Copilot M365 web | HTTP 200 with `(empty response)` before the fix | Now raises an explicit upstream error; live recheck pending |
| T3 web | Catalog model returned HTTP 400 | Model mapping needs a current live check |

Other imported accounts include LMArena, HuggingChat, Poe, v0, ZenMux Free, and Notion. Their presence in the encrypted connection store does not establish that their inference endpoint works. Public free connections also depend on upstream quota, model availability, and verification. Previously observed failures included OpenCode 403 insufficient quota, LLM7 400 model unavailable, DuckDuckGo 418 upstream verification, and UncloseAI 502.

## Verification gate

After a standalone gateway rebuild, start Studio from this worktree and test a short request through each configured model. Record whether the answer is nonempty and correct, or whether the upstream reports an explicit error; do not treat a successful login or HTTP 200 alone as working inference. Development checks above exercise current source and do not establish that an older production build includes these changes. Keep provider rate limits and site terms intact.
