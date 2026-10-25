# Generic Browser Adapter v1

Provider-neutral MV3 browser adapter for Multi-AI Local Bridge.

## Built-in sites

- ChatGPT web
- Grok web

The core is site-neutral. New sites implement the Browser Adapter Contract and do not reimplement memory/auth logic.

## Data flow

```text
SEND_INTENT
→ service worker auto-provisions credential if needed
→ /v1/recall
→ site adapter injects recalled local context
→ release original AI send once
→ observe assistant response
→ durable Capture outbox
→ /v1/capture
→ Local Shared Memory
```

## Credential rule

The page/content script never receives a Bridge token. Tokens live only in extension-owned service-worker storage. The Bridge stores only token hashes.

## Extension identity

`manifest.key` produces the stable unpacked-extension identity documented in `config/extension-identity.json`. The Bridge can load that identity file directly, so normal installation does not require copying an extension ID into configuration.

## Runtime status

Automated tests prove Browser Core semantics, service-worker bootstrap/Recall/Capture behavior, credential rotation, durable Capture outbox, stale-generation ownership, and real Bridge HTTP cross-model sharing.

A Chromium executable is available in the build environment, but environment policy blocks navigation to both public AI sites and loopback test pages with `ERR_BLOCKED_BY_ADMINISTRATOR`. Therefore actual page-level Chromium injection remains `LIVE_UNPROVEN` here and must be accepted on an unrestricted deployment browser.
