# Record a manual provider chat

Use [browser_api_recorder.js](../scripts/browser_api_recorder.js) in your original signed-in browser. The recorder observes your normal page activity and downloads a local JSON file. It does not send chats, upload recordings, refresh credentials, or bypass provider restrictions.

## Run it

1. Open the provider's normal chat website and sign in.
2. Open Chrome DevTools with **F12**, select **Console**, and ensure the selected execution context is the chat page.
3. Copy the entire `scripts/browser_api_recorder.js` file, paste it into the Console, and run it.
4. A **Kratos API recorder** panel appears at the bottom right. Open the model menu, select a model, and send a short test message manually. Wait for the answer to finish. For protocol diagnosis, two short turns can show how the website continues a conversation.
5. Click **Download log**. The JSON file is saved through Chrome's normal download flow. Attach that file in this chat together with the model's displayed name.
6. Click **Stop** to restore the page methods. This leaves the download button available and does not cancel the website's chat. A refresh also removes the recorder; paste it again on the refreshed page.

Use separate recordings for Qwen, Dola, Z.ai, Meta AI, or another provider. A manual capture helps identify the request endpoint, model identifier, conversation fields, response framing and completion events. It does not itself establish that those endpoints can be used by a separate client.

## Captured data

- **Fetch:** URL, method, visible headers, request body, response status, response headers and readable response body.
- **Streaming responses:** a bounded copy of the text/SSE stream, parsed SSE events, chunk byte counts and arrival times. Application response objects and bodies remain available to the website.
- **XHR:** request details, progress text and the completed response. Binary responses are represented by metadata.
- **WebSockets:** newly created connections and their sent/received frames. Existing sockets become observable after an intercepted send. Small UTF-8 binary frames are decoded; other binary frames retain size/type metadata.
- **EventSource:** new connections, normal messages, reconnection state and named events that the page registers with `addEventListener` after installation.
- **Beacon:** the observed URL/body and whether the browser accepted it for sending.
- **Resource timing:** URL, initiator and browser timing metadata, including some traffic whose bodies are unavailable. These entries can duplicate the detailed fetch/XHR entries.

Common authorization headers, cookies, tokens, passwords, client secrets, signed URL fields and account email/phone fields are masked in exported logs. Generation token objects containing `text` are preserved. Prompts and model replies remain in the log. Unknown credential formats or secrets embedded in chat text may need manual redaction before sharing. The script never reads `document.cookie` or browser credential storage.

Each text body is limited to 1 MiB, each frame to 64 KiB, each connection to 500 frames, and the log to 300 entries with an approximate 20 MiB memory budget. There are at most eight simultaneous body readers. The export records truncation, skipped captures and dropped entries. Download while a reply is streaming to save the content captured so far, or after it finishes for the completion marker.

## Console commands

```javascript
kratosApiRecorder.download(); // Save the JSON file
kratosApiRecorder.snapshot(); // View a sanitized copy of the log
kratosApiRecorder.status(); // Counts, memory estimate and reader count
kratosApiRecorder.clear(); // Clear previous entries; keep recording
kratosApiRecorder.stop(); // Stop observation and restore patched methods
kratosApiRecorder.dispose(); // Stop, remove the panel/API; then paste again to reinstall
```

## Limits

Console code cannot observe every browser request. Workers, other iframe execution contexts, opaque CORS responses, browser-injected credentials, cached references to native functions, existing silent sockets, or encrypted/compressed binary protocols can hide bodies. The recorder captures traffic after installation. It does not recover earlier requests or survive a reload.

If a needed request is missing, DevTools **Network** can provide a separate HAR export, while its **WS** view can show WebSocket messages. Browser HAR exports may include sensitive data; review them before attaching them.

## Qwen capture support

The October 6 Qwen recording confirmed `qwen3.7-plus`, `/api/v2/chats/new`, and `/api/v2/chat/completions`. Kratos uses those normal authenticated requests for this model, with the session already imported by Browser Sync. It stops reading when the answer phase reports `status: "finished"`; Qwen does not need to send `[DONE]`. Repeated thinking summaries are deduplicated and input/output token counts are mapped to the completion format.

The `qwen-ui-qwen3.7-plus` picker alias maps to the same protocol ID. Other observed picker choices keep the existing browser transport. A recording of one model does not establish the IDs, attachment format, or API availability of other models. This API path supports text messages and retains the ten-answer conversation handoff. Login, challenge and quota errors remain explicit; it does not retry them through another account or transport.

Recordings redact authorization data. They diagnose the protocol but cannot replace the live signed-in credentials. After session expiry, the Browser Sync extension must be connected to the running receiver and a signed-in original browser tab.
