---
name: multi-ai-local-memory
description: Build and operate one local shared long-term memory across any supported AI model, web/desktop client, agent, intermediary, and local memory application, with bidirectional sync, filtered capture, recall, conflict handling, zero-config deployment, and auditable writes.
---

# Multi-AI Local Memory

Use this skill when one or more AI models, web/desktop clients, agents, intermediaries, or local memory applications need to share one user-owned local long-term memory. ChatGPT, Grok, OpenClaw, and Obsidian are default/reference adapters only; none is a required architectural dependency.

The objective is not to make each AI maintain its own memory. The objective is:

`any model × any client × any agent × any intermediary × any supported memory software -> one shared local memory_space -> bidirectional recall/capture/sync -> auditable updates`

## 1. Non-negotiable architecture

1. The local shared `memory_space` is the authoritative memory identity and single source of truth (SSOT).
2. Model, provider, client, surface, device, agent, intermediary, and memory application are provenance/authorization dimensions only; they MUST NOT partition memory.
3. Every connected endpoint reads and writes through the same memory contract.
4. Do not create a separate private memory database per AI unless it is only a disposable cache.
5. A cache must never outrank the local SSOT.
6. OpenClaw is the default intermediary, not a required intermediary.
7. Obsidian is the default local memory application, not a required storage backend.
8. Any supported memory application must participate bidirectionally whenever its interface permits. A read-only integration must be labeled read-only.
9. A skill alone does not magically provide local-machine access. Use one of:
   - a local file/shell tool,
   - a local memory bridge/plugin/app,
   - an MCP/tool connector that exposes equivalent recall/capture actions.
10. If no usable local-memory capability exists, report `BLOCKED`; never pretend recall or capture succeeded.
11. Provider-private native memory is separate from shared local memory. Synchronize native provider memory only when an official readable/writable interface exists; otherwise provide equivalent behavior through local recall-before-use and capture-after-use without claiming the provider's private memory was modified.

## 2. Supported operating modes

### Always-on mode

Preferred when the host supports hooks or a browser/agent bridge.

Before a user turn is released:

`user text -> recall -> relevant local memory -> model context`

After the assistant response is final:

`original user text + assistant result -> capture filter -> local memory SSOT`

### Explicit skill mode

When the host cannot hook every turn automatically:

- Run recall when the user asks to remember, continue, resume, compare with prior work, or when prior personal/project context materially changes the answer.
- Run capture after durable new information appears.
- Never claim this is zero-touch always-on sync unless the platform integration actually invokes the skill or memory bridge on every relevant turn.

## 3. Recall policy

Recall only what is relevant to the current task.

Priority order:

1. Explicit user rules and constraints.
2. Current project decisions and current status.
3. User facts/preferences that materially change the answer.
4. Recent unresolved tasks and blockers.
5. Older background context.

Exclude by default:

- obsolete facts,
- superseded decisions,
- unrelated projects,
- low-value conversational filler,
- unresolved conflicts unless the conflict itself matters.

Never treat recalled memory as higher authority than the user's current message.

## 4. Capture policy

`Capture` is not the same as `long-term memory`.

Do not save every message as a durable memory atom.

Save information with future value, including:

- stable preferences,
- explicit rules,
- confirmed decisions,
- project state,
- important facts,
- recurring workflow preferences,
- durable environment/configuration facts,
- unresolved blockers that matter next time,
- information the user explicitly asks to remember.

Do not promote to long-term memory by default:

- greetings,
- acknowledgements,
- filler such as "ok" or "next",
- one-off wording with no future value,
- automatically injected recall context,
- assistant guesses or unverified inferences.

If the user explicitly says to remember a fact, treat it as a high-priority capture candidate subject to the configured local policy.

## 5. Sensitive memory policy

Default public-package policy:

`sensitive_memory = explicit_only`

Meaning:

- Do not silently turn sensitive personal data into durable memory.
- If the user explicitly asks the local memory system to remember it and local policy allows it, it may be stored locally.
- Never put secrets, passwords, API keys, authentication tokens, or private keys into long-term memory.
- Never echo secrets into logs or audit records.

The memory owner may change this policy in local configuration.

## 6. Memory atom contract

When creating or updating a durable memory, use the logical fields defined in `schemas/memory-atom.schema.json`.

Minimum semantic fields:

- `category`
- `project`
- `fact`
- `status`
- `source_type`
- `source_agent`
- `last_known_date`
- `confidence`
- `mutable`
- `sensitivity`
- `notes`

Allowed status values:

- `VERIFIED`
- `UNVERIFIED`
- `OBSOLETE`
- `CONFLICT`

Do not silently convert `UNVERIFIED` into `VERIFIED`.

## 7. Multi-AI conflict handling

When ChatGPT, Grok, OpenClaw, or another client supplies conflicting durable facts:

1. Do not overwrite silently.
2. Compare dates, evidence, source type, and user confirmation.
3. If one item clearly supersedes another, mark the old one `OBSOLETE` and link the successor.
4. If the conflict cannot be resolved, preserve both and mark the logical state `CONFLICT`.
5. Prefer a direct current user correction over older derived memory.
6. Never resolve a conflict merely because one AI model sounds more confident.

## 8. Mutable facts

For facts that naturally change (project status, software version, job, location, device state, current plan):

- keep the newest verified state current,
- preserve provenance,
- supersede rather than erase history when history matters,
- do not return obsolete values as current recall.

## 9. Transaction and idempotency contract

For always-on integrations, one real user turn should have one transaction identity from recall through capture.

Minimum logical chain:

1. `SEND_INTENT`
2. `TRANSACTION_CREATED`
3. `BEFORE_SEND`
4. `RECALL`
5. exactly one model send/release
6. `AFTER_RESPONSE`
7. `CAPTURE`
8. final local-memory write
9. duplicate effective write count = 0

Use idempotency keys or equivalent transaction identity so retries do not create duplicate memories.

Do not use message text alone as turn identity; users may intentionally send identical text twice.

## 10. Audit policy

Audit proves the memory system worked; audit is not itself long-term memory.

Audit records may include:

- transaction id,
- client id,
- conversation/turn identifiers when available,
- timestamps,
- recall/capture status,
- source version/hash,
- final write status,
- duplicate count,
- blocking guard/error code.

Audit records must not include:

- credentials,
- bearer tokens,
- Authorization headers,
- private keys,
- recalled secret content.

## 10.5. Existing source-memory migration is lossless

When migrating existing memories from ChatGPT, Grok, another model/provider, an Agent, a legacy memory system, Obsidian, or any other source, preserve the accessible original source **100% verbatim in a local immutable source archive before any derived processing**.

Required invariant:

```text
Source Memory
→ byte-for-byte Local Source Archive
→ optional derived index / MemoryAtom / semantic view
```

Never migrate by summarizing, purifying, merging, rewriting, normalizing, or discarding the original. Derived semantic indexes may improve recall but are rebuildable views and may never replace the source archive.

For file/export-based sources, require:

```text
SOURCE_BYTES_PRESERVED=100%
SOURCE_FILE_COUNT_PRESERVED=100%
SOURCE_SHA256_MATCH=100%
SOURCE_RELATIVE_PATH_PRESERVED=YES
SOURCE_ORIGINAL_MUTATED=NO
DERIVED_VIEW_REPLACES_SOURCE=NO
```

If a provider exposes only part of its private native memory, preserve 100% of the accessible export and explicitly report the inaccessible remainder as unsupported/unknown. Do not falsely claim that hidden provider-private memory was migrated.

This rule concerns **existing memory migration**. It does not change the separate rule that ordinary new conversations are not automatically all promoted into long-term memory.

## 10.6. Derived semantic memory is disposable

Semantic recall, embeddings, clustering, aliases, summaries, ranking features, and indexes are **derived views only**. They MUST NOT rewrite, merge, normalize, delete, or replace authoritative source memory.

Required flow:

`authoritative local memory / immutable source archive -> disposable semantic index -> ranked pointers -> fetch current source record -> model context`

Before serving a semantic hit, validate the current source identity/revision/fingerprint. If the derived view is stale, rebuild it instead of serving stale content. Deleting or corrupting all semantic data must be recoverable by rebuilding from the local SSOT without loss.

Minimum acceptance:

```text
SOURCE_ORIGINAL_MUTATED=NO
DERIVED_INDEX_DELETE_SAFE=PASS
DERIVED_INDEX_REBUILD=PASS
DERIVED_INDEX_CORRUPTION_RECOVERY=PASS
STALE_DERIVED_RESULT_BLOCKED=PASS
RECALL_RETURNS_AUTHORITATIVE_SOURCE=PASS
```

A future embedding model may replace the ranking implementation, but it may never change these invariants.

## 11. Raw conversation archive policy

Raw conversation archive and long-term memory are separate products.

Default:

`raw_archive = false`

If the owner enables raw archive, keep it in a separate namespace from long-term memory so recall is not polluted by every utterance.

Never infer that "capture all turns" means "recall all turns forever".

## 12. Tool / bridge discovery

Before memory operations:

1. Identify whether the host exposes a local memory capability.
2. Prefer an existing configured capability over inventing a new one.
3. Map host-specific tool names to the logical operations:
   - health
   - recall
   - capture
   - session close (optional)
4. Follow `references/bridge-contract.md` for payload semantics.
5. If only read access exists, allow recall but mark capture `BLOCKED`.
6. If only write access exists, never pretend recall happened.

## 13. E2E acceptance

Do not claim shared-memory success because an answer "looks personalized".

Do not claim capture success because a similar string exists in a local file.

A live E2E PASS requires correlated evidence for the same turn. Use `references/e2e-acceptance.md`.

## 14. Failure handling

Use these states:

- `PASS`
- `FAIL`
- `UNPROVEN`
- `BLOCKED`

Evidence precedence:

`Raw Runtime > local SSOT content/provenance > source contract > test/report > UI summary`

Do not use progressive blind repair. When a live memory path fails, build the smallest complete failure tree for the remaining unknown boundary and collect the evidence in one pass.

Do not reopen previously confirmed PASS boundaries without new raw regression evidence.

## 15. Output behavior

When memory materially affects an answer, use it naturally. Do not dump the memory store unless the user asks.

When a memory operation is requested, report concise status, for example:

`RECALL=PASS`
`CAPTURE=PASS`
`CONFLICT=NONE`

If blocked, state the missing capability exactly.

## 16. Platform portability

This package follows the portable `SKILL.md` / Agent Skills pattern. Platform-specific installation notes are in `references/platform-install.md`.

The memory semantics in this file must remain platform-neutral. ChatGPT, Grok, OpenClaw, and future clients should share the same SSOT and schemas rather than forking memory logic per platform.

## 17. Required outcome: universal shared memory

This is a required product outcome, not an optional integration pattern.

A compliant deployment MUST support one shared local memory across all connected endpoints:

```text
Any Model
× Any Web/Desktop/API Client
× Any Agent
× Any Intermediary
× Any Supported Local Memory Software
        ↕
One Shared Local memory_space
```

Required interoperability behavior:

- Model A writes durable memory -> Model B can recall it.
- Web and desktop clients for the same owner/workspace do not create separate memory silos.
- Agent and intermediary changes do not partition memory.
- A supported local memory application can update memory -> the Bridge reconciles it -> other connected models/clients receive the updated state.
- A model/agent write can propagate to the default memory application and other configured peers.
- Concurrent edits preserve provenance and resolve through revision/conflict rules; never silently lose one side.

The following are forbidden as final architecture:

- `one model = one memory database`;
- `one client surface = one memory database`;
- `OpenClaw owns the memory`;
- `Obsidian is the only possible backend`;
- manual copy/paste as the synchronization mechanism.

## 18. Zero-Config Deployment Contract

The target user experience is:

**Install once -> all connected models, clients, agents, intermediaries, and local memory applications share the same local memory automatically.**

Default stack:

```text
Local authority: Local Bridge
Memory application: Obsidian
Intermediary: OpenClaw
```

Defaults are replaceable adapters, not hard dependencies.

### Installer/deployment responsibilities

The deployment workflow MUST automatically, whenever the host platform permits:

1. Install and configure the Local Bridge.
2. Discover or create the local memory SSOT.
3. Prefer Obsidian when available; otherwise create a safe local default.
4. Create or recover the shared `memory_space`.
5. Provision client identities and credentials automatically.
6. Keep reusable plaintext credentials out of page context and long-term memory.
7. Configure the default intermediary/agent when present.
8. Configure startup/daemon persistence.
9. Configure automatic bidirectional synchronization.
10. Configure durable capture retry/outbox behavior.
11. Configure crash/restart recovery and peer reconciliation.
12. Configure health/diagnostic reporting.
13. Run a post-install E2E acceptance test.
14. Preserve stable owner/workspace identity across reinstall/upgrade.

Normal users MUST NOT be required to manually:

```text
copy API tokens
copy extension IDs
edit JSON/YAML
choose internal ports
configure localhost URLs
configure memory_space IDs
configure vault paths
configure agent credentials
run sync commands
restart services for ordinary operation
repair normal upgrades
```

### External security approvals

If the browser or operating system requires an explicit security confirmation, one unavoidable confirmation is allowed. Example: browser-controlled `Add extension`.

That approval MUST be reported as:

`EXTERNAL_USER_APPROVAL=<exact unavoidable action>`

It MUST NOT be misrepresented as ordinary configuration. After approval, provisioning must continue automatically.

### Completion gate

Do not call a deployment "one-click", "zero-config", or "complete" merely because components installed. Completion requires correlated E2E evidence. At minimum:

```text
ZERO_CONFIG_BOOTSTRAP=PASS
LOCAL_BRIDGE_AUTOSTART=PASS
SHARED_MEMORY_SPACE=PASS
AUTOMATIC_CREDENTIAL_PROVISIONING=PASS
MODEL_A_TO_MODEL_B=PASS
MODEL_TO_MEMORY_SOFTWARE=PASS
MEMORY_SOFTWARE_TO_MODEL=PASS
BIDIRECTIONAL_SYNC=PASS
RESTART_RECOVERY=PASS
DUPLICATE_WRITE=0
MANUAL_MEMORY_SYNC_REQUIRED=NO
MANUAL_TOKEN_COPY_REQUIRED=NO
MANUAL_EXTENSION_ID_REQUIRED=NO
```

The minimum live acceptance path is:

```text
Model A writes durable memory
-> local SSOT commits it
-> configured memory software contains it
-> Model B recalls it
-> memory software is externally modified
-> Local Bridge detects/reconciles it
-> Model A or another client recalls the updated value
```

At least one cross-model path and one reverse memory-software-to-model path MUST pass.

## 19. Native provider-memory synchronization

Shared Local Memory and provider-private native memory are different systems.

If a provider exposes an official read/write memory interface, an adapter MAY synchronize provider-native memory with the local SSOT.

If no such interface exists:

- do not claim native provider memory was changed;
- perform local Recall before the interaction;
- perform durable Capture after the interaction;
- preserve the same shared `memory_space` across models so practical memory continuity remains consistent.

## 20. Deployment governance

When implementing or repairing this skill's system:

1. First define the real end-to-end objective and remaining unknown boundaries.
2. Do not substitute component tests for the deployment completion gate.
3. Prefer structural removal of manual configuration over documentation telling the user what to configure.
4. Any unavoidable recurring manual step is a deployment defect unless imposed by an external security boundary.
5. Do not reopen locked PASS boundaries without new raw regression evidence.
6. Evidence precedence remains: `Raw Runtime > local SSOT/provenance > contract > verifier/test > UI`.
7. Final status must be one of `PASS`, `FAIL`, `UNPROVEN`, or `BLOCKED`.

## Public release and user acceptance

This package may be released as **Public Beta** before every third-party web surface has been live-tested by the publisher, provided local/conformance gates pass and there is no known data-loss/security blocker.

Final website/provider compatibility is verified in the user's own environment using `USER_ACCEPTANCE.md`.

Do not ask ordinary users to perform engineering diagnostics. The expected user experience is:

1. install the package / Local Bridge;
2. approve the browser extension only when the browser itself requires confirmation;
3. use two connected AI surfaces plus the local memory app for the simple acceptance flow;
4. receive a compact PASS/FAIL result.

When local execution is available, prefer the bundled zero-config installer:

`python {baseDir}/scripts/install.py`

If the current AI surface cannot execute on the user's local machine, report `BLOCKED` for local installation and use the appropriate release channel described in `RELEASE_CHANNELS.md`. Never claim local installation or synchronization succeeded without runtime evidence.

Release channels and provider surfaces are adapters around the same invariant: one user-owned local `memory_space`.
