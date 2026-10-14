import assert from "node:assert/strict";
import test from "node:test";
import { executorConversation, sseConversation, kimiConversation } from "../src/kratos_agent/brain/cookie_conversation.mjs";
import { parseGroqReply } from "../src/kratos_agent/brain/groq_browser.mjs";

test("DeepSeek captures only real response IDs for the parent of the next turn", () => {
  assert.deepEqual(sseConversation("deepseek-web", 'data: {"request_message_id":1,"response_message_id":2}\n', {chat_session_id:"owned"}), {chat_session_id:"owned",parent_message_id:2});
  assert.equal(sseConversation("deepseek-web", 'data: {"request_message_id":1}\n', {chat_session_id:"owned"}), null);
});

test("DeepSeek restores the owned conversation and sends its real parent ID", async () => {
  const originalFetch=globalThis.fetch;
  let submitted;
  globalThis.fetch=async (_url, options) => {
    submitted=JSON.parse(options.body);
    return new Response('data: {"response_message_id":4}\n\ndata: [DONE]\n\n');
  };
  const fetcher=globalThis.fetch;
  const module={sessionCache:new Map(), extractUserToken:()=>"private-token"};
  try {
    const input={conversation:{new:false,native:{chat_session_id:"owned",parent_message_id:2}}};
    const result=await executorConversation("deepseek-web",module,{},input,{data:{},apiKey:"protected"},async()=>{
      const response=await globalThis.fetch("https://chat.deepseek.com/api/v0/chat/completion",{method:"POST",body:JSON.stringify({chat_session_id:"owned",parent_message_id:null,prompt:"new tool results"})});
      await response.text(); return {response:new Response('completed')};
    });
    assert.equal(submitted.parent_message_id,2);
    assert.deepEqual(result.conversation.native,{chat_session_id:"owned",parent_message_id:4});
    assert.equal(module.sessionCache.get("private-token").sessionId,"owned");
    assert.equal(globalThis.fetch,fetcher);
  } finally { globalThis.fetch=originalFetch; }
});

test("Kimi metadata requires a real assistant message and chat ID", () => {
  const frames=[{chat:{id:"chat-1"}},{message:{id:"user-1",role:"user"}},{message:{id:"assistant-1",role:"assistant"}}];
  const module={decodeConnectFrame:(_bytes,offset)=>({consumed:1,frame:{message:frames[offset]}})};
  assert.deepEqual(kimiConversation(module,new Uint8Array(3)),{chat_id:"chat-1",parent_id:"assistant-1"});
  assert.equal(kimiConversation(module,new Uint8Array(2)),null);
});

test("Groq accepts completed native streams and rejects errors and partial text", () => {
  assert.equal(parseGroqReply('0:"Hi"\nd:{"finishReason":"stop"}\n'),"Hi");
  assert.equal(parseGroqReply('data: {"type":"text-delta","delta":"Hi"}\n\ndata: {"type":"finish"}\n\n'),"Hi");
  assert.throws(()=>parseGroqReply('0:"partial"\n'),/incomplete/);
  assert.throws(()=>parseGroqReply('data: {"type":"error","errorText":"private detail"}\n\n'),/error/);
});
