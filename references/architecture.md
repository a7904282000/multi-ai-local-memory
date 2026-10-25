# Architecture

## Goal

Many AI clients should share one local source of truth instead of maintaining isolated memories.

```text
AI clients
  ChatGPT
  Grok
  OpenClaw
  others
      |
      v
common recall/capture contract
      |
      v
local access layer
  - direct files (when supported)
  - local bridge/plugin/MCP
      |
      v
LOCAL MEMORY SSOT
```

## Separation of responsibilities

### Skill
Defines:
- when to recall,
- what to capture,
- conflict rules,
- memory schemas,
- audit and E2E requirements.

### Local access layer
Provides:
- authenticated or trusted local reads/writes,
- concurrency control,
- idempotent writes,
- local path isolation,
- transport between web clients and local storage when needed.

### SSOT
Stores durable memory and provenance.

## Recommended logical namespaces

The physical layout is configurable. A reasonable logical model is:

- `PROFILE` — durable user facts/preferences.
- `RULES` — explicit interaction/workflow rules.
- `PROJECTS` — project facts, decisions, status, blockers.
- `CONFLICTS` — unresolved competing facts.
- `AUDIT` — transaction evidence, not recall memory.
- `RAW_ARCHIVE` — optional raw chats, disabled by default.

Do not require these exact folder names if the user's existing local system already has a stable layout.

## Multi-client identity

Every caller should use a stable client identity such as:

- `chatgpt`
- `grok`
- `openclaw`

Optionally add installation/device scope, but avoid user secrets in IDs.
