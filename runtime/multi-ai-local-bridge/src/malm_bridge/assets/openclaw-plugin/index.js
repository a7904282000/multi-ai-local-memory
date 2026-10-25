import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";

function loadProfile(api) {
  const configured = api.pluginConfig?.profilePath;
  const envPath = process.env.MALM_PROFILE_PATH;
  const candidates = [
    configured,
    envPath,
    process.platform === "win32" && process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, "Multi-AI Local Memory", "openclaw-client.json") : null,
    process.platform === "darwin" ? path.join(os.homedir(), "Library", "Application Support", "Multi-AI Local Memory", "openclaw-client.json") : null,
    path.join(process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share"), "multi-ai-local-memory", "openclaw-client.json")
  ].filter(Boolean);
  const p = candidates.find(x => fs.existsSync(x));
  if (!p) throw new Error("MALM OpenClaw profile not found");
  const profile = JSON.parse(fs.readFileSync(p, "utf8"));
  profile.__profilePath = p;
  return profile;
}

function bearer(profile) {
  return {"Authorization": `Bearer ${profile.credential}`, "Content-Type": "application/json"};
}

async function post(profile, route, payload) {
  let r;
  try {
    r = await fetch(profile.bridge_url.replace(/\/$/, "") + route, {
      method: "POST", headers: bearer(profile), body: JSON.stringify(payload)
    });
  } catch (error) {
    const e = new Error(`MALM ${route} unavailable`);
    e.kind = "availability";
    e.cause = error;
    throw e;
  }
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = new Error(`MALM ${route} HTTP ${r.status}`);
    e.status = r.status;
    e.kind = (r.status === 401 || r.status === 403 || r.status === 400) ? "security" : "availability";
    e.body = body;
    throw e;
  }
  return body;
}

function lastUserText(event) {
  if (typeof event?.prompt === "string" && event.prompt.trim()) return event.prompt;
  const messages = Array.isArray(event?.messages) ? event.messages : [];
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m?.role !== "user") continue;
    if (typeof m.content === "string") return m.content;
    if (Array.isArray(m.content)) {
      const text = m.content.filter(x => x?.type === "text" && typeof x.text === "string").map(x => x.text).join("\n");
      if (text) return text;
    }
  }
  return "";
}

function lastAssistantText(event) {
  const messages = Array.isArray(event?.messages) ? event.messages : [];
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m?.role !== "assistant") continue;
    if (typeof m.content === "string") return m.content;
    if (Array.isArray(m.content)) {
      const text = m.content.filter(x => x?.type === "text" && typeof x.text === "string").map(x => x.text).join("\n");
      if (text) return text;
    }
  }
  return "";
}

function formatRecall(items) {
  if (!Array.isArray(items) || items.length === 0) return "";
  const lines = items.map((x, i) => `${i + 1}. [${x.kind || "memory"}] ${x.content || ""}`);
  return `<relevant-local-memory>\n${lines.join("\n")}\n</relevant-local-memory>`;
}

function outboxPath(profile) {
  return path.join(path.dirname(profile.__profilePath), "openclaw-capture-outbox.json");
}

function loadOutbox(profile) {
  const p = outboxPath(profile);
  if (!fs.existsSync(p)) return [];
  try {
    const x = JSON.parse(fs.readFileSync(p, "utf8"));
    return Array.isArray(x) ? x : [];
  } catch {
    return [];
  }
}

function saveOutbox(profile, rows) {
  const p = outboxPath(profile);
  const tmp = `${p}.${crypto.randomUUID()}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(rows, null, 2) + "\n", {mode: 0o600});
  fs.renameSync(tmp, p);
  try { fs.chmodSync(p, 0o600); } catch {}
}

function enqueueCapture(profile, payload) {
  const rows = loadOutbox(profile);
  if (!rows.some(x => x?.idempotency_key === payload.idempotency_key)) rows.push(payload);
  saveOutbox(profile, rows);
}

async function flushOutbox(profile) {
  const rows = loadOutbox(profile);
  if (!rows.length) return;
  const keep = [];
  for (const payload of rows) {
    try {
      await post(profile, "/v1/capture", payload);
    } catch (e) {
      keep.push(payload);
      // Authentication/config failures cannot self-heal by hammering the Bridge.
      if (e.kind === "security") break;
    }
  }
  saveOutbox(profile, keep);
}

export default {
  id: "multi-ai-local-memory",
  name: "Multi-AI Local Memory",
  register(api) {
    const turns = new Map();
    const securityFailures = new Map();

    api.on("gateway_start", async () => {
      try { await flushOutbox(loadProfile(api)); } catch {}
    }, {priority: 50});

    api.on("before_prompt_build", async (event, ctx) => {
      const userText = lastUserText(event);
      if (!userText) return;
      const profile = loadProfile(api);
      await flushOutbox(profile).catch(() => {});
      const tx = crypto.randomUUID();
      const session = ctx?.sessionKey || ctx?.runId || "openclaw-session";
      const turn = ctx?.runId || tx;
      const payload = {
        contract_version: "1.0",
        transaction_id: tx,
        client: profile.client,
        memory_space: profile.memory_space,
        execution_context: {
          surface: "agent", provider: ctx?.provider || null, product: "openclaw",
          model: ctx?.model || null, agent_id: ctx?.agentId || null,
          intermediary_chain: [{type: "agent-runtime", id: "openclaw"}]
        },
        session_id: session,
        turn_id: turn,
        query: {user_text: userText, scopes: ["user", "project"], max_items: api.pluginConfig?.recallMaxItems || 12}
      };
      try {
        const recalled = await post(profile, "/v1/recall", payload);
        turns.set(ctx?.runId || turn, {
          tx, session, turn, userText,
          injected: (recalled.items || []).map(x => x.memory_id).filter(Boolean), profile
        });
        securityFailures.delete(ctx?.runId || turn);
        const prependContext = formatRecall(recalled.items);
        return prependContext ? {prependContext} : undefined;
      } catch (e) {
        // Availability is fail-open; security/contract failures are gated in before_agent_run.
        if (e.kind === "security") securityFailures.set(ctx?.runId || turn, String(e.message || e));
        turns.set(ctx?.runId || turn, {tx, session, turn, userText, injected: [], profile});
        return undefined;
      }
    }, {priority: 50});

    api.on("before_agent_run", async (_event, ctx) => {
      const key = ctx?.runId;
      const failure = securityFailures.get(key);
      if (!failure) return {outcome: "pass"};
      securityFailures.delete(key);
      turns.delete(key);
      return {outcome: "block", reason: "local-memory-auth-failed", message: "Local memory authorization failed. Repair the local bridge connection before continuing."};
    }, {priority: 50});

    api.on("agent_end", async (event, ctx) => {
      const key = ctx?.runId || event?.runId;
      const prior = turns.get(key);
      if (!prior) return;
      turns.delete(key);
      securityFailures.delete(key);
      const assistantText = lastAssistantText(event);
      if (!assistantText) return;
      const payload = {
        contract_version: "1.0",
        transaction_id: prior.tx,
        client: prior.profile.client,
        memory_space: prior.profile.memory_space,
        execution_context: {
          surface: "agent", provider: ctx?.provider || null, product: "openclaw",
          model: ctx?.model || null, agent_id: ctx?.agentId || null,
          intermediary_chain: [{type: "agent-runtime", id: "openclaw"}]
        },
        session_id: prior.session,
        turn_id: prior.turn,
        idempotency_key: `capture:${prior.tx}`,
        turn: {
          user_text: prior.userText,
          assistant_text: assistantText,
          injected_memory_ids: prior.injected,
          explicit_remember_request: /(?:remember|記住|記得|remember this)/iu.test(prior.userText)
        }
      };
      enqueueCapture(prior.profile, payload);
      await flushOutbox(prior.profile).catch(() => {});
    }, {priority: 50});
  }
};
