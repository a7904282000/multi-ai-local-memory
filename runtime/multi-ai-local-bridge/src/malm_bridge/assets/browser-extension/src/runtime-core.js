(() => {
  "use strict";

  const g = globalThis;
  const registry = new Map();

  function uuid() {
    if (g.crypto?.randomUUID) return g.crypto.randomUUID();
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
  }

  function textOf(node) {
    if (!node) return "";
    if (typeof node.value === "string") return node.value;
    return (node.innerText || node.textContent || "").trim();
  }

  function registerSiteAdapter(adapter) {
    if (!adapter || !adapter.id || typeof adapter.matches !== "function") {
      throw new Error("Invalid MALM site adapter");
    }
    registry.set(adapter.id, adapter);
  }

  function resolveSiteAdapter() {
    for (const adapter of registry.values()) {
      try {
        if (adapter.matches(location)) return adapter;
      } catch (_) {}
    }
    return null;
  }

  function makeMemoryEnvelope(items) {
    if (!Array.isArray(items) || items.length === 0) return "";
    const lines = items.map((item) => `- [${item.memory_id}] ${item.content}`);
    return [
      "<local_memory_context>",
      "Use these user-owned local memories only when relevant. Do not claim they are new user statements in this turn.",
      ...lines,
      "</local_memory_context>",
    ].join("\n");
  }

  function createRuntime(adapter, chromeApi = g.chrome) {
    let disabled = false;
    let activeTurn = null;
    const buildId = (() => {
      try { return chromeApi.runtime.getManifest?.().version || "dev"; } catch (_) { return "dev"; }
    })();
    const generation = `${adapter.id}:${buildId}:${uuid()}`;
    let replayGuard = false;
    let responseObserver = null;
    let responseTimer = null;
    const sessionId = (() => {
      try {
        const k = "malm.session_id";
        let v = sessionStorage.getItem(k);
        if (!v) { v = uuid(); sessionStorage.setItem(k, v); }
        return v;
      } catch (_) {
        return uuid();
      }
    })();

    function disable(reason) {
      disabled = true;
      if (responseObserver) responseObserver.disconnect();
      responseObserver = null;
      if (responseTimer) clearTimeout(responseTimer);
      responseTimer = null;
      try { document.documentElement.dataset.malmDisabled = reason || "true"; } catch (_) {}
    }

    async function sendToWorker(message) {
      if (disabled) throw new Error("MALM runtime disabled");
      try {
        const result = await chromeApi.runtime.sendMessage(message);
        if (chromeApi.runtime.lastError) throw new Error(chromeApi.runtime.lastError.message);
        return result;
      } catch (err) {
        const msg = String(err?.message || err || "");
        if (/Extension context invalidated/i.test(msg)) disable("extension-context-invalidated");
        throw err;
      }
    }

    function beginResponseObservation(turn) {
      if (responseObserver) responseObserver.disconnect();
      let lastText = "";
      const settle = () => {
        if (responseTimer) clearTimeout(responseTimer);
        responseTimer = setTimeout(async () => {
          if (!ownsDocument()) { disable("stale-generation"); return; }
          if (disabled || !activeTurn || activeTurn.transaction_id !== turn.transaction_id) return;
          const text = adapter.latestAssistantText?.() || "";
          if (!text || text !== lastText) {
            lastText = text;
            if (text) settle();
            return;
          }
          try {
            const response = await sendToWorker({
              type: "MALM_AFTER_RESPONSE",
              transaction_id: turn.transaction_id,
              turn_id: turn.turn_id,
              session_id: sessionId,
              user_text: turn.original_user_text,
              assistant_text: text,
              injected_memory_ids: turn.injected_memory_ids,
              explicit_remember_request: adapter.isExplicitRememberRequest?.(turn.original_user_text) || false,
              site: adapter.identity(),
            });
            if (response?.ok) {
              activeTurn = null;
              responseObserver?.disconnect();
              responseObserver = null;
            }
          } catch (_) {
            // Capture errors are reported by worker diagnostics; do not break the page.
          }
        }, 1200);
      };
      responseObserver = new MutationObserver(settle);
      responseObserver.observe(document.documentElement, {subtree:true, childList:true, characterData:true});
      settle();
    }

    function ownsDocument() {
      try { return document.documentElement.dataset.malmRuntimeGeneration === generation; }
      catch (_) { return false; }
    }

    function mustFailClosed(code) {
      return ["AUTH_FAILED", "FORBIDDEN", "UNSUPPORTED_VERSION"].includes(code);
    }

    async function handleSendIntent(event, source) {
      if (!ownsDocument()) { disable("stale-generation"); return; }
      if (disabled || replayGuard || activeTurn) return;
      const composer = adapter.currentComposer?.(event);
      if (!composer) return;
      const original = adapter.getComposerText ? adapter.getComposerText(composer) : textOf(composer);
      if (!original.trim()) return;

      event.preventDefault?.();
      event.stopImmediatePropagation?.();
      event.stopPropagation?.();

      const transaction_id = uuid();
      const turn_id = transaction_id;
      activeTurn = {
        transaction_id,
        turn_id,
        original_user_text: original,
        injected_memory_ids: [],
        source,
      };

      try {
        const recall = await sendToWorker({
          type: "MALM_BEFORE_SEND",
          transaction_id,
          turn_id,
          session_id: sessionId,
          user_text: original,
          site: adapter.identity(),
        });
        if (!recall?.ok) {
          if (mustFailClosed(recall?.code)) {
            activeTurn = null;
            try { document.documentElement.dataset.malmLastError = recall.code; } catch (_) {}
            return;
          }
          throw new Error(recall?.error || "Recall failed");
        }
        const items = recall.items || [];
        activeTurn.injected_memory_ids = items.map((x) => x.memory_id).filter(Boolean);
        const envelope = makeMemoryEnvelope(items);
        if (envelope) {
          adapter.applyRecallContext?.(composer, original, envelope);
        }
        replayGuard = true;
        try {
          adapter.releaseSend?.(composer, source);
        } finally {
          queueMicrotask(() => { replayGuard = false; });
        }
        beginResponseObservation(activeTurn);
      } catch (_) {
        // Fail-open for ordinary bridge unavailability: user's AI request still proceeds.
        // Auth/security errors are kept in worker diagnostics but must not lose the user's turn.
        replayGuard = true;
        try { adapter.releaseSend?.(composer, source); }
        finally { queueMicrotask(() => { replayGuard = false; }); }
        activeTurn = null;
      }
    }

    function install() {
      if (disabled) return;
      // Always claim a new generation. Older listeners remain physically attached to the
      // page, but their ownership check makes them inert before they can create a turn.
      document.documentElement.dataset.malmRuntimeOwner = adapter.id;
      document.documentElement.dataset.malmRuntimeBuild = buildId;
      document.documentElement.dataset.malmRuntimeGeneration = generation;

      document.addEventListener("submit", (event) => {
        if (adapter.isSubmitEvent?.(event)) void handleSendIntent(event, "SUBMIT");
      }, true);
      document.addEventListener("click", (event) => {
        if (adapter.isSendClick?.(event)) void handleSendIntent(event, "CLICK");
      }, true);
      document.addEventListener("keydown", (event) => {
        if (adapter.isSendKeydown?.(event)) void handleSendIntent(event, "KEYDOWN");
      }, true);

      void sendToWorker({type:"MALM_CONTENT_READY", site: adapter.identity(), build_id:buildId, generation}).catch(() => {});
    }

    return {install, disable, handleSendIntent, sessionId, generation, buildId, ownsDocument};
  }

  g.MALM_BROWSER = {
    registerSiteAdapter,
    resolveSiteAdapter,
    createRuntime,
    makeMemoryEnvelope,
    textOf,
  };
})();
