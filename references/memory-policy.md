# Memory Policy

## Long-term value test

A new fact is a long-term memory candidate when at least one is true:

- the user explicitly asks to remember it,
- it is a stable preference,
- it is an explicit instruction/rule,
- it is a confirmed decision,
- it changes project state,
- it is an unresolved blocker needed next time,
- it is a durable fact that will materially affect future answers.

## Do not store by default

- filler,
- small talk,
- acknowledgements,
- temporary drafts,
- assistant speculation,
- automatically injected memory context,
- tool noise,
- secrets.

## Confidence

Recommended values are numeric `0..1` or an equivalent host mapping.

Guideline:

- direct explicit user statement: high confidence,
- verified local document/runtime evidence: high confidence,
- inference: lower confidence and normally `UNVERIFIED`,
- model guess: do not store as user fact.

## Status lifecycle

- `VERIFIED` — supported by direct user confirmation or trusted evidence.
- `UNVERIFIED` — plausible but not confirmed.
- `OBSOLETE` — previously valid or used, no longer current.
- `CONFLICT` — competing facts remain unresolved.

## Sensitive information

Public default is `explicit_only`.

The local owner may configure another policy, but the system must still exclude credentials and authentication secrets.

## Forget / delete

A memory client should not claim deletion unless it has actually mutated the SSOT and verified the result.

If a host has its own independent memory feature, deleting from the local SSOT does not automatically delete the host's internal memory and vice versa.
