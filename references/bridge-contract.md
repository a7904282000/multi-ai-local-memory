# Logical Bridge Contract

Hosts may expose different tool names. Map them to these logical operations.

## health

Purpose: verify that the local memory capability is reachable and identify the active SSOT/version without returning memory content.

Suggested response fields:

- `status`
- `ssot_status`
- `schema_version`
- `server_version`

## recall

Suggested request:

```json
{
  "client_id": "chatgpt",
  "conversation_id": "...",
  "turn_id": "...",
  "query": "current user request",
  "project": "optional",
  "max_items": 20
}
```

Suggested response:

```json
{
  "status": "ok",
  "source": "local-ssot",
  "source_version": "...",
  "items": []
}
```

Recall must not return obsolete items as current facts unless historical context was requested.

## capture

Suggested request:

```json
{
  "client_id": "grok",
  "conversation_id": "...",
  "turn_id": "...",
  "transaction_id": "...",
  "original_user_text": "...",
  "assistant_summary": "...",
  "candidates": []
}
```

The local writer applies policy, conflict checks, and idempotency.

Automatically injected recall text must not be accepted as original user text.

## session close

Optional. Use for final state flush or conversation/session metadata when the implementation needs it.

## Authentication

Transport security is implementation-specific. Requirements:

- no secret in page content,
- no secret in logs,
- no broad unauthenticated write endpoint,
- least privilege,
- local-only exposure where possible,
- clear client identity.

## Failure semantics

- `PASS`: operation is proven successful.
- `FAIL`: operation was attempted and proven unsuccessful.
- `UNPROVEN`: evidence is insufficient.
- `BLOCKED`: required capability is unavailable.
