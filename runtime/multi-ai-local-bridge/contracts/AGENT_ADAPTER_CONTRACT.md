# Agent / Intermediary Adapter Contract v1

**Status:** Stable interface  
**Contract version:** `1.0`

## 1. Purpose

An Agent / Intermediary Adapter connects any agent runtime, relay, orchestrator, desktop automation host, or direct model runner to the Local Bridge without becoming a memory owner.

Examples include OpenClaw, another agent framework, a desktop agent host, a CLI orchestrator, or a direct application integration.

OpenClaw is the default reference adapter only. It is not required by the Bridge Core.

## 2. Shared-memory invariant

The adapter MUST use the same authorized `memory_space` as every other connected client.

The following are provenance/authentication dimensions only and MUST NOT create separate memory silos:

```text
agent_id
agent runtime
model
provider
intermediary chain
device
surface
```

Therefore, for authorized peers in the same memory space:

```text
Agent A write -> Agent B recall       MUST work
Agent write -> Browser model recall   MUST work
Browser model write -> Agent recall   MUST work
Intermediary X -> Intermediary Y      MUST preserve memory semantics
```

## 3. Required lifecycle

Each logical agent turn MUST implement the semantic equivalent of:

```text
before_turn
  -> create transaction identity
  -> recall from Local Bridge
  -> inject only returned memory context
  -> run agent/model exactly once

after_turn
  -> capture completed user/assistant turn
  -> preserve injected_memory_ids
  -> use durable retry if capture delivery fails
```

The same `transaction_id` MUST span recall and capture for one logical turn.

## 4. Recall behavior

Before the agent/model executes, the adapter MUST:

1. preserve the actual current user/task text used for recall;
2. call `/v1/recall` with the authorized `memory_space`;
3. keep returned `memory_id`s for feedback-loop prevention;
4. expose recalled context to the agent without changing memory ownership.

Failure policy:

```text
401 / 403 / invalid contract or security configuration -> FAIL CLOSED
ordinary Bridge/storage unavailability                 -> MAY FAIL OPEN
```

A fail-open turn MUST be observable as `memory_context_available=false` or equivalent diagnostics.

## 5. Capture behavior

After the agent/model returns a final response, the adapter MUST submit one logical Capture event containing:

```text
exact user/task text
final assistant/agent response
same transaction_id
same turn_id/session_id
injected_memory_ids
explicit remember signal when detectable
execution provenance
```

Capture MUST NOT mean "save every conversation". Long-term memory policy remains Bridge-owned.

## 6. Durable capture delivery

A completed turn MUST NOT lose its Capture merely because the Bridge is temporarily unavailable.

The adapter MUST provide durable retry/outbox semantics or delegate to an equivalent durable delivery layer.

Required properties:

```text
capture queued before/while delivery is attempted
same idempotency_key reused on retry
success removes the queued item
restart preserves unsent items
security/config failures do not create an infinite retry storm
```

## 7. Intermediary transparency

An intermediary MUST NOT rewrite the canonical memory contract into an intermediary-specific memory format.

The adapter MAY add provenance:

```json
{
  "surface": "agent",
  "provider": "...",
  "product": "...",
  "model": "...",
  "agent_id": "...",
  "intermediary_chain": [
    {"type": "agent-runtime", "id": "openclaw"}
  ]
}
```

But changing the intermediary MUST NOT require changing Bridge storage semantics or memory-space identity.

## 8. Adapter boundary

The generic adapter owns:

- turn correlation;
- Bridge recall/capture calls;
- security-vs-availability failure policy;
- durable capture retry;
- execution provenance normalization.

A runtime-specific wrapper owns only:

- extracting current user/task text;
- injecting pre-run context using runtime hooks;
- extracting the final response;
- mapping runtime session/run/agent/model identifiers into the generic adapter inputs.

This split is REQUIRED so a runtime such as OpenClaw cannot become a Bridge Core dependency.

## 9. OpenClaw reference mapping

Reference mapping:

```text
before_prompt_build -> generic before_turn
before_agent_run    -> fail-closed security gate
agent_end           -> generic after_turn
gateway_start       -> durable outbox replay
```

OpenClaw-specific hook names MUST NOT appear in Bridge Core interfaces.

## 10. Conformance requirements

A conforming Agent / Intermediary Adapter MUST prove:

```text
GENERIC_AGENT_RECALL=PASS
GENERIC_AGENT_CAPTURE=PASS
SAME_TRANSACTION_RECALL_CAPTURE=PASS
INJECTED_MEMORY_FEEDBACK_GUARD=PASS
SECURITY_FAILURE_FAIL_CLOSED=PASS
AVAILABILITY_FAILURE_POLICY=PASS
DURABLE_CAPTURE_OUTBOX=PASS
RESTART_OUTBOX_REPLAY=PASS
CROSS_AGENT_SHARED_MEMORY=PASS
AGENT_TO_BROWSER_SHARED_MEMORY=PASS
BROWSER_TO_AGENT_SHARED_MEMORY=PASS
INTERMEDIARY_DOES_NOT_PARTITION_MEMORY=PASS
OPENCLAW_IS_DEFAULT_ONLY=PASS
```
