import fs from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const runtimeSource = fs.readFileSync(new URL("../src/runtime-core.js", import.meta.url), "utf8");
const chatgptSource = fs.readFileSync(new URL("../src/site-chatgpt.js", import.meta.url), "utf8");

const dataset = {};
const listeners = {};
globalThis.document = {
  documentElement: {dataset},
  addEventListener(type, fn) { listeners[type] = fn; },
};
globalThis.sessionStorage = {
  data:new Map(),
  getItem(k){ return this.data.get(k) ?? null; },
  setItem(k,v){ this.data.set(k,String(v)); },
};
globalThis.MutationObserver = class { observe(){} disconnect(){} };
globalThis.location = {hostname:"chatgpt.com", pathname:"/"};

globalThis.chrome = {runtime:{lastError:null, getManifest(){return {version:"0.3.0"};}, async sendMessage(msg){
  if (msg.type === "MALM_CONTENT_READY") return {ok:true};
  if (msg.type === "MALM_BEFORE_SEND") return {ok:true,items:[{memory_id:"m1",content:"purple"}]};
  return {ok:true};
}}};

vm.runInThisContext(runtimeSource);
assert.ok(globalThis.MALM_BROWSER);
const envelope = globalThis.MALM_BROWSER.makeMemoryEnvelope([{memory_id:"m1",content:"purple"}]);
assert.match(envelope,/m1/);
assert.match(envelope,/purple/);

let releases = 0;
const composer = {textContent:"hello", innerText:"hello"};
const fakeAdapter = {
  id:"fake",
  currentComposer:()=>composer,
  getComposerText:()=>"hello",
  identity:()=>({client_id:"chatgpt-web",client_type:"chatgpt-web"}),
  applyRecallContext:()=>{},
  releaseSend:()=>{ releases++; },
  latestAssistantText:()=>"",
};
const runtime = globalThis.MALM_BROWSER.createRuntime(fakeAdapter, globalThis.chrome);
runtime.install();
const event = {preventDefault(){},stopImmediatePropagation(){},stopPropagation(){}};
await Promise.all([
  runtime.handleSendIntent(event,"KEYDOWN"),
  runtime.handleSendIntent(event,"SUBMIT"),
]);
assert.equal(releases,1,"multi-signal send intent must release once");

// New runtime generation must supersede old listeners/contexts even on the same document.
let oldReleases = 0, newReleases = 0;
const oldAdapter = {...fakeAdapter, id:"same-site", releaseSend:()=>{oldReleases++;}};
const newAdapter = {...fakeAdapter, id:"same-site", releaseSend:()=>{newReleases++;}};
const oldRuntime = globalThis.MALM_BROWSER.createRuntime(oldAdapter, globalThis.chrome);
oldRuntime.install();
const oldGeneration = oldRuntime.generation;
const newRuntime = globalThis.MALM_BROWSER.createRuntime(newAdapter, globalThis.chrome);
newRuntime.install();
assert.notEqual(oldGeneration,newRuntime.generation);
assert.equal(oldRuntime.ownsDocument(),false);
assert.equal(newRuntime.ownsDocument(),true);
await oldRuntime.handleSendIntent(event,"KEYDOWN");
await newRuntime.handleSendIntent(event,"KEYDOWN");
assert.equal(oldReleases,0,"stale generation must self-disable before send");
assert.equal(newReleases,1,"current generation owns the document");

let registered;
globalThis.MALM_BROWSER.registerSiteAdapter = (a) => { registered = a; };
vm.runInThisContext(chatgptSource);
assert.ok(registered);
assert.equal(registered.isSendKeydown({key:"Enter",shiftKey:true,isComposing:false,target:{closest:()=>({})}}),false);
assert.equal(registered.isSendKeydown({key:"Enter",shiftKey:false,isComposing:true,target:{closest:()=>({})}}),false);
assert.equal(registered.isSendKeydown({key:"Enter",shiftKey:false,isComposing:false,target:{closest:()=>({})}}),true);

console.log("BROWSER_RUNTIME_CORE=PASS");
