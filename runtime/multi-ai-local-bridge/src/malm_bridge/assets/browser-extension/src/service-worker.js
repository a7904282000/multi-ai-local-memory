"use strict";

const BRIDGE_BASE_URL = "http://127.0.0.1:18790";
const CONTRACT_VERSION = "1.0";
const executionBySite = (site) => ({
  surface: site.surface || "web",
  provider: site.provider || null,
  product: site.product || null,
  model: site.model || null,
  agent_id: null,
  intermediary_chain: [],
});

function randomId() {
  return crypto.randomUUID();
}

async function getInstanceId() {
  const key = "malm.client_instance_id";
  const found = await chrome.storage.local.get(key);
  if (found[key]) return found[key];
  const value = randomId();
  await chrome.storage.local.set({[key]:value});
  return value;
}

function credentialKey(site, instanceId) {
  return `malm.auth_profile.${site.client_id}.${site.client_type}.${instanceId}`;
}

async function bootstrap(site) {
  const instanceId = await getInstanceId();
  const client = {client_id:site.client_id, client_type:site.client_type, client_instance_id:instanceId};
  const res = await fetch(`${BRIDGE_BASE_URL}/bootstrap/v1/browser`, {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({client}),
  });
  if (!res.ok) throw new Error(`Browser bootstrap failed: ${res.status}`);
  const body = await res.json();
  if (!body.credential || !body.default_memory_space) throw new Error("Browser bootstrap returned incomplete auth profile");
  const profile = {
    credential:body.credential,
    client,
    defaultMemorySpace:body.default_memory_space,
    scopes:body.authorized_scopes || ["user"],
  };
  await chrome.storage.local.set({[credentialKey(site,instanceId)]:profile});
  return profile;
}

async function getAuth(site, {forceBootstrap=false} = {}) {
  const instanceId = await getInstanceId();
  const client = {client_id:site.client_id, client_type:site.client_type, client_instance_id:instanceId};
  const key = credentialKey(site,instanceId);
  if (!forceBootstrap) {
    const found = await chrome.storage.local.get(key);
    if (found[key]?.credential) return {...found[key], client};
  }
  return bootstrap(site);
}

async function bridgeRequest(site, path, payload) {
  let auth = await getAuth(site);
  for (let attempt = 0; attempt < 2; attempt++) {
    const res = await fetch(`${BRIDGE_BASE_URL}${path}`, {
      method:"POST",
      headers:{"Authorization":`Bearer ${auth.credential}`,"Content-Type":"application/json"},
      body:JSON.stringify(payload(auth.client, auth)),
    });
    if (res.status === 401 && attempt === 0) {
      auth = await getAuth(site,{forceBootstrap:true});
      continue;
    }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(body?.error?.message || body?.error?.code || `Bridge HTTP ${res.status}`);
      err.code = body?.error?.code || `HTTP_${res.status}`;
      throw err;
    }
    return body;
  }
  throw new Error("Bridge authentication retry exhausted");
}

const OUTBOX_KEY = "malm.capture_outbox";

async function readOutbox() {
  const found = await chrome.storage.local.get(OUTBOX_KEY);
  return Array.isArray(found[OUTBOX_KEY]) ? found[OUTBOX_KEY] : [];
}

async function writeOutbox(items) {
  await chrome.storage.local.set({[OUTBOX_KEY]:items});
}

async function enqueueCapture(message) {
  const items = await readOutbox();
  if (!items.some((x) => x.transaction_id === message.transaction_id)) {
    items.push(message);
    await writeOutbox(items);
  }
}

async function removeCapture(transactionId) {
  const items = await readOutbox();
  const next = items.filter((x) => x.transaction_id !== transactionId);
  if (next.length !== items.length) await writeOutbox(next);
}

async function performCapture(message) {
  const site = message.site;
  return bridgeRequest(site, "/v1/capture", (client, auth) => ({
    contract_version:CONTRACT_VERSION,
    transaction_id:message.transaction_id,
    client,
    memory_space:auth.defaultMemorySpace,
    execution_context:executionBySite(site),
    session_id:message.session_id,
    turn_id:message.turn_id,
    idempotency_key:`capture:${message.transaction_id}`,
    turn:{
      user_text:message.user_text,
      assistant_text:message.assistant_text,
      injected_memory_ids:message.injected_memory_ids || [],
      explicit_remember_request:!!message.explicit_remember_request,
    },
  }));
}

async function drainCaptureOutbox() {
  const items = await readOutbox();
  for (const message of items) {
    try {
      await performCapture(message);
      await removeCapture(message.transaction_id);
      diagnostic.lastEvent = "CAPTURE_REPLAY_COMPLETED";
      diagnostic.lastTransactionId = message.transaction_id;
      diagnostic.captureResult = "PASS";
    } catch (_) {
      // Keep the item. Idempotency on transaction_id makes replay safe.
    }
  }
}

const diagnostic = {
  lastEvent:null,
  lastTransactionId:null,
  recallResult:null,
  captureResult:null,
  credentialPresent:false,
  runtimeBuildId:null,
  runtimeGeneration:null,
};

chrome.runtime.onInstalled?.addListener(() => {
  chrome.alarms?.create("malm-capture-retry", {periodInMinutes:1});
  void drainCaptureOutbox();
});
chrome.runtime.onStartup?.addListener(() => {
  chrome.alarms?.create("malm-capture-retry", {periodInMinutes:1});
  void drainCaptureOutbox();
});
chrome.alarms?.onAlarm?.addListener((alarm) => {
  if (alarm?.name === "malm-capture-retry") void drainCaptureOutbox();
});
void drainCaptureOutbox();

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || typeof message.type !== "string") return false;

  if (message.type === "MALM_CONTENT_READY") {
    diagnostic.lastEvent = "CONTENT_SCRIPT_READY";
    diagnostic.runtimeBuildId = message.build_id || null;
    diagnostic.runtimeGeneration = message.generation || null;
    sendResponse({ok:true});
    return false;
  }

  if (message.type === "MALM_BEFORE_SEND") {
    (async () => {
      const site = message.site;
      const result = await bridgeRequest(site, "/v1/recall", (client, auth) => ({
        contract_version:CONTRACT_VERSION,
        transaction_id:message.transaction_id,
        client,
        memory_space:auth.defaultMemorySpace,
        execution_context:executionBySite(site),
        session_id:message.session_id,
        turn_id:message.turn_id,
        query:{user_text:message.user_text, scopes:auth.scopes || ["user"], max_items:12},
      }));
      diagnostic.lastEvent = "RECALL_COMPLETED";
      diagnostic.lastTransactionId = message.transaction_id;
      diagnostic.recallResult = "PASS";
      diagnostic.credentialPresent = true;
      sendResponse({ok:true,items:result.items || [],memory_context_available:result.memory_context_available});
    })().catch((err) => {
      diagnostic.lastEvent = "RECALL_FAILED";
      diagnostic.lastTransactionId = message.transaction_id;
      diagnostic.recallResult = "FAIL";
      sendResponse({ok:false,error:String(err?.message || err),code:err?.code || null});
    });
    return true;
  }

  if (message.type === "MALM_AFTER_RESPONSE") {
    (async () => {
      await enqueueCapture(message);
      try {
        const result = await performCapture(message);
        await removeCapture(message.transaction_id);
        diagnostic.lastEvent = "CAPTURE_COMPLETED";
        diagnostic.lastTransactionId = message.transaction_id;
        diagnostic.captureResult = "PASS";
        diagnostic.credentialPresent = true;
        sendResponse({ok:true,queued:false,result});
      } catch (err) {
        diagnostic.lastEvent = "CAPTURE_QUEUED";
        diagnostic.lastTransactionId = message.transaction_id;
        diagnostic.captureResult = "QUEUED";
        sendResponse({ok:true,queued:true,error:String(err?.message || err),code:err?.code || null});
      }
    })();
    return true;
  }

  if (message.type === "MALM_DIAGNOSTICS") {
    readOutbox().then((items) => sendResponse({...diagnostic,captureOutboxSize:items.length}));
    return true;
  }

  // Deliberately no message type that returns the credential.
  return false;
});
