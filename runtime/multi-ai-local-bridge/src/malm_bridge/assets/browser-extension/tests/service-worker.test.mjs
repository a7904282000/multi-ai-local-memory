import fs from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const source = fs.readFileSync(new URL("../src/service-worker.js", import.meta.url), "utf8");
const store = {};
let listener;
const calls = [];
let bootstraps = 0;

globalThis.chrome = {
  storage:{local:{
    async get(k){ return {[k]:store[k]}; },
    async set(obj){ Object.assign(store,obj); },
  }},
  alarms:{create(){},onAlarm:{addListener(){}}},
  runtime:{
    onMessage:{addListener(fn){ listener=fn; }},
    onInstalled:{addListener(){}},
    onStartup:{addListener(){}},
  },
};

globalThis.fetch = async (url, opts={}) => {
  calls.push({url,opts});
  if (url.endsWith("/bootstrap/v1/browser")) {
    bootstraps++;
    return {ok:true,status:200,async json(){return {
      credential:`token-${bootstraps}`,
      authorized_scopes:["user"],
      authorized_memory_spaces:["shared"],
      default_memory_space:{space_id:"shared",owner_id:"owner",kind:"personal"},
    };}};
  }
  if (url.endsWith("/v1/recall")) {
    return {ok:true,status:200,async json(){return {memory_context_available:true,items:[{memory_id:"m1",content:"remembered"}]};}};
  }
  if (url.endsWith("/v1/capture")) {
    return {ok:true,status:200,async json(){return {decision:"COMMIT",committed_memory_ids:["m2"]};}};
  }
  throw new Error(`unexpected fetch ${url}`);
};

vm.runInThisContext(source);
assert.equal(typeof listener,"function");

function dispatch(message) {
  return new Promise((resolve,reject) => {
    const keep = listener(message,{},resolve);
    if (!keep) setTimeout(()=>reject(new Error("listener did not keep channel")),20);
  });
}
const site={client_id:"chatgpt-web",client_type:"chatgpt-web",provider:"openai",product:"chatgpt",surface:"web"};
const before=await dispatch({type:"MALM_BEFORE_SEND",transaction_id:"tx1",turn_id:"tx1",session_id:"s",user_text:"hello",site});
assert.equal(before.ok,true);
assert.equal(before.items[0].memory_id,"m1");
assert.equal(bootstraps,1);
const recallCall=calls.find(x=>x.url.endsWith("/v1/recall"));
const recallBody=JSON.parse(recallCall.opts.body);
assert.equal(recallBody.memory_space.space_id,"shared");
assert.equal(recallBody.query.scopes[0],"user");
assert.match(recallCall.opts.headers.Authorization,/Bearer token-1/);

const after=await dispatch({type:"MALM_AFTER_RESPONSE",transaction_id:"tx1",turn_id:"tx1",session_id:"s",user_text:"hello",assistant_text:"hi",injected_memory_ids:["m1"],explicit_remember_request:false,site});
assert.equal(after.ok,true);
assert.equal(bootstraps,1,"existing worker credential should be reused");
assert.ok(Object.values(store).some(v=>v?.credential==="token-1"));
assert.deepEqual(store["malm.capture_outbox"],[]);

console.log("BROWSER_SERVICE_WORKER=PASS");
