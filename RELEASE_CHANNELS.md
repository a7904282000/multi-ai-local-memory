# Release Channels

## Recommended release structure

The product has two deliverables:

1. **Skill package** — shared memory rules/workflow used by supported AI agents.
2. **Local runtime** — Local Bridge + browser adapter + memory/storage adapters that actually read/write the user's machine.

Do not market the Skill alone as if it can bypass a product's local-access sandbox.

## Canonical public distribution

### 1. Source / universal release
Publish one canonical repository and versioned release containing:
- `multi-ai-local-memory` Skill;
- Local Bridge runtime;
- browser-extension package/source;
- OpenClaw adapter;
- checksums;
- changelog;
- user-acceptance instructions.

This is the SSOT for all downstream distribution channels.

### 2. ChatGPT
Official uploaded Skills are the preferred Skill channel when the user's ChatGPT workspace supports Skills.

Install path should be documented as:
`Plugins -> Skills -> Create -> Upload from computer`.

If the account/workspace does not expose uploaded Skills, do not claim the Skill is installed. The web runtime may still use the browser adapter + Local Bridge, but that is a separate integration path.

### 3. Grok
For **Grok Build**, publish the same Skill folder for:
- user scope: `~/.grok/skills/multi-ai-local-memory/`
- project scope: `.grok/skills/multi-ai-local-memory/`
- later: a Grok plugin/marketplace package if desired.

Consumer Grok web and Grok Build are different surfaces. Browser-web memory integration is handled by the browser adapter; do not imply a Grok Build Skill was installed into consumer web Grok.

### 4. OpenClaw
Publish:
- workspace Skill: `<workspace>/skills/multi-ai-local-memory/`
- optional ClawHub listing;
- OpenClaw runtime adapter/plugin bundled with the Local Bridge installer.

OpenClaw is the default intermediary, not a required dependency.

### 5. Browser web adapters
For ordinary ChatGPT/Grok web users, publish the browser adapter through the normal browser-extension store channel.

Browser-required installation confirmation is an external security approval. After that confirmation, credentials, memory_space, Bridge URL, and synchronization should auto-provision.

### 6. Local Bridge
Recommended release channels:
- packaged desktop installer / signed executable for nontechnical users;
- versioned source release;
- optional Python package for developers/automation.

The consumer path should prefer the desktop installer, not `pip`.

## Release tiers

### Public Beta
Use while real-world ChatGPT/Grok/browser/provider compatibility is being validated by users.

Requirements:
- automated local self-test passes;
- no known data-loss issue;
- immutable source archive contract active;
- users receive the simple acceptance flow in `USER_ACCEPTANCE.md`.

### Stable
Promote only after:
- enough real-user acceptance reports pass on supported platforms;
- browser-extension store distribution is live;
- update/rollback path is exercised;
- no unresolved data-loss/security blocker remains.

## Versioning

Version these separately when necessary:
- Skill;
- Local Bridge runtime;
- browser adapter;
- OpenClaw adapter.

A release manifest should record the compatible component versions so one component cannot silently drift from the others.
