import fs from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const source=fs.readFileSync(new URL("../src/service-worker.js",import.meta.url),"utf8");
const store={}; let listener; let alarmListener; let captureAttempts=0; let bridgeUp=false;
globalThis.chrome={
  storage:{local:{async get(k){return {[k]:store[k]};},async set(o){Object.assign(store,o);}}},
  alarms:{create(){},onAlarm:{addListener(fn){alarmListener=fn;}}},
  runtime:{onMessage:{addListener(fn){listener=fn;}},onInstalled:{addListener(){}},onStartup:{addListener(){}}},
};
globalThis.fetch=async(url,opts={})=>{
  if(url.endsWith("/bootstrap/v1/browser")) return {ok:true,status:200,async json(){return {credential:"tok",authorized_scopes:["user"],authorized_memory_spaces:["shared"],default_memory_space:{space_id:"shared",owner_id:"owner",kind:"personal"}};}};
  if(url.endsWith("/v1/capture")){
    captureAttempts++;
    if(!bridgeUp) throw new Error("offline");
    return {ok:true,status:200,async json(){return {decision:"COMMIT"};}};
  }
  if(url.endsWith("/v1/recall")) return {ok:true,status:200,async json(){return {items:[]};}};
  throw new Error("unexpected");
};
vm.runInThisContext(source);
function dispatch(msg){return new Promise((resolve,reject)=>{const keep=listener(msg,{},resolve); if(!keep) reject(new Error("not async"));});}
const site={client_id:"chatgpt-web",client_type:"chatgpt-web",provider:"openai",product:"chatgpt",surface:"web"};
const msg={type:"MALM_AFTER_RESPONSE",transaction_id:"tx-out",turn_id:"tx-out",session_id:"s",user_text:"remember",assistant_text:"ok",injected_memory_ids:[],explicit_remember_request:true,site};
const first=await dispatch(msg);
assert.equal(first.ok,true); assert.equal(first.queued,true);
assert.equal(store["malm.capture_outbox"].length,1);
bridgeUp=true;
alarmListener({name:"malm-capture-retry"});
await new Promise(r=>setTimeout(r,20));
assert.deepEqual(store["malm.capture_outbox"],[]);
assert.ok(captureAttempts>=2);
console.log("BROWSER_CAPTURE_OUTBOX=PASS");
