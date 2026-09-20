import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import createPi from "../adapters/pi.mjs";
import createOpenCode from "../adapters/opencode.mjs";
import { rpc, ReceiptStore } from "../adapters/bridge.mjs";

const dir=path.dirname(fileURLToPath(import.meta.url));
const fixture=JSON.parse(fs.readFileSync(path.join(dir,"native-fixture.json"),"utf8"));
const base={python:process.env.PYTHON_BINARY || "python3",runner:path.join(dir,"../runner.py"),profile:"p",format:"pi"};
function piHost(choice, hasUI=true) {
  const events={}, commands={}, branch=[], notices=[];
  let aborts=0;
  const pi={on:(k,v)=>events[k]=v,registerCommand:(k,v)=>commands[k]=v,appendEntry:(customType,data)=>branch.push({type:"custom",customType,data})};
  const ctx={sessionManager:{getSessionId:()=>"s",getBranch:()=>structuredClone(branch)},hasUI,
    ui:{notify:(...a)=>notices.push(a),select:async()=>choice},isIdle:()=>true,abort:()=>aborts++};
  return {pi,ctx,events,commands,branch,notices,get aborts(){return aborts;}};
}

test("real worker transport inspects fixture without remote API",async()=>{
  const r=await rpc(base,"inspect","s",fixture.pi.messages);
  assert.equal(r.eligible_pairs,1); assert.equal(r.remote_called,false);
});
test("real worker projects without touching original input",async()=>{
  const original=structuredClone(fixture.pi.messages);
  const r=await rpc(base,"project","s",original,fixture.pi.result.receipts);
  assert.equal(r.projection.applied,1); assert.deepEqual(original,fixture.pi.messages);
});
test("worker transport rejects pre-cancelled requests",async()=>{
  const controller=new AbortController(); controller.abort();
  await assert.rejects(rpc(base,"inspect","s",[],[],controller.signal),/cancelled/);
});
test("Pi manual compact makes zero Jev calls and does not show chooser",async()=>{
  let calls=0,choices=0; const h=piHost("Prune"); h.ctx.ui.select=async()=>{choices++;return "Prune";};
  createPi(h.pi,{...base,autoChoice:true},async()=>{calls++;});
  assert.equal(await h.events.session_before_compact({reason:"manual"},h.ctx),undefined);
  assert.equal(calls,0); assert.equal(choices,0); assert.equal(h.commands.compact,undefined);
});
test("Pi automatic Compact passes to native with zero assessment",async()=>{
  let calls=0; const h=piHost("Compact — native"); createPi(h.pi,{...base,autoChoice:true},async()=>{calls++;});
  assert.equal(await h.events.session_before_compact({reason:"threshold"},h.ctx),undefined);
  assert.equal(calls,0); assert.equal(h.aborts,0);
});
test("Pi Pause cancels and stops rather than falsely resuming",async()=>{
  const h=piHost(undefined); createPi(h.pi,{...base,autoChoice:true},async()=>{throw Error("unexpected");});
  assert.deepEqual(await h.events.session_before_compact({reason:"threshold"},h.ctx),{cancel:true});
  assert.equal(h.aborts,1);
});
test("Pi headless choice cancels without stdin prompt",async()=>{
  const h=piHost(undefined,false); createPi(h.pi,{...base,autoChoice:true});
  assert.deepEqual(await h.events.session_before_compact({reason:"overflow"},h.ctx),{cancel:true});
  assert.equal(h.aborts,1);
});
test("Pi manual prune appends proof and next request is projected",async()=>{
  const h=piHost(); const ops=[];
  const call=async(c,op,...args)=>{ops.push(op);return op==="assess"?structuredClone(fixture.pi.result):rpc(c,op,...args);};
  createPi(h.pi,{...base,autoChoice:false},call);
  await h.events.context({messages:fixture.pi.messages},h.ctx);
  await h.commands.prune.handler("",h.ctx);
  assert.equal(h.branch.length,1); assert.deepEqual(ops,["assess"]);
  const r=await h.events.context({messages:fixture.pi.messages},h.ctx);
  assert.notDeepEqual(r.messages[2],fixture.pi.messages[2]);
  assert.equal(h.events.session_before_compact,undefined);
});
test("Pi stale branch does not commit an assessed plan",async()=>{
  const h=piHost(); createPi(h.pi,base,async()=>{h.branch.push({type:"message",message:{role:"user",content:"new"}});return fixture.pi.result;});
  await h.events.context({messages:fixture.pi.messages},h.ctx);
  await h.commands.prune.handler("",h.ctx);
  assert.equal(h.branch.filter(x=>x.type==="custom").length,0);
});
test("OpenCode transform mutates the shared array in place",async(t)=>{
  const state=fs.mkdtempSync(path.join(os.tmpdir(),"jev-node-")); t.after(()=>fs.rmSync(state,{recursive:true,force:true}));
  const config={...base,format:"opencode",stateDir:state};
  const store=new ReceiptStore(state,"p");store.save("s",fixture.opencode.result.receipts,null);
  const plugin=await createOpenCode({client:{tui:{showToast:async()=>{}}}},config);
  const array=structuredClone(fixture.opencode.messages), output={messages:array};
  await plugin["experimental.chat.messages.transform"]({},output);
  assert.equal(output.messages,array);assert.notDeepEqual(array[2],fixture.opencode.messages[2]);
});
test("OpenCode preserves an existing /prune command",async(t)=>{
  const state=fs.mkdtempSync(path.join(os.tmpdir(),"jev-node-")); t.after(()=>fs.rmSync(state,{recursive:true,force:true}));
  let calls=0;const plugin=await createOpenCode({client:{tui:{showToast:async()=>{}}}},{...base,stateDir:state},async()=>{calls++;});
  const cfg={command:{prune:{template:"existing"}}};await plugin.config(cfg);
  assert.equal(cfg.command.prune.template,"existing");
  await plugin["command.execute.before"]({command:"prune",sessionID:"s"},{});assert.equal(calls,0);
});
test("OpenCode manual /prune stops with a visible command result, never compacts",async(t)=>{
  const state=fs.mkdtempSync(path.join(os.tmpdir(),"jev-node-"));t.after(()=>fs.rmSync(state,{recursive:true,force:true}));
  const config={...base,format:"opencode",stateDir:state}; const ops=[];
  const plugin=await createOpenCode({client:{tui:{showToast:async()=>{}}}},config,async(c,op,...args)=>{ops.push(op);return fixture.opencode.result;});
  await plugin.config({});await plugin["experimental.chat.messages.transform"]({},{messages:structuredClone(fixture.opencode.messages)});
  await assert.rejects(plugin["command.execute.before"]({command:"prune",sessionID:"s"},{}),/completed without a model turn/);
  assert.deepEqual(ops,["assess"]);
  await plugin["command.execute.before"]({command:"compact",sessionID:"s"},{});
  assert.deepEqual(ops,["assess"]);
});
test("receipt store refuses stale compare-and-swap",(t)=>{
  const state=fs.mkdtempSync(path.join(os.tmpdir(),"jev-node-"));t.after(()=>fs.rmSync(state,{recursive:true,force:true}));
  const s=new ReceiptStore(state,"p");s.save("s",[],null);assert.throws(()=>s.save("s",[],null),/changed/);
});
test("receipt stores are isolated by profile",(t)=>{
  const state=fs.mkdtempSync(path.join(os.tmpdir(),"jev-node-"));t.after(()=>fs.rmSync(state,{recursive:true,force:true}));
  const a=new ReceiptStore(state,"a"),b=new ReceiptStore(state,"b");a.save("s",[],null);
  assert.equal(b.load("s").version,null);
});
test("Pi different-session fork does not inherit receipt authority",async()=>{
  const h=piHost(); h.branch.push({type:"custom",customType:"jev-prune.receipts.v1",data:{session:"parent",receipts:fixture.pi.result.receipts}});
  let calls=0; createPi(h.pi,base,async()=>{calls++;});
  assert.equal(await h.events.context({messages:fixture.pi.messages},h.ctx),undefined);
  assert.equal(calls,0);
});
