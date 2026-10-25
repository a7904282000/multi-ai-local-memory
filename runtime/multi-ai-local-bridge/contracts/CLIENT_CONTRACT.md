# Client Contract v1

**Status:** Stable interface  
**Contract version:** `1.0`

## 1. Purpose

A Client is any adapter that connects an AI interaction surface to the Local Bridge.

Examples:
- ChatGPT browser extension;
- Grok browser extension;
- OpenClaw native client;
- CLI or desktop app;
- future AI adapters.

A client MUST NOT read or write the memory store directly.

## 2. Required client lifecycle

For each conversational turn:

```text
1. Observe user send intent.
2. Create a unique transaction_id and turn_id.
3. Call /v1/recall before releasing/sending the turn when recall is enabled.
4. Inject only the returned recall context.
5. Release the user turn exactly once.
6. Observe the final assistant response.
7. Call /v1/capture exactly once for that completed turn.
8. Preserve the transaction_id across the entire flow.
```

## 3. Client identity

Each client instance MUST have:

```text
client_id
client_type
client_instance_id
```

`client_type` examples:

```text
chatgpt-web
grok-web
openclaw
cli
desktop
```

The bridge decides authorization. The client MUST NOT self-assert elevated permissions.

## 4. Recall request

Minimum request:

```json
{
  "contract_version": "1.0",
  "transaction_id": "uuid",
  "client": {
    "client_id": "logical-client",
    "client_type": "chatgpt-web",
    "client_instance_id": "stable-local-instance"
  },
  "session_id": "session",
  "turn_id": "turn",
  "query": {
    "user_text": "current user message",
    "conversation_summary": null,
    "scopes": ["user", "project"],
    "max_items": 12
  }
}
```

The client MUST send the exact user text needed for recall. It MUST NOT secretly rewrite the user's meaning before recall.

## 5. Recall response

Minimum response:

```json
{
  "contract_version": "1.0",
  "transaction_id": "uuid",
  "memory_context_available": true,
  "items": [
    {
      "memory_id": "mem_...",
      "kind": "preference",
      "content": "...",
      "provenance": {
        "source_type": "local-memory",
        "revision": 3
      }
    }
  ]
}
```

The client MUST preserve `memory_id`s of injected recall items and submit them during capture, so the bridge can prevent recall→model→capture feedback loops.

## 6. Capture request

Minimum request:

```json
{
  "contract_version": "1.0",
  "transaction_id": "uuid",
  "client": {
    "client_id": "logical-client",
    "client_type": "chatgpt-web",
    "client_instance_id": "stable-local-instance"
  },
  "session_id": "session",
  "turn_id": "turn",
  "idempotency_key": "capture:uuid",
  "turn": {
    "user_text": "exact user message",
    "assistant_text": "final assistant response",
    "injected_memory_ids": ["mem_123"],
    "explicit_remember_request": false
  }
}
```

The client MAY provide additional structured metadata, but memory policy remains bridge-owned.

## 7. Capture response

Minimum response:

```json
{
  "contract_version": "1.0",
  "transaction_id": "uuid",
  "decision": "DROP",
  "committed_memory_ids": [],
  "conflict_ids": [],
  "duplicate_count": 0
}
```

A client MUST distinguish:
- `DROP` — valid, nothing worth saving;
- `COMMIT` — durable memory written;
- `CONFLICT` — unresolved durable conflict;
- request failure.

## 8. Send-intent requirements for browser clients

Browser adapters SHOULD use delegated/current-DOM observation rather than binding only to one initial composer node.

If the surface supports multiple send paths, they SHOULD converge into one semantic event:

```text
SEND_INTENT
```

Typical sources:
- form submit;
- send-button click;
- keyboard Enter.

Multiple signals for one user action MUST yield exactly one transaction and exactly one release.

Browser clients MUST safely handle:
- React/SPA DOM replacement;
- extension/runtime reload;
- stale content-script context;
- duplicate injection/reconciliation;
- IME composition;
- Shift+Enter or equivalent newline behavior.

## 9. Context invalidation

A client whose extension/runtime context becomes invalid MUST self-disable and MUST NOT:
- create transactions;
- write memory;
- block the new runtime;
- throw uncontrolled repeated errors.

A newly valid client generation MUST be able to reconcile the current page without requiring daily manual refresh.

## 10. Client diagnostics

A client SHOULD expose safe diagnostics:

```text
runtime_build_id
contract_version
content_script_live
send_intent_source
transaction_created
recall_result
capture_result
last_transaction_id
```

Diagnostics MUST NOT expose secrets.

## 11. Prohibited client behavior

Clients MUST NOT:
- write files in the vault/store;
- embed storage paths into request semantics;
- decide conflict overwrite policy;
- save all conversation text as long-term memory by default;
- treat a successful AI response as proof that memory capture succeeded;
- use recalled memory as new evidence merely because the model repeated it.

## 12. Shared Memory Space

Every recall/capture turn MUST target an authorized `memory_space`.

The same `memory_space` MUST be usable by multiple simultaneous clients and models. `client_id`, `client_type`, provider, product, model, agent, and intermediary chain are **not** memory ownership boundaries.

A conforming client therefore treats local memory as shared state:

```text
before inference/response: recall from shared memory_space
completed turn: capture back to the same shared memory_space
```

This applies to web, desktop, API, CLI, and agent surfaces.

## 13. Model / Agent / Intermediary Neutrality

Clients SHOULD provide execution provenance:

```json
{
  "execution_context": {
    "surface": "web",
    "provider": "provider-name",
    "product": "product-name",
    "model": "model-id",
    "agent_id": "optional-agent",
    "intermediary_chain": [
      {"type": "agent", "id": "openclaw"}
    ]
  }
}
```

OpenClaw is the default/recommended intermediary for the reference distribution, but another intermediary or direct client MUST produce the same Bridge semantics.

A model switch inside the same client session MUST NOT create a new memory silo.

## 14. Native Provider Memory

A provider's private built-in memory is a separate optional sync peer.

Clients MUST NOT claim native-memory synchronization unless a supported provider interface actually confirms read/write. Regardless of provider-native memory availability, the shared local `memory_space` remains available to every integrated client.

