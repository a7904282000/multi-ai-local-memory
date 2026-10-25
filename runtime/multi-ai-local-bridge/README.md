# Multi-AI Local Bridge

Provider-neutral local shared-memory bridge for multiple AI models, clients, agents, intermediaries, and local memory applications.

## Current implementation status (0.7.0)

- Bridge / Client / Storage contracts: PASS
- Shared memory spaces / cross-model semantics: PASS
- SQLite durable SSOT: PASS
- Obsidian bidirectional adapter: PASS
- Continuous sync runtime: PASS
- Persistent client credentials: PASS
- Generic Browser Adapter core: PASS (simulated/runtime harness)
- Automatic browser credential provisioning: PASS
- Durable browser Capture outbox: PASS
- Built-in ChatGPT/Grok site adapters: implemented; live public-site acceptance UNPROVEN in this restricted build environment
- Generic Agent / Intermediary Adapter contract + runtime-neutral Python adapter: PASS
- OpenClaw reference adapter: implemented and tested against the same Client Contract
- Zero-config release installer lifecycle (install/update/migration/backup/restore/uninstall/post-install self-test): PASS in automated conformance tests
- Immutable byte-for-byte source-memory archive for migrations/imports: PASS
- Derived Semantic Memory v1: PASS (disposable/rebuildable local index; authoritative source revalidation)
- Conservative durable Capture classifier: PASS (preferences/rules/confirmed decisions/project state; sensitive explicit-only; secrets prohibited)
- Real OS/browser public deployment acceptance: pending

## Product target

> Any number of models, on web / desktop / API / agent surfaces, through any intermediary, share one local memory space and can bidirectionally read, write, update, and synchronize it with supported local memory software.

Defaults are configuration choices, not architectural dependencies:

```text
default intermediary = OpenClaw
default local memory software = Obsidian
```

Canonical architecture:

```text
ChatGPT Web/Desktop -----\
Grok Web/Desktop ---------\
Any Model/API -------------+--> Client Adapter --> Local Bridge --> shared memory_space
Any Agent ----------------/                           |                  |
OpenClaw/default relay ---/                           |                  +--> Obsidian (default)
Other intermediary ------/                            |                  +--> SQLite
                                                     |                  +--> other memory software adapters
                                                     +<---- two-way sync+
```

Models, clients, agents, devices and intermediaries are provenance/authentication peers. They MUST NOT partition memory. `memory_space` is the shared identity boundary.

Provider-native memory can be imported/exported only where the provider exposes a supported interface. When no such interface exists, the local shared memory remains authoritative and is recalled/captured through the client adapter.

## Implemented

- Stable v1 Bridge / Client / Storage contracts.
- Stable v1 Agent / Intermediary Adapter contract.
- Shared `memory_space` identity independent of model/client/agent/intermediary.
- Provider-neutral Bridge Core.
- Recall / Capture / Session Close HTTP API.
- Conservative long-term memory policy (`Capture != save every conversation`).
- Transaction audit separated from recallable memory.
- Conflict and supersession semantics.
- Idempotent storage writes.
- Durable bridge operation/idempotency state across daemon restarts.
- In-memory reference StorageAdapter.
- Transactional SQLite StorageAdapter.
- Obsidian Markdown StorageAdapter.
- Obsidian external/manual edit detection with canonical revision advancement.
- Obsidian as either primary local SSOT or bidirectional sync peer.
- Generic bidirectional memory-software sync coordinator.
- Production continuous sync runtime with durable peer cursors and startup recovery.
- Cross-platform polling filesystem watcher used as an early-wakeup signal; periodic reconciliation remains authoritative.
- Primary-SSOT watcher support, including Obsidian as the default primary memory application.
- Peer failure isolation and multi-memory-space health aggregation.
- Deterministic conflict replay after crashes; cursor pagination cannot skip unseen changes.
- Combined HTTP Bridge + Sync Runtime service using one shared StorageAdapter instance.
- Capture-to-sync wake notification that cannot turn an already committed capture into a failure.
- Concurrent peer edit conflict preservation (no silent last-write-wins).
- Persistent per-client credential registry; plaintext bearer tokens are not stored.
- Credential binding to client id/type/instance and revocation.
- Provider-neutral Python HTTP Client SDK.
- Runtime-neutral AgentMemoryAdapter with durable capture outbox.
- OpenClaw reference wrapper over the same shared-memory semantics; OpenClaw remains optional.
- Cross-model, cross-client, cross-agent/intermediary conformance tests.

## Zero-config release lifecycle implemented

The release lifecycle now exposes one installer entry point for:

```text
install
update
backup
restore
uninstall
doctor
self-test
```

Release behavior is backup-first and identity-preserving:

- install state migrates v1 -> v2 without changing `owner_id`, `installation_id`, or `memory_space_id`;
- update creates and verifies a backup before changing generated assets/config;
- update preserves configured primary storage, peers, sync settings, and future/custom adapter fields instead of resetting them to defaults;
- restore contains its own local recovery targets and does not depend on a possibly-corrupted current `service.json`;
- uninstall removes application/runtime state but preserves user memory and immutable source archives by default;
- post-install E2E uses the real installed code + browser identity but an isolated temporary memory space, so installer test data never pollutes the user's real memory;
- the selected real vault receives only a byte write/read/delete probe during self-test.

### Lossless source-memory migration

Existing memories imported from a model/provider/agent/legacy memory system are preserved before any derived processing:

```text
Source export / existing memory
        ↓
Immutable _SourceArchive (byte-for-byte)
        ↓
optional MemoryAtom / keyword index / semantic index / derived view
```

Required migration gate:

```text
SOURCE_BYTES_PRESERVED = 100%
SOURCE_FILE_COUNT_PRESERVED = 100%
SOURCE_SHA256_MATCH = 100%
SOURCE_RELATIVE_PATH_PRESERVED = YES
SOURCE_ORIGINAL_MUTATED = NO
DERIVED_VIEW_REPLACES_SOURCE = NO
```

This is distinct from raw conversation archival: ordinary new chat turns are still not automatically promoted into long-term memory.

## Explicit invariants

```text
ALL_CONVERSATIONS_ARE_MEMORY = NO
CAPTURE_EQUALS_MEMORY_COMMIT = NO
RAW_ARCHIVE_IS_LONG_TERM_MEMORY = NO
SOURCE_MEMORY_MIGRATION_IS_BYTE_EXACT = YES
DERIVED_VIEW_REPLACES_ORIGINAL_SOURCE = NO
UNINSTALL_PRESERVES_USER_MEMORY_BY_DEFAULT = YES
CLIENT_DIRECT_STORAGE_ACCESS = NO
MODEL_PARTITIONS_MEMORY = NO
AGENT_PARTITIONS_MEMORY = NO
INTERMEDIARY_PARTITIONS_MEMORY = NO
SECRET_IN_MEMORY = FORBIDDEN
SILENT_CONFLICT_OVERWRITE = FORBIDDEN
```

## Current verified test boundary

```text
PYTHON_UNIT_CONFORMANCE_HTTP_SYNC_AGENT_RELEASE_TESTS = 122/122 PASS
OPENCLAW_REFERENCE_PLUGIN_TESTS = 3/3 PASS
BROWSER_RUNTIME_CORE = PASS
BROWSER_SERVICE_WORKER = PASS
BROWSER_CAPTURE_OUTBOX = PASS
BROWSER_FAILURE_POLICY = PASS
CORE_OPENCLAW_COUPLING = PASS
RESOURCE_WARNING_GATE = PASS
```

Coverage includes:

- ChatGPT-style client writes -> Grok-style client reads the same shared memory over real HTTP;
- bridge restart -> capture retry returns the original result without duplicate memory;
- Obsidian Markdown persistence and restart;
- manual Obsidian body edit -> revision advance -> model recall;
- Obsidian -> other memory software fan-out;
- other memory software -> SSOT -> other model recall;
- concurrent external edits -> explicit conflict;
- SQLite durability / CAS / atomic supersession;
- credential hash-at-rest / identity binding / revocation.
- continuous periodic model-write fan-out without manual sync calls;
- filesystem-watcher wakeup for external Obsidian edits;
- Obsidian-as-primary external edit -> downstream peer convergence;
- downtime/startup recovery with durable cursors;
- crash replay of conflict events without duplicate conflicts;
- one broken peer cannot block healthy peers;
- combined service E2E: ChatGPT-style capture -> Obsidian -> human edit -> Grok-style recall.
- Generic AgentMemoryAdapter: recall/capture share one transaction and durable capture survives adapter restart;
- Agent A -> Agent B, Agent -> Browser, and Browser -> Agent all share the same memory space;
- OpenClaw wrapper passes recall/capture, durable outbox replay, and security fail-closed tests while remaining outside Bridge Core.
- release lifecycle: exact backup/restore, config-independent disaster recovery, identity-preserving update, uninstall-preserves-memory;
- existing source-memory import: binary/text byte-for-byte copy, SHA-256 verification, no source mutation, immutable source manifest;
- update preserves non-default primary/peer configuration rather than silently resetting adapters;
- post-install E2E is non-destructive to the user's actual memory store.
- derived semantic index deletion/rebuild/corruption recovery; stale revision rejection; authoritative SSOT re-fetch; SourceArchive SHA preservation.
- automatic durable capture classification vs ordinary/filler/sensitive/secret cases; automatic captures remain source-text faithful.

## Not release-complete yet

- Semantic memory extractor/classifier beyond the conservative deterministic baseline.
- Native-client automatic provisioning transports beyond the implemented browser bootstrap and OpenClaw profile provisioning.
- Live public-site acceptance for ChatGPT/Grok browser adapters in unrestricted user Chrome.
- Additional third-party Agent/Intermediary wrappers beyond the OpenClaw reference adapter.
- Provider-native-memory adapters where provider APIs permit them.
- Real OS lifecycle acceptance for autostart/update/uninstall on Windows/macOS/Linux.
- Security hardening and final end-to-end release acceptance.

## Release rule

The project must not be called production-ready merely because source tests pass. A release requires real runtime evidence across the supported deployment paths, including install -> provision -> recall -> model turn -> capture -> local storage -> external edit -> cross-client recall -> restart/update recovery.

## Derived Semantic Memory v1

Semantic recall is implemented as a disposable index over the authoritative storage. It never rewrites source memory or `_SourceArchive`; every hit is re-fetched from SSOT and revision/SHA validated before being returned. Deleting or corrupting the derived index is safe because it is automatically rebuildable.

Current baseline uses deterministic local hashed lexical/CJK n-gram features with no network dependency. The interface is intentionally replaceable by a future embedding provider without changing source memory or the Bridge/Storage contracts.
