# Bridge Contract v1

**Status:** Stable interface  
**Contract version:** `1.0`

## 1. Purpose

The Local Bridge is the sole authority between AI clients and the local memory SSOT.

It MUST own:
- client authentication/authorization;
- transaction correlation;
- recall orchestration;
- capture policy;
- conflict/supersession logic;
- idempotency;
- audit events;
- storage-adapter invocation;
- capability reporting;
- diagnostics.

It MUST NOT require an AI client to understand a vault path, SQLite schema, Markdown layout, storage filename, or backend-specific identifier.

## 2. Stable application API

The v1 application surface is:

```text
GET  /v1/health
GET  /v1/capabilities
POST /v1/recall
POST /v1/capture
POST /v1/session/close
GET  /v1/diagnostics     # privileged/local-admin only
```

Client provisioning/authentication is a separate security boundary. Implementations MAY use OS keychain, native messaging, mTLS, Unix sockets, named pipes, extension bootstrap, or another secure local mechanism. The application API MUST NOT expose reusable plaintext credentials to arbitrary web pages.

## 3. Request identity

Every stateful turn MUST carry:

```text
client_id
session_id
turn_id
transaction_id
contract_version
```

`transaction_id` spans the complete logical turn:

```text
BEFORE_SEND
→ recall
→ AI send
→ AFTER_RESPONSE
→ capture
→ storage commit/drop/conflict
```

A retry of the same logical operation MUST preserve the same idempotency key.

## 4. Recall semantics

`POST /v1/recall`:

- MUST authenticate the client.
- MUST query the authoritative local SSOT through the Storage Contract.
- MUST return only memory relevant to the current request and permitted scopes.
- MUST include provenance identifiers for every recalled item.
- MUST NOT mutate long-term memory.
- MAY write audit metadata.
- MUST return an explicit empty result rather than invent memory.

A recall failure MUST never be reported as successful recall.

Availability policy:
- authentication/security failures: **fail closed**;
- ordinary backend unavailability: MAY allow the AI request to continue without memory, but MUST expose `memory_context_available=false`.

## 5. Capture semantics

`POST /v1/capture` records a completed conversational turn for memory evaluation.

Capture does **not** mean "save everything".

The bridge MUST classify the event into one of:

```text
DROP
CANDIDATE
COMMIT
CONFLICT
SUPERSEDE
REJECT
```

Examples normally eligible for long-term memory:
- stable user preference;
- explicit "remember this" request;
- durable rule/instruction;
- confirmed decision;
- project state/milestone;
- important durable fact.

Examples normally dropped:
- acknowledgments;
- transient small talk;
- one-off wording;
- "next";
- test noise;
- assistant boilerplate;
- recalled memory echoed back by the model.

The bridge MUST exclude injected recalled memory from being re-captured merely because the model repeated it.

## 6. Raw transcript separation

Raw conversation archive and long-term memory are separate products.

Default v1 behavior:

```text
raw_archive_enabled = false
```

If enabled, raw archive MUST use a separate namespace/store and MUST NOT automatically become recallable long-term memory.

## 7. Conflict and supersession

The bridge MUST NOT silently overwrite a conflicting durable fact.

A new observation may:
- confirm an active atom;
- create a candidate;
- supersede an old atom;
- open a conflict set;
- be rejected by policy.

Conflict resolution MUST preserve provenance.

## 8. Idempotency

The following operations MUST be idempotent:

- capture;
- session close;
- storage write/update;
- retryable audit append.

A repeated request with the same idempotency key and equivalent payload MUST return the original logical result without creating a duplicate memory.

Same text in two different user turns MUST NOT be deduplicated merely because text hashes match.

## 9. Audit

Audit is separate from memory.

Minimum event vocabulary:

```text
CLIENT_AUTHENTICATED
RECALL_STARTED
RECALL_COMPLETED
RECALL_FAILED
SEND_RELEASED
AFTER_RESPONSE
CAPTURE_STARTED
CAPTURE_CLASSIFIED
STORAGE_WRITE_STARTED
STORAGE_WRITE_COMMITTED
STORAGE_WRITE_FAILED
SESSION_CLOSED
```

Audit records SHOULD include:
- transaction_id;
- client_id;
- session_id;
- turn_id;
- event;
- timestamp;
- result/status;
- safe diagnostic metadata.

Audit MUST NOT include secrets.

## 10. Error model

Canonical error envelope:

```json
{
  "error": {
    "code": "AUTH_FAILED",
    "message": "human-readable summary",
    "retryable": false,
    "boundary": "CLIENT_AUTH",
    "transaction_id": "..."
  }
}
```

Stable error codes:

```text
INVALID_REQUEST
UNSUPPORTED_VERSION
AUTH_FAILED
FORBIDDEN
POLICY_REJECTED
NOT_FOUND
CONFLICT
IDEMPOTENCY_CONFLICT
STORAGE_UNAVAILABLE
STORAGE_FAILURE
BRIDGE_UNAVAILABLE
INTERNAL_ERROR
```

`DROP` is not an error.

## 11. Security invariants

The bridge MUST:
- bind credentials/capabilities to a specific trusted client identity;
- use least privilege;
- keep secrets out of memory/audit;
- reject arbitrary page origins from credential bootstrap;
- keep storage writes inside configured storage scope;
- support credential revocation/rotation;
- expose diagnostics without exposing secrets.

## 12. Observability and acceptance

The bridge MUST be able to prove, for one transaction:

```text
client send observed
→ transaction created
→ recall attempted/result
→ response observed
→ capture attempted/result
→ storage result
→ duplicate count
```

A UI status indicator is not authoritative when raw transaction evidence disagrees.

Evidence priority:

```text
Raw Runtime
> Protocol/Contract
> Verifier/Test
> UI
```

## 13. Capability discovery

`GET /v1/capabilities` MUST report at least:

```text
contract_version
bridge_version
recall
capture
session_close
diagnostics
raw_archive
storage_adapter
auth_mode
```

Clients MUST feature-detect optional capabilities rather than infer them from product name.

## 14. Shared Memory Fabric Invariant

The Bridge is a **multi-client, multi-model, multi-agent shared-memory fabric**.

A durable memory belongs to a `memory_space`, not to the client, model, agent, intermediary, or storage application that observed it.

Every recall/capture request MUST identify:

```text
memory_space.space_id
memory_space.owner_id
```

Client/model/agent identity is provenance and authorization context only.
It MUST NOT partition otherwise shared memory.

Therefore, when two authorized clients use the same `memory_space`:

```text
ChatGPT write -> Grok recall                 MUST be possible
Grok write -> ChatGPT recall                 MUST be possible
Web write -> Desktop recall                  MUST be possible
Agent A write -> Agent B recall              MUST be possible
Intermediary X -> Intermediary Y              MUST preserve semantics
```

The default intermediary MAY be OpenClaw, but the Bridge MUST NOT depend on OpenClaw-specific semantics.

## 15. Execution Provenance

Requests MAY carry an `execution_context` containing:

```text
surface
provider
product
model
agent_id
intermediary_chain[]
```

This metadata MUST be preserved as provenance where useful, but MUST NOT become the memory owner or a storage partition key.

## 16. Memory-Software Bidirectional Sync

The Bridge MUST support memory-software adapters that normalize external software changes to canonical Memory Atoms and accept canonical atoms back.

Default memory software: **Obsidian**.

Obsidian is a default adapter, not a hard dependency. A conforming implementation may use any local/user-controlled memory software that implements the Storage/Sync contract.

Required directionality for a bidirectional adapter:

```text
AI/Agent -> Bridge -> local SSOT -> Memory Software
Memory Software edit -> Adapter -> local SSOT -> all authorized AI/Agents
Memory Software A -> local SSOT -> Memory Software B
```

Concurrent external changes MUST preserve both values through the conflict model; last-writer-wins silent overwrite is forbidden by default.

## 17. Provider-Native Memory Boundary

The shared local memory is the authoritative cross-model memory.

If an AI provider exposes an official readable/writable native-memory interface, that provider memory MAY be connected as another sync peer.

If a provider does not expose such an interface, the Bridge MUST NOT claim that the provider's private internal memory was modified. The conformance guarantee in that case is:

```text
all integrated clients recall from and capture to the same local memory_space
```

This limitation MUST NOT prevent cross-model shared local memory.

