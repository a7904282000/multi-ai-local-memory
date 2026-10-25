(() => {
  "use strict";
  const api = globalThis.MALM_BROWSER;
  const FORM = 'form[data-chatgpt-composer][data-composer-placement="thread"]';
  const INPUT = `${FORM} [contenteditable="true"][role="textbox"][data-composer-markdown]`;
  const SEND = `${FORM} button[type="submit"]`;
  const ASSISTANT = '[data-markdown-text-style="assistant-message"]';

  function setContentEditable(el, text) {
    el.focus();
    el.textContent = text;
    el.dispatchEvent(new InputEvent("input", {bubbles:true, inputType:"insertText", data:text}));
  }

  api.registerSiteAdapter({
    id: "chatgpt",
    matches: (loc) => /(^|\.)chatgpt\.com$/.test(loc.hostname) || /(^|\.)chat\.openai\.com$/.test(loc.hostname),
    identity: () => ({client_id:"chatgpt-web", client_type:"chatgpt-web", provider:"openai", product:"chatgpt", surface:"web"}),
    currentComposer: () => document.querySelector(INPUT),
    getComposerText: (el) => api.textOf(el),
    isSubmitEvent: (e) => !!e.target?.matches?.(FORM),
    isSendClick: (e) => !!e.target?.closest?.(SEND),
    isSendKeydown: (e) => e.key === "Enter" && !e.shiftKey && !e.isComposing && !!e.target?.closest?.(INPUT),
    applyRecallContext: (composer, original, envelope) => setContentEditable(composer, `${envelope}\n\n<current_user_message>\n${original}\n</current_user_message>`),
    releaseSend: (composer) => {
      const form = composer.closest(FORM);
      const button = form?.querySelector('button[type="submit"]');
      if (button && !button.disabled) button.click();
      else form?.requestSubmit?.();
    },
    latestAssistantText: () => {
      const nodes = document.querySelectorAll(ASSISTANT);
      return nodes.length ? api.textOf(nodes[nodes.length - 1]) : "";
    },
    isExplicitRememberRequest: (text) => /(?:請|帮|幫)?(?:記住|记住|remember(?:\b|$))/i.test(text),
  });
})();
