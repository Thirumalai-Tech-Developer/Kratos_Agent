# Automatic session sync from your original Chrome

Studio starts a local receiver alongside its web or terminal interface. A Chrome
extension captures renewed cookies and declared storage tokens from your original
signed-in tabs every 30 seconds, after cookie changes and after page reloads.
It updates only its own connections and encrypts both credentials and companion
cookie metadata. No cookie values or tokens are logged or exported as files.

## One-time Chrome installation

Start Studio normally, or use the standalone command below. In your original
Chrome, open `chrome://extensions`, enable Developer mode, select **Load unpacked**,
and choose the generated folder:

```text
C:\Users\thiru\.codex\worktrees\kratos-omniroute\Kratos_Agent\.kratos\browser-sync\chrome-extension
```

Keep your signed-in provider tabs open. No second login or separate browser
profile is created. Clicking the extension icon triggers an immediate scan.
It retries automatically when Studio restarts. After updating extension files,
click Reload on its card in Chrome's extensions page.

For Meta AI, refresh its existing tab once after installing the extension so it
can observe the normal page's WebSocket companion credential. An expired login
or provider verification still requires the site's normal sign-in flow.

## Automatic start with Studio

Enable in the workspace `.env`:

```dotenv
KRATOS_BROWSER_SESSION_SYNC=true
KRATOS_BROWSER_SESSION_PROVIDERS=all
KRATOS_BROWSER_SESSION_SYNC_INTERVAL=30
```

These settings are enabled in this integration checkout's private `.env`. Restart
Studio using its normal command. The updated gateway must run to decode sealed
companion credentials. Use `--dev` to load new source without a production rebuild:

```powershell
uv run --no-sync kratos-studio run --dev --cli --workspace .
```

Standalone commands, from the Kratos checkout:

```powershell
uv run --no-sync kratos-studio browser-sync --workspace . --providers all
uv run --no-sync kratos-studio browser-sync --list
```

`all` currently selects 12 configured sites: Qwen, Dola/Doubao, Kimi, DeepSeek,
Claude, Gemini, Grok, Perplexity, Z.ai, Meta AI, Poe and Blackbox. This lists capture
support; it does not enable every model or a paid tier. See `--list` for provider IDs.
Meta AI's separate WebSocket credential is captured when its normal page opens the
authorized websocket. Missing companion credentials do not overwrite a saved session.

The default extension uses loopback port 20129 and a private random receiver token.
The generated extension contains this local token; keep `.kratos` private and out
of Git. It does not require DevTools or read Chrome's protected credential database.

For an existing browser explicitly configured for local Chrome DevTools access,
set `KRATOS_BROWSER_SESSION_CDP=http://127.0.0.1:9222`. Only loopback endpoints are
accepted. This does not read Chrome's protected credential database or make the Codex
browser extension expose an unavailable connection. CDP itself must already be enabled.

The watcher preserves rate limits, cooldowns, account bans and disabled connections.
It clears a specifically expired status only after credentials change and when the
connection isn't cooling down. It never substitutes accounts to evade restrictions,
sends test chats, switches paid plans, or solves provider challenges.

Logs: `.kratos/studio/logs/browser-sync.log`. Logs report credential capture rather
than successful inference. A saved session cannot establish that a site's models or
free quota are currently available; check inference separately through the gateway.

## Model discovery and workspace selection

Extension version 1.1.1 observes model choices in each provider's normal model
menu and successful same-origin `/api/models` responses. It does not send chats
to discover models. Choices are stored with the encrypted browser session; a
model-only change also triggers synchronization. Signing out clears an observed
catalog, while closing a menu preserves it. Paid or disabled choices are excluded
from executable discovery, and unknown protocol identifiers are retained only as
observations until the transport can route them.

Conversation path, query and fragment changes within the same provider origin
preserve the observed catalog. Renewed session, clearance and analytics cookies
also preserve it. Stable account cookie values and identity claims in already
declared storage tokens detect account changes without treating each token
renewal as a new account. An observed account change, provider origin change or
explicit sign-out clears the catalog. Opaque credentials alone cannot identify
an account change, so discovery is not an authorization or session-validity check.

Click the **Model** badge in the full-screen workspace to search the gateway
catalog and select the next request's model. The server validates the choice and
persists it in `.kratos/model-selection.json`. Switching is blocked during an
active request. Labels show 📝 Text, 👁️ Vision, or 📝 Text + 👁️ Vision from
explicit transport metadata; missing metadata is reported as unknown.

After upgrading an already loaded unpacked extension, click **Reload** on its
Chrome extension card once. Refresh signed-in provider tabs once to observe their
normal startup model response, or open their model menu. Later cookie and model
changes synchronize automatically.
