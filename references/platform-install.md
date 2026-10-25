# Platform Installation

The package uses one universal `SKILL.md`. Only installation differs by platform.

## ChatGPT

Where Skills are available:

1. Open Plugins / Skills.
2. Choose Create.
3. Choose upload from computer or the available skill editor flow.
4. Upload this skill folder/archive.
5. Review the skill before enabling/sharing it.

Important: the Skill defines memory behavior. ChatGPT still needs a connected local-memory tool/plugin/app if the web client must read/write a machine-local SSOT.

## Grok

For Grok environments that support filesystem Skills, place the directory under a configured skills root such as:

- `./.grok/skills/multi-ai-local-memory/`
- `~/.grok/skills/multi-ai-local-memory/`

Grok web/mobile Skill Creator can also be used to recreate/import the same workflow where supported.

## OpenClaw

Common locations include:

- `<workspace>/skills/multi-ai-local-memory/`
- `~/.openclaw/skills/multi-ai-local-memory/`

Or install a local skill directory with the platform's skill installer when available.

OpenClaw can often use direct local files or local tools, making it suitable as the bridge/SSOT executor for other AI clients.

## Cross-platform requirement

Do not fork the memory policy per platform.

If a platform needs an adapter, adapt transport/tool names only. Keep:

- schemas,
- memory policy,
- conflict rules,
- sensitivity policy,
- E2E rules

identical across clients.
