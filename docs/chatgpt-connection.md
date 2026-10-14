# Connect Kratos to ChatGPT

Run these commands from the OmniRoute worktree:

```powershell
uv run kratos-connect login --provider chatgpt
uv run kratos-connect models --provider chatgpt
uv run kratos-connect select --provider chatgpt --account ACCOUNT_ID --model MODEL_ID
uv run kratos-connect status --provider chatgpt
```

Complete authorization in the browser, including permission to use your ChatGPT
plan. The command returns an account registration ID and its advertised models.
Use those exact IDs in `select`. Finish active tasks and restart running Kratos
processes after changing a connection. Account settings are shared by processes
running under the same OS user. Login itself preserves the current provider.

This official authorization flow receives a scoped OAuth grant. Access, refresh
and ID tokens are saved atomically outside the workspace, under
`%LOCALAPPDATA%\KratosAgent\auth\accounts.bin`. Windows DPAPI encrypts the record
for the current OS user; other systems use owner-only directory/file permissions.
Token rotation uses a file lock. Loaded credentials are registered with the
archive redactor, and the account file is excluded from artifact capture.

`KRATOS_MODEL_PROVIDER` explicitly overrides a saved selection; normally leave it
unset when switching through the CLI. In ChatGPT mode, inference ignores the
workspace gateway URL, key and `KRATOS_MODEL`. `kratos-connect gateway` restores
the gateway selection. `signout --provider chatgpt --account ACCOUNT_ID` clears that registration's
tokens and attempts remote revocation. An unconfirmed revocation is reported.

Models and inference use the same account credential. Catalog visibility does
not establish inference access. The transport uses the documented public
Responses endpoint with `store:false`, full history, streamed output and local
function tools. It carries opaque encrypted continuation items with tool calls.
Only a terminal completed response counts as successful inference. Interrupted
streams, access failures and usage limits remain errors without a provider fallback.

The ChatGPT plan-sharing preview rejects several generation options, including
`max_output_tokens` and temperature. The transport omits them. Provider metadata
controls known context limits; configuring a larger local context budget cannot
increase the model's real capacity.

For the cookie-based OmniRoute executor supplied in this project, use
`kratos-connect login` and follow the [browser connection guide](chatgpt-browser-connection.md).
The browser flow and the official OAuth flow have separate account records.

References:

- [Registration and sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [Accounts, storage and refresh](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
- [Account models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [Preview requirements and limits](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
