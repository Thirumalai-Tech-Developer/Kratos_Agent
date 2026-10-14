import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import { readFile } from "node:fs/promises";
const source=await readFile(new URL('../src/kratos_agent/brain/chatgpt_browser_extension/conversation-tabs.js',import.meta.url),'utf8');

test("owned tabs isolate sessions and a user navigation requires a full bootstrap",async()=>{
  const records={}, tabs=new Map([[1,{id:1,url:'https://chatgpt.com/c/user-draft',windowId:5,status:'complete'}]]);
  let next=2;
  const context=vm.createContext({URL,Date,setTimeout,KRATOS_BROWSER:{providers:{'chatgpt-web':{url:'https://chatgpt.com/'}}},
    authorizedTab:async()=>tabs.get(1),chatgptUrl:url=>new URL(url).origin==='https://chatgpt.com',
    chrome:{storage:{local:{get:async key=>({[key]:records[key]}),set:async values=>Object.assign(records,values)}},tabs:{
      get:async id=>{if(!tabs.has(id))throw new Error('closed');return tabs.get(id)},
      create:async values=>{const tab={id:next++,...values,status:'complete'};tabs.set(tab.id,tab);return tab}
    }}});
  vm.runInContext(source,context);
  const work=key=>({provider:'chatgpt-web',conversation:{key:key.repeat(64),new:true}});
  const first=await context.kratosConversationTab(work('a'));
  const second=await context.kratosConversationTab(work('b'));
  assert.notEqual(first.tab_id,second.tab_id);
  assert.equal(tabs.get(1).url,'https://chatgpt.com/c/user-draft');
  const followup=work('a');followup.conversation.new=false;
  assert.equal((await context.kratosConversationTab(followup)).tab_id,first.tab_id);
  tabs.get(first.tab_id).url='https://chatgpt.com/c/user-changed';
  assert.equal((await context.kratosConversationTab(followup)).reset,true);
  tabs.delete(second.tab_id);
  const closed=work('b');closed.conversation.new=false;
  assert.equal((await context.kratosConversationTab(closed)).reset,true);
});
