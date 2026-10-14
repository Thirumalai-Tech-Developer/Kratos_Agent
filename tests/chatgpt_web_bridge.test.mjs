import {Readable} from "node:stream";
import assert from "node:assert/strict";
import test from "node:test";
import {
  supportedAccountModels,
  persistentFrames,
  readExecutorCompletion,
} from "../src/kratos_agent/brain/chatgpt_web_bridge.mjs";

test("only account-advertised executor routes are selectable", () => {
  const routes = [
    { id: "gpt-5-6", name: "Instant" },
    { id: "gpt-5-6-thinking", name: "Thinking" },
    { id: "gpt-5-6-pro", name: "Pro" },
    { id: "gpt-5-5-pro", name: "Old Pro" },
  ];
  const models = supportedAccountModels(routes, [
    { slug: "gpt-5-6" },
    { slug: "gpt-5-6-pro", available: false },
    { slug: "gpt-5-5-pro", visibility: "hidden" },
  ]);
  assert.deepEqual(
    models.map((model) => model.id),
    ["chatgpt-web/gpt-5-6", "chatgpt-web/gpt-5-6-thinking"],
  );
  assert.equal(models[0].access_verified, false);
  assert.equal(models[0].supports_tool_calling, false);
  assert.equal(models[0].context_limits_available, false);
});

test("unknown account slugs are never translated into invented routes", () => {
  assert.deepEqual(
    supportedAccountModels(
      [{ id: "gpt-5-6-pro", name: "Pro" }],
      [{ slug: "unknown-new-model" }],
    ),
    [],
  );
});

test("executor failure wrappers preserve quota and authentication error status", async () => {
  for (const status of [429, 401, 502]) {
    const result = await readExecutorCompletion({
      response: new Response("private upstream diagnostic", { status }),
    });
    assert.deepEqual(result, { error: "browser_turn_failed", status });
    assert.equal(JSON.stringify(result).includes("private"), false);
  }
});

test("executor success responses expose only completed assistant text", async () => {
  assert.deepEqual(
    await readExecutorCompletion(
      Response.json({ choices: [{ message: { content: "answer" } }] }),
    ),
    { text: "answer" },
  );
  assert.deepEqual(
    await readExecutorCompletion(Response.json({ choices: [] })),
    { error: "empty_browser_response", status: 502 },
  );
});

test('website module failures expose a recovery category without the upstream message', async () => {
  const result = await readExecutorCompletion({ response: Response.json({ error: {
    message: 'ChatGPT Web first-party request module was not loaded private-token-value',
  } }, { status: 400 }) });
  assert.deepEqual(result, { error: 'browser_module_unavailable', status: 400 });
  assert.equal(JSON.stringify(result).includes('private-token-value'), false);
});

test('persistent private frames remain correlated across multiple turns',async()=>{
  const results=[];const input=[{request_id:'one',request:{prompt:'first'}},{request_id:'two',request:{prompt:'second'}}].map(v=>JSON.stringify(v)+'\n');
  await persistentFrames(Readable.from(input),async request=>({text:request.prompt}),async result=>{results.push(result);});
  assert.deepEqual(results,[{request_id:'one',result:{text:'first'}},{request_id:'two',result:{text:'second'}}]);
});
test('invalid frame never executes and errors cannot expose request or cookie content',async()=>{
  let calls=0;const results=[];
  await persistentFrames(Readable.from(['{"request_id":"bad id","request":{"cookie":"private-cookie"}}\n']),async()=>{calls++;},async r=>{results.push(r);});
  assert.equal(calls,0);
  assert.equal(results[0].request_id,null);
  assert.equal(JSON.stringify(results).includes('private-cookie'),false);
});
