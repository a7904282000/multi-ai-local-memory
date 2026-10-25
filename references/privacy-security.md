# Privacy and Security

## Local-first

Keep the authoritative long-term memory local when that is the configured architecture.

A cloud AI may receive only the recalled subset needed for the current task.

## Never store as memory

- passwords,
- API keys,
- bearer tokens,
- OAuth refresh/access tokens,
- private keys,
- recovery codes,
- security answers.

## Sensitive personal memory

Default policy: `explicit_only`.

If a user explicitly asks to keep sensitive personal information and local policy permits it, store the minimum useful durable fact and provenance. Do not silently expand or infer adjacent sensitive attributes.

## Logs and audit

Prefer hashes/IDs/status booleans over full content.
Audit should prove behavior without becoming a second raw transcript database.

## Least privilege

A memory bridge should only access the configured memory scope, not the entire filesystem.

Separate read, write, and administrative capabilities when practical.

## Failure mode

Fail closed when identity/authentication cannot be validated for a write operation.
Do not silently fall back to an unauthenticated writer.
