(() => {
  "use strict";
  const api = globalThis.MALM_BROWSER;
  if (!api || !globalThis.chrome?.runtime?.sendMessage) return;
  const adapter = api.resolveSiteAdapter();
  if (!adapter) return;
  const runtime = api.createRuntime(adapter, globalThis.chrome);
  runtime.install();
})();
