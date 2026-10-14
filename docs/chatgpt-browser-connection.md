# Browser cookie connections in Kratos

The Kratos extension collects credentials from your existing signed-in Chrome or
Edge profile. Sign in normally, including Google sign-in. Extension version 1.6
never opens or redirects tabs, types prompts, selects website models, or clicks
Send. The extension has no debugger permission.

## Install or update

Run `uv run --no-sync kratos-connect browser-setup` from the Kratos checkout.
Load the printed directory in chrome://extensions or edge://extensions. If it is
already installed, reload **Kratos browser connections**. Refresh an already open
provider tab once so its read-only storage collector can load.

The generated directory is outside the workspace, usually
`%USERPROFILE%\.kratos\auth\browser-extension`. It contains a private loopback
receiver token. Do not share or commit that directory.

Choose a website in the popup and click **Collect session cookies**. Choose an
available model and thinking level, then **Use model**. Keep Studio running; it
starts the local credential receiver. Restart Studio after Python updates and
reload the extension after extension updates.

## How credentials and requests flow

1. The extension reads only the selected provider's cookies and origin storage.
   It exports a Playwright-compatible `{cookies, origins}` object. For providers
   storing tokens in localStorage, keep their signed-in website open during
   collection. Cookie-only collection can work with the website tab closed.
2. Kratos validates cookie domains, expiry and origin data, then stores the session
   encrypted with Windows DPAPI outside the workspace. Cookies are excluded from
   status responses, logs and training archives.
3. The extension observes cookie changes and checks bound sessions every minute.
   Refresh updates the connected browser cookie store; it cannot restore a
   disconnected account. Reconnect explicitly after switching website accounts.
4. Model requests use the saved session directly through OmniRoute. They do not
   wait for extension polling or require an open ordinary-browser chat tab.

For ChatGPT, `chatgpt-web.ts` supplies the Clean Room executor contract and
storage-state validation. Kratos supplies an isolated executor browser and uses
OmniRoute's shared composer helper from the Codex adapter to submit the request.
`chatgptWebTools.ts` converts supported text tool responses; Kratos then validates
names and argument schemas before any local tool runs.

`chatgpt-web-codex.ts` remains the separate native Codex Responses executor. Its
native-client and local-tool tunnel requirements still apply. A normal agent chat
is handled by the Clean Room executor; a cookie does not bypass those checks.

The executor browser is separate from your ordinary signed-in browser. It is
initialized from exported cookies. ChatGPT task turns reuse one private worker
and one executor tab for the same Kratos conversation, including tool results.
Each account and conversation has its own scoped page; new tasks never inherit
another user's chat. The browser closes on Stop, worker expiry, or shutdown.
No automated Google login is required. Website changes,
verification challenges and provider limits can still interrupt this route.

## Supported website routes

| Website | Executor path |
| --- | --- |
| ChatGPT | Clean Room executor with saved storage state; text turns |
| Qwen | OmniRoute Qwen browser executor |
| Dola | OmniRoute Doubao web executor |
| Gemini | OmniRoute Gemini web executor |
| DeepSeek | OmniRoute DeepSeek web executor |
| Kimi, Grok, Claude, Perplexity, Z.ai | Corresponding OmniRoute cookie executor |
| Meta AI | Upstream executor also requires an authorization header; cookies alone are insufficient |
| Groq | No cookie executor in this checkout; use the existing API route |

Registry entries describe available routes, not verified account access or quota.
Thinking controls appear only when declared by the executor. This text bridge
neither advertises image support nor claims a verified 256K context limit.

## Connection status and conversations

Green **Connected** means credentials were collected and validated, not that a
model reply has been tested. **Session expired** and connection errors appear in
red. Sign in normally on the website to refresh expired cookies. **Check login**
refreshes the live account/catalog; **Disconnect** removes Kratos credentials and
leaves your website login alone.

The model picker combines normal OmniRoute routes and cached browser routes.
Opening it does not start a browser. Explicit refresh checks fresh metadata;
a failed browser connection does not hide normal gateway models.

Where supported, Kratos stores the actual remote conversation ID and completed
assistant message ID, scoped to account, model and Kratos session. Follow-up turns
send only new messages and tool results. System instructions are sent on the first
turn, or when a new conversation is required after context changes or compaction.
A lost remote conversation is reported instead of inventing a continuation ID.

Requests from different accounts are isolated; calls sharing an account are
serialized. Stop cancels the owned request worker and its browser children.
An uncertain submission is not blindly resent, to avoid duplicate website turns.

Substantive results render in the same Kratos chat as structured Markdown: headings,
steps, tables, code, and Mermaid architecture diagrams. The internal JSON tool
protocol is validated before rendering; execution wrappers stay out of the final
answer. Speech summaries are audio metadata and do not create a second visible
reply. Diagram rendering uses strict Mermaid settings and sanitized SVG, with
a readable source fallback if a diagram is incomplete or invalid.

## Checks

Focused tests cover credential validation, encrypted persistence, cookie rotation,
logout, account binding, rejecting extension model commands, tool-call validation,
real conversation cursors and matching newly completed assistant replies.
A successful live reply must be verified separately for each provider/account.
