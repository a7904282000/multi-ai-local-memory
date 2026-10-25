# Browser Adapter Contract v1

Status: implementation contract for `multi-ai-local-bridge` 0.3.x.

## Purpose

A Browser Adapter connects a supported web AI surface to the provider-neutral Client Contract without giving the webpage direct access to Local Bridge credentials or local storage.

## Boundary

```text
Web AI page
  ↕ site adapter (DOM/runtime only)
Content script
  ↕ extension messaging (no credential)
Extension service worker
  ↕ authenticated Local Bridge HTTP
Local Bridge
```

## Required invariants

1. The webpage and content script MUST NOT receive the Bridge credential.
2. The service worker owns browser credentials in extension-owned storage.
3. Provisioning MUST be automatic after installation and MUST NOT require manual token copy.
4. A packaged extension identity MUST be stable; manual extension-ID maintenance is not a normal operating step.
5. `submit`, send-button `click`, and Enter-style send paths MUST converge to one semantic `SEND_INTENT`.
6. One user action MUST create one transaction and release the AI send exactly once.
7. Shift+Enter/newline and IME composition MUST NOT be treated as send intent.
8. SPA/React node replacement MUST NOT invalidate delegated send observation.
9. A new extension generation supersedes prior content-script generations. Stale generations self-disable before creating transactions.
10. Recall occurs before send. Auth/authorization/version failures fail closed; ordinary Bridge/storage unavailability may fail open.
11. Capture occurs after the assistant response and MUST enter a durable extension outbox before delivery.
12. Capture replay uses the same transaction/idempotency identity and MUST NOT create duplicate memories.
13. Recalled memory IDs MUST be returned during capture so the Bridge can block recall→model→capture feedback loops.
14. Site/model identity is provenance only; it MUST NOT partition a shared `memory_space`.

## Site adapter interface

A built-in or future web model adapter supplies the semantic equivalent of:

```text
id
matches(location)
identity()
currentComposer(event?)
getComposerText(composer)
isSubmitEvent(event)
isSendClick(event)
isSendKeydown(event)
applyRecallContext(composer, originalText, memoryEnvelope)
releaseSend(composer, source)
latestAssistantText()
isExplicitRememberRequest(text)
```

The Browser Core owns transaction/dedup/retry semantics. A site adapter MUST NOT implement its own memory store or credential system.

## Recall injection

The provider-neutral fallback is a per-turn prompt envelope containing recalled local memory plus the original user message. A provider-specific invisible/request-level hook MAY replace the fallback when a stable supported mechanism exists.

The capture event MUST always preserve the original user text and recalled memory IDs, not the injected envelope.

## Provisioning

Browser bootstrap is a separate loopback control-plane route:

```text
POST /bootstrap/v1/browser
```

It requires:
- loopback caller;
- exact allow-listed extension Origin;
- allowed browser client type.

The Bridge returns a one-time plaintext credential to the extension service worker and stores only its hash. Re-bootstrap rotates the credential for the same browser client instance.

The bootstrap response also supplies authorized scopes and the default `memory_space`; these values MUST NOT be hard-coded per user into the extension source.

## Extensibility

ChatGPT and Grok are built-in site adapters. Additional web models are added as site adapters. Supporting a new site may also require browser host permission; permission acquisition is an installation/runtime concern, not a new memory architecture.

Desktop AI applications that do not expose a browser-extension surface use the same Client Contract through a native/agent adapter instead of this Browser Adapter.
