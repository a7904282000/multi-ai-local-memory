# E2E Acceptance

## Principle

A personalized-looking answer is not proof of recall.
A matching string in the SSOT is not proof of capture.

The same real turn must be correlated end to end.

## Minimum always-on E2E proof

For the same transaction/turn:

1. send intent observed,
2. transaction created,
3. original user text captured before send,
4. memory credential/trusted local capability used automatically,
5. recall request succeeded,
6. recall source is the current local SSOT,
7. user message released exactly once,
8. assistant final response observed,
9. capture request succeeded,
10. final local writer succeeded,
11. stored fact matches the intended durable fact,
12. injected recall context was excluded from capture,
13. duplicate effective writes = 0,
14. turn correlation = PASS.

## Example verdict

```text
TRANSACTION_ID=...
RECALL=PASS
RECALL_FROM_SSOT=PASS
SEND_RELEASE_COUNT=1
AFTER_RESPONSE=PASS
CAPTURE=PASS
FINAL_WRITE=PASS
INJECTED_CONTEXT_EXCLUDED=PASS
DUPLICATE_WRITE=0
TURN_CORRELATION=PASS
FINAL_E2E=PASS
```

## Invalid shortcuts

Do not accept these as E2E proof by themselves:

- model remembers the answer,
- file contains the same phrase,
- plugin says `loaded`,
- static tests pass,
- source build is correct but live runtime is stale,
- one route returns success without turn correlation.
