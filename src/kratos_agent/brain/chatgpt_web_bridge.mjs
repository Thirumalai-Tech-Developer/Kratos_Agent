// Private executor worker. The extension only collects credentials.
import path from "node:path";
import {pathToFileURL} from "node:url";
import {createInterface} from "node:readline";
import {RegularBrowserConnection} from "./chatgpt_regular_browser.mjs";
import {cookieProviderMain} from "./web_cookie_bridge.mjs";
export {readExecutorCompletion} from "./web_cookie_bridge.mjs";
const writeProtocol=process.stdout.write.bind(process.stdout);

export function supportedAccountModels(routes,accountModels) {
  const normalize=value=>String(value).toLowerCase().replaceAll(".","-");
  const slugs=new Set(accountModels.filter(item=>item && item.enabled!==false && item.available!==false && item.visibility!=="hidden").map(item=>normalize(item.slug || item.id || "")));
  return routes.filter(route=>{
    const id=normalize(route.id);
    if(id.includes("luna-free")) return false;
    return slugs.has(id) || slugs.has(id.replace(/-(?:instant|thinking)$/,""));
  }).map(route=>({
    id:"chatgpt-web/"+route.id,display_name:route.name,supports_vision:false,
    supports_tool_calling:false,local_tool_bridge:true,supports_reasoning:route.supportsReasoning===true,
    effort_tiers:[...(route.supportedThinkingEfforts || [])],access_verified:false,context_limits_available:false
  }));
}

function publicFailure(error) {
  return {
    error:["browser_conversation_lost","browser_extension_unavailable","browser_tab_missing",
      "browser_draft_present","browser_page_busy","browser_model_unavailable","browser_effort_unavailable",
      "browser_submit_unavailable","browser_response_incomplete"].includes(error?.code) ? error.code : "browser_session_failed",
    status:502,
    diagnostic:{
      type:["Error","TypeError","TimeoutError","ReferenceError"].includes(error?.name) ? error.name:"Error",
      location:String(error?.stack || "").match(/(?:chatgpt_cookie_executor|chatgpt_owned_turn|web_cookie_bridge)\.mjs:\d+:\d+/)?.[0] || "executor"
    }
  };
}

export async function executeBridgeInput(input,source,{persistent=false}={}) {
  const load=relative=>import(pathToFileURL(path.join(source,relative)).href);
  if(persistent && (input.mode!=="complete" || input.provider_id!=="chatgpt-web" ||
      !input.account_id || !input.storage_state || !input.conversation?.key))
    return {error:"browser_request_invalid",status:400};
  if(input.mode!=="check" && !input.storage_state) {
    const collector=new RegularBrowserConnection({...input.browser_connection,provider:input.provider_id || "chatgpt-web"});
    await collector.start();
    try {Object.assign(input,await collector.inspect(30000));}
    finally {await collector.close();}
  }
  if(input.provider_id==="groq-web") return {error:"website_executor_unavailable",status:400};
  try {
    if(input.provider_id && input.provider_id!=="chatgpt-web") return await cookieProviderMain(input,load);
    const {chatgptCookieMain}=await import("./chatgpt_cookie_executor.mjs");
    return await chatgptCookieMain({...input,persistent},load,supportedAccountModels);
  } finally {
    if(!persistent) {
      const {shutdownPool}=await load("open-sse/services/browserPool.ts");
      await shutdownPool("kratos-worker-complete");
    }
  }
}

export async function persistentFrames(stream,execute,write) {
  const reader=createInterface({input:stream,crlfDelay:Infinity});
  try {
    for await(const line of reader) {
      let id=null,result;
      try {
        if(Buffer.byteLength(line)>12*1024*1024) throw new Error("Invalid frame");
        const frame=JSON.parse(line);
        if(typeof frame.request_id!=="string" || !/^[A-Za-z0-9_-]{1,128}$/.test(frame.request_id) ||
            !frame.request || typeof frame.request!=="object" || Array.isArray(frame.request))
          throw new Error("Invalid frame");
        id=frame.request_id;
        result=await execute(frame.request);
      } catch(error) {result=publicFailure(error);}
      await write({request_id:id,result});
    }
  } finally {reader.close();}
}

// Importing this module for tests does not launch a worker.
if(process.argv.includes("--source")) {
  const source=process.argv[process.argv.indexOf("--source")+1];
  console.log=console.info=console.warn=console.error=()=>{};
  process.stdout.write=process.stderr.write.bind(process.stderr);
  const write=value=>new Promise(resolve=>writeProtocol(JSON.stringify(value)+"\n",resolve));
  if(process.argv.includes("--persistent")) {
    try {
      await persistentFrames(process.stdin,input=>executeBridgeInput(input,source,{persistent:true}),write);
    } finally {
      const {shutdownPool}=await import(pathToFileURL(path.join(source,"open-sse/services/browserPool.ts")).href);
      await shutdownPool("kratos-worker-closed");
    }
  } else {
    let result;
    try {
      const chunks=[];let size=0;
      for await(const chunk of process.stdin) {
        size+=chunk.length;
        if(size>12*1024*1024) throw new Error("Invalid input");
        chunks.push(chunk);
      }
      result=await executeBridgeInput(JSON.parse(Buffer.concat(chunks).toString("utf8")),source);
    } catch(error) {result=publicFailure(error);}
    await write(result);
  }
  process.exit(0);
}
