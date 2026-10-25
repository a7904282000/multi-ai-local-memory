# Storage Contract v1

**Status:** Stable interface  
**Contract version:** `1.0`

## 1. Purpose

A Storage Adapter maps the Bridge's canonical memory model to a concrete local backend.

Examples:
- Obsidian vault;
- plain Markdown directory;
- SQLite;
- encrypted local database;
- future user-owned store.

The Storage Adapter persists canonical records. It does not decide what is worth remembering.

## 2. Required operations

A v1 adapter MUST implement the semantic equivalent of:

```text
capabilities() -> StorageCapabilities

search(query, filters, limit) -> MemoryAtom[]

get(memory_id) -> MemoryAtom | NOT_FOUND

commit(atom, idempotency_key, expected_revision?) -> CommitResult

supersede(old_memory_id, new_atom, idempotency_key, expected_revision?) -> CommitResult

open_conflict(atom_ids, metadata, idempotency_key) -> ConflictResult

append_audit(event, idempotency_key?) -> AuditResult

health() -> StorageHealth
```

Implementations MAY expose these as functions, RPC, SQL, files, or plugin calls. The Bridge sees only the semantic contract.

## 3. Canonical Memory Atom

The canonical atom MUST include:

```text
memory_id
kind
namespace
subject
key
content
verification_status
lifecycle_status
sensitivity
confidence
provenance
created_at
updated_at
revision
```

Optional:
- tags;
- supersedes;
- conflict_group_id;
- expiry;
- structured_value;
- project_id.

`content` is the human-readable memory. `structured_value` may hold machine-readable data when useful.

## 4. Status separation

Verification and lifecycle are separate dimensions.

Verification:

```text
VERIFIED
UNVERIFIED
```

Lifecycle:

```text
ACTIVE
SUPERSEDED
CONFLICT
TOMBSTONED
```

An adapter MUST NOT overload one field to represent both.

## 5. Search semantics

Search MUST:
- operate only within authorized namespaces;
- return canonical atoms;
- preserve memory_id and revision;
- allow filtering out `SUPERSEDED` and `TOMBSTONED`;
- allow conflict-aware retrieval;
- support deterministic result limits.

Search MAY use:
- keyword search;
- embeddings;
- metadata indexes;
- database full-text search;
- a hybrid.

Ranking implementation is not part of the Storage Contract.

## 6. Commit semantics

`commit` MUST be atomic for one canonical atom.

It MUST:
- preserve idempotency;
- return the final memory_id and revision;
- support compare-and-swap behavior when `expected_revision` is supplied;
- refuse unauthorized paths/namespaces;
- never silently overwrite a conflicting newer revision.

## 7. Supersession

Supersession MUST preserve history.

A storage adapter MUST NOT physically destroy the previous canonical atom merely because a newer value exists.

At minimum:
- old atom → `SUPERSEDED`;
- new atom → `ACTIVE`;
- link new atom to old atom via provenance/supersedes.

## 8. Conflict storage

A conflict MUST preserve all competing atoms until resolved.

The adapter MUST support a shared `conflict_group_id` or equivalent durable relation.

## 9. Audit separation

Audit events are not memory atoms.

Adapters MAY store audit in the same physical database/file tree, but the logical namespace MUST remain separate and audit records MUST NOT appear in ordinary recall searches.

## 10. Raw archive separation

If raw transcript archival is enabled, it MUST be a separate logical collection from long-term memory.

A raw archive entry MUST NOT become recallable merely because it exists.

## 11. Path neutrality

The Bridge contract must remain valid if storage moves from:

```text
Obsidian → SQLite
Markdown → encrypted DB
one vault → another vault
```

Therefore a storage adapter MUST NOT leak:
- filesystem paths;
- note filenames;
- table names;
- storage-engine-specific primary keys

as required client-facing semantics.

## 12. Storage capabilities

An adapter MUST report at least:

```text
adapter_name
adapter_version
transactional_writes
compare_and_swap
full_text_search
semantic_search
raw_archive
audit_log
encryption_at_rest
```

The Bridge MUST feature-detect optional behavior.

## 13. Failure model

Canonical storage failures:

```text
NOT_FOUND
REVISION_CONFLICT
IDEMPOTENCY_CONFLICT
UNAUTHORIZED_SCOPE
READ_FAILURE
WRITE_FAILURE
UNAVAILABLE
CORRUPT_RECORD
```

Errors MUST preserve enough boundary information for the Bridge to distinguish storage failure from policy, client, or authentication failure.

## 14. Storage acceptance

A storage adapter is v1-compliant only if tests prove:

```text
create atom
→ read atom
→ search atom
→ retry same commit without duplicate
→ update with expected revision
→ reject stale expected revision
→ supersede while preserving history
→ maintain conflict set
→ keep audit outside recall
→ keep raw archive outside recall
```

## 15. Shared Memory Space Partitioning

Every canonical Memory Atom MUST carry `memory_space_id`.

`memory_space_id` is the cross-client/cross-model ownership boundary. Storage adapters MUST support filtering by memory space and MUST NOT substitute `client_id`, model ID, agent ID, device ID, note file, or application name as the ownership boundary.

## 16. Bidirectional Memory-Software Sync Extension

A memory software adapter that advertises bidirectional sync MUST provide the semantic equivalent of:

```text
sync_capabilities() -> SyncPeerCapabilities
pull_changes(memory_space_id, cursor, limit) -> ChangeBatch
push_atoms(memory_space_id, canonical_atoms, idempotency_key) -> PushResult
sync_health() -> SyncHealth
```

`pull_changes` converts native application edits into canonical change proposals.
`push_atoms` converts canonical Memory Atoms into the native application's representation.

The adapter owns format translation. The Bridge owns:
- canonical identity;
- authorization;
- conflict detection;
- revision policy;
- fan-in/fan-out;
- loop prevention/idempotency.

An externally edited canonical item MUST include the canonical revision it was based on. A stale/concurrent edit MUST open a conflict instead of silently overwriting newer SSOT state.

## 17. Default and Alternative Backends

The reference product defaults to an Obsidian adapter.

A conforming Bridge MUST remain storage-neutral. Other adapters may target Markdown, SQLite, local databases, knowledge tools, or other user-controlled memory applications.

Multiple bidirectional peers MAY be connected simultaneously:

```text
Memory Software A --pull/push--\
                              Local SSOT -- clients/models/agents
Memory Software B --pull/push--/
```

A change imported from Software A MUST be eligible for fan-out to Software B and for recall by every authorized model/client in the same memory space.

## 18. Provider-Native Memory as a Sync Peer

Where an AI provider exposes a supported native-memory read/write API, an adapter MAY represent it as a sync peer under the same canonical contract.

Absence of such a provider API is not a Storage Contract failure; it only means that provider-native private memory cannot be bidirectionally mirrored. The local SSOT remains the cross-model source of truth.

