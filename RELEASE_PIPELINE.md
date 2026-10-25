# Release Pipeline

```text
Source repository / release SSOT
        |
        +-- Skill package
        |    +-- ChatGPT uploaded Skill (where supported)
        |    +-- Grok Build skill folder / marketplace path
        |    +-- OpenClaw workspace skill / ClawHub
        |
        +-- Local runtime
             +-- desktop installer
             +-- Local Bridge
             +-- Browser Adapter
             +-- OpenClaw Adapter
             +-- Obsidian default adapter
             +-- other storage/agent adapters
```

## Public Beta flow

1. Build Skill + runtime from the same tagged source.
2. Run static/unit/conformance/local E2E gates.
3. Generate checksums and release manifest.
4. Publish canonical source/release.
5. Publish Skill to each supported Skill channel.
6. Publish browser adapter to browser-extension distribution.
7. Users install and run the simple live acceptance flow.
8. Collect only structured PASS/FAIL evidence and first-bad-boundary diagnostics.
9. Fix compatibility bugs without changing the source-preservation/shared-memory invariants.
10. Promote to Stable when supported environments have enough passing live acceptance.

## Non-negotiable release gates

- original migrated memory preserved byte-for-byte;
- no model/client/agent-specific memory silo;
- one shared local `memory_space`;
- automatic credential provisioning;
- automatic recall/capture where the surface supports hooks;
- bidirectional local-memory sync;
- durable retry/idempotency;
- user memory survives update/uninstall by default;
- no secrets stored as long-term memory;
- installation success is never inferred only from UI.
