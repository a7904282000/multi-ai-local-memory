(() => {
  "use strict";
  const api = globalThis.MALM_BROWSER;

  function findComposer() {
    const candidates = [
      'textarea',
      '[contenteditable="true"][role="textbox"]',
      '[contenteditable="true"]',
    ];
    for (const sel of candidates) {
      const nodes = [...document.querySelectorAll(sel)].filter((n) => n.offsetParent !== null && !n.closest('[aria-hidden="true"]'));
      if (nodes.length) return nodes[nodes.length - 1];
    }
    return null;
  }

  function composerForm(el) { return el?.closest?.("form") || null; }
  function setText(el, text) {
    el.focus();
    if ("value" in el) {
      const proto = Object.getPrototypeOf(el);
      const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
      if (setter) setter.call(el, text); else el.value = text;
    } else {
      el.textContent = text;
    }
    el.dispatchEvent(new InputEvent("input", {bubbles:true, inputType:"insertText", data:text}));
  }

  api.registerSiteAdapter({
    id: "grok",
    matches: (loc) => /(^|\.)grok\.com$/.test(loc.hostname) || ((/^x\.com$/.test(loc.hostname) || /(^|\.)twitter\.com$/.test(loc.hostname)) && loc.pathname.startsWith("/i/grok")),
    identity: () => ({client_id:"grok-web", client_type:"grok-web", provider:"xai", product:"grok", surface:"web"}),
    currentComposer: () => findComposer(),
    getComposerText: (el) => api.textOf(el),
    isSubmitEvent: (e) => {
      const c = findComposer(); const f = composerForm(c); return !!f && e.target === f;
    },
    isSendClick: (e) => {
      const c = findComposer(); const f = composerForm(c); if (!c || !f) return false;
      const b = e.target?.closest?.('button[type="submit"]'); return !!b && f.contains(b);
    },
    isSendKeydown: (e) => e.key === "Enter" && !e.shiftKey && !e.isComposing && e.target === findComposer(),
    applyRecallContext: (composer, original, envelope) => setText(composer, `${envelope}\n\n<current_user_message>\n${original}\n</current_user_message>`),
    releaseSend: (composer) => {
      const f = composerForm(composer); const b = f?.querySelector?.('button[type="submit"]');
      if (b && !b.disabled) b.click(); else f?.requestSubmit?.();
    },
    latestAssistantText: () => {
      const candidates = [...document.querySelectorAll('article, [data-testid*="message"], [class*="message"]')]
        .filter((n) => n.offsetParent !== null);
      return candidates.length ? api.textOf(candidates[candidates.length - 1]) : "";
    },
    isExplicitRememberRequest: (text) => /(?:請|帮|幫)?(?:記住|记住|remember(?:\b|$))/i.test(text),
  });
})();
