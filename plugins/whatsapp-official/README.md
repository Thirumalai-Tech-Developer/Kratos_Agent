# Official WhatsApp plugin for Kratos

Installed upstream: https://github.com/dearken10/ai-agent-whatsapp-official-plugin

The upstream OpenClaw and Claude plugins are preserved under
`.kratos/plugins/whatsapp-official/upstream`. This adapter uses the upstream
WebSocket contract, outbound transport, reply chunking and 24-hour-window buffer,
and forwards text messages into the local Kratos runtime.

## Connect

1. Start Docker Desktop. Configure the upstream `.env` with a Meta Cloud API
   token and phone number ID, or 360dialog API key. Provide the WhatsApp number,
   webhook app secret and verification token. Start its backend:

   ```powershell
   cd .kratos/plugins/whatsapp-official/upstream
   docker compose up -d --build
   ```

2. Register a public HTTPS webhook with your WhatsApp provider and complete
   pairing using upstream instructions. Put the resulting routing API key in
   `.kratos/plugins/whatsapp-official/.env` and set `WHATSAPP_ALLOWED_PHONES`.
3. Set `WHATSAPP_BRIDGE_ENABLED=true` there and restart Kratos Studio.
   `/plugins` lists the plugin and process state. Connection events are logged in
   `.kratos/plugins/whatsapp-official/bridge.log`.

The plugin is installed but starts inactive. Enabling it authorizes automatic
replies to messages from the configured allowed numbers. Direct chat is the
default; set `WHATSAPP_AGENT_MODE=true` explicitly to permit agent tools.
All sender sessions share the configured Kratos workspace; this is not a
multi-user security sandbox. Give access only to trusted senders.

Text messages are supported. Attachments are not downloaded or inspected by this
Kratos adapter. Only allowlisted senders are handled. Message IDs are persisted
to avoid duplicate tool execution; failed turns are not automatically retried.
Buffered replies are flushed when the backend reports that the messaging window
has reopened. No WhatsApp message is sent during installation or local testing.

The official-provider setup requires your own account/API credentials. This plugin
does not connect a personal WhatsApp Web session or grant free provider access.
