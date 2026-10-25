import fs from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const source=fs.readFileSync(new URL("../src/runtime-core.js",import.meta.url),"utf8");

globalThis.document={documentElement:{dataset:{}},addEventListener(){}};
globalThis.sessionStorage={getItem(){return null;},setItem(){}};
globalThis.MutationObserver=class{observe(){} disconnect(){}};
vm.runInThisContext(source);

function adapter(counter){
  const composer={};
  return {
    id:"site", currentComposer:()=>composer, getComposerText:()=>"hello",
    identity:()=>({client_id:"c",client_type:"web-ai"}),
    releaseSend:()=>counter.count++, latestAssistantText:()=>"",
  };
}
const event={preventDefault(){},stopImmediatePropagation(){},stopPropagation(){}};

let secure={count:0};
const authChrome={runtime:{getManifest(){return {version:"1"};},lastError:null,async sendMessage(m){
  if(m.type==="MALM_CONTENT_READY") return {ok:true};
  if(m.type==="MALM_BEFORE_SEND") return {ok:false,code:"AUTH_FAILED",error:"bad auth"};
}}};
const r1=globalThis.MALM_BROWSER.createRuntime(adapter(secure),authChrome); r1.install();
await r1.handleSendIntent(event,"KEYDOWN");
assert.equal(secure.count,0,"authentication failure must fail closed");
assert.equal(document.documentElement.dataset.malmLastError,"AUTH_FAILED");

let unavailable={count:0};
const downChrome={runtime:{getManifest(){return {version:"1"};},lastError:null,async sendMessage(m){
  if(m.type==="MALM_CONTENT_READY") return {ok:true};
  if(m.type==="MALM_BEFORE_SEND") throw new Error("bridge unavailable");
}}};
const r2=globalThis.MALM_BROWSER.createRuntime(adapter(unavailable),downChrome); r2.install();
await r2.handleSendIntent(event,"KEYDOWN");
assert.equal(unavailable.count,1,"ordinary bridge unavailability may fail open");

console.log("BROWSER_FAILURE_POLICY=PASS");
