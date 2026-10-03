import { readFile, writeFile, mkdir, rename } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export function validateConfig(env) {
  const required = ['ROUTING_BASE_URL', 'ROUTING_API_KEY', 'WHATSAPP_ALLOWED_PHONES', 'KRATOS_INTERNAL_TOKEN'];
  const missing = required.filter(name => !env[name]?.trim());
  if (missing.length) throw new Error(`Missing configuration: ${missing.join(', ')}`);
  const routing = new URL(env.ROUTING_BASE_URL);
  if (!['http:', 'https:'].includes(routing.protocol)) throw new Error('Routing URL must use HTTP or HTTPS');
  if (routing.protocol === 'http:' && !['localhost', '127.0.0.1', '[::1]'].includes(routing.hostname)) throw new Error('Remote WhatsApp routing requires HTTPS');
  const allowed = new Set(env.WHATSAPP_ALLOWED_PHONES.split(',').map(phone => phone.trim().replace(/^\+/, '')));
  if (![...allowed].every(phone => /^\d{7,15}$/.test(phone))) throw new Error('Allowed phones must use international digits');
  const port = Number(env.KRATOS_AGENT_PORT || 7860);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid Kratos agent port');
  return { routingBaseUrl: routing.href.replace(/\/$/, ''), routingApiKey: env.ROUTING_API_KEY,
    allowed, agentUrl: `http://127.0.0.1:${port}`, token: env.KRATOS_INTERNAL_TOKEN,
    agentMode: env.WHATSAPP_AGENT_MODE === 'true' };
}

export async function processMessage(envelope, cfg, state, dependencies) {
  if (envelope.type !== 'INBOUND_MESSAGE') return false;
  const phone = String(envelope.payload?.from || '').replace(/^\+/, '');
  if (!cfg.allowed.has(phone)) return false;
  const id = String(envelope.message_id || '');
  if (!id || state.seen.includes(id)) return false;
  const prompt = envelope.payload?.text;
  // This adapter supports text. Never describe an attachment as inspected.
  if (typeof prompt !== 'string' || !prompt.trim()) return false;
  if (prompt.length > 16000) throw new Error('Incoming text exceeds the message limit');
  state.seen.push(id);
  state.seen = state.seen.slice(-1000);
  // Persist before execution: duplicate deliveries must not execute tools twice.
  await dependencies.save(state);
  let session = state.sessions[phone];
  if (!session) {
    const created = await dependencies.agent('/api/sessions', { title: 'WhatsApp conversation', model: 'auto' });
    session = created.session_id;
    if (!session) throw new Error('Kratos did not create a session');
    state.sessions[phone] = session;
    await dependencies.save(state);
  }
  const response = await dependencies.agent('/api/chat/sync', { session_id: session, prompt, agent_mode: cfg.agentMode });
  if (response.status === 'failed') throw new Error('Kratos could not complete this WhatsApp turn');
  const reply = response.reply || response.result;
  if (typeof reply !== 'string' || !reply.trim()) throw new Error('Kratos returned an empty reply');
  await dependencies.send(phone, reply);
  return true;
}

async function main() {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
  const pluginDir = resolve(root, '.kratos/plugins/whatsapp-official');
  const upstream = resolve(pluginDir, 'upstream/claude-plugin');
  const { default: WebSocket } = await import(pathToFileURL(resolve(upstream, 'node_modules/ws/wrapper.mjs')));
  const { sendOutboundText, flushPending, LOCAL_WAB } = await import(pathToFileURL(resolve(upstream, 'src/transport.ts')));
  const { Buffer: ReplyBuffer } = await import(pathToFileURL(resolve(upstream, 'src/buffer.ts')));
  if (process.argv.includes('--check')) {
    console.log('Upstream WebSocket, outbound transport, and reply buffer imports verified. No live connection started.');
    return;
  }
  const cfg = validateConfig(process.env);
  const buffer = new ReplyBuffer({ dir: resolve(pluginDir, 'reply-buffer'), ttlMs: 72 * 3600000, maxPerPhone: 50 });
  const statePath = resolve(pluginDir, 'kratos-sessions.json');
  let state;
  try { state = JSON.parse(await readFile(statePath, 'utf8')); }
  catch (error) { if (error.code !== 'ENOENT') throw new Error('WhatsApp session store cannot be read'); state = { sessions: {}, seen: [] }; }
  const save = async value => {
    await mkdir(pluginDir, { recursive: true });
    await writeFile(statePath + '.tmp', JSON.stringify(value), { mode: 0o600 });
    await rename(statePath + '.tmp', statePath);
  };
  const agent = async (path, body) => {
    const response = await fetch(cfg.agentUrl + path, { method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Kratos-Internal-Token': cfg.token },
      body: JSON.stringify(body), signal: AbortSignal.timeout(600000) });
    if (!response.ok) throw new Error(`Kratos request failed (${response.status})`);
    return response.json();
  };
  const dependencies = { save, agent, send: (phone, text) => sendOutboundText(cfg, phone, text, buffer) };
  let stopping = false;
  let socket;
  let queue = Promise.resolve();
  const stop = () => { stopping = true; socket?.close(); };
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
  // Studio owns stdin; EOF stops the bridge when the parent process exits.
  process.stdin.on('end', stop);
  process.stdin.resume();
  let attempt = 0;
  while (!stopping) {
    await new Promise(resolveDone => {
      const url = new URL('/ws', cfg.routingBaseUrl);
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      socket = new WebSocket(url, { headers: { Authorization: `Bearer ${cfg.routingApiKey}` }, maxPayload: 1024 * 1024 });
      let heartbeat;
      socket.on('open', () => {
        attempt = 0;
        console.log('WhatsApp routing connected.');
        heartbeat = setInterval(() => socket.ping(), 30000);
      });
      socket.on('message', data => {
        queue = queue.then(async () => {
          const envelope = JSON.parse(data.toString());
          if (envelope.type === 'WINDOW_OPENED') {
            const phone = String(envelope.payload?.from || envelope.payload?.phone || '').replace(/^\+/, '');
            if (cfg.allowed.has(phone)) await flushPending(cfg, buffer, LOCAL_WAB, phone);
          } else await processMessage(envelope, cfg, state, dependencies);
        }).catch(() => console.error('WhatsApp message handling failed. No automatic agent retry was attempted.'));
      });
      socket.on('error', () => console.error('WhatsApp routing connection failed.'));
      socket.on('close', () => { clearInterval(heartbeat); resolveDone(); });
    });
    await queue;
    if (!stopping) await new Promise(resolveDelay => setTimeout(resolveDelay, Math.min(60000, 1000 * 2 ** Math.min(attempt++, 6))));
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { console.error(error.message); process.exitCode = 1; });
}
