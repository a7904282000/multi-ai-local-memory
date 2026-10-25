# User Acceptance — Public Beta

Final live compatibility testing is performed on the user's own environment, because ChatGPT/Grok web UI, browser policy, installed agents, and local Obsidian state cannot be reproduced reliably for every user before distribution.

## Public Beta browser-adapter note

Until the browser adapter has a normal store/distribution listing, beta testers may load the unpacked extension from the `browser_extension_dir` printed by the installer.

This manual developer-mode step is **beta-only**. It MUST NOT be counted as satisfying the final Stable zero-config requirement.

Stable release requires a trusted browser-extension distribution path where the ordinary user only performs the browser's unavoidable install/approval confirmation.

## One simple acceptance flow

After installation and the browser-extension approval required by the browser:

1. In **AI A** (for example ChatGPT), send:
   `請記住：跨模型同步測試代碼是 MALM-TEST-<任意四碼>。`
2. In **AI B** (for example Grok or OpenClaw), ask:
   `我的跨模型同步測試代碼是什麼？`
3. Open the corresponding local memory in **Obsidian** and change the code once.
4. Ask **AI A or AI B** for the code again.

Pass means:
- AI B can read what AI A saved.
- the local memory exists in the user's local memory software;
- a manual local edit propagates back to another AI;
- no duplicate durable memory is created;
- restart recovery keeps the same memory space;
- original migrated source-memory archives remain byte-identical.

## What the installer self-tests automatically

The installer/doctor/self-test should verify everything that does not require a real third-party website interaction:
- Local Bridge health;
- shared memory_space identity;
- automatic credentials;
- local storage write/read;
- cross-client bridge recall;
- autostart;
- source archive preservation;
- duplicate protection;
- local sync runtime.

## User-facing result

Return only a compact result:

```text
LOCAL_BRIDGE=PASS/FAIL
MODEL_A_TO_MODEL_B=PASS/FAIL
MODEL_TO_LOCAL_MEMORY=PASS/FAIL
LOCAL_MEMORY_TO_MODEL=PASS/FAIL
BIDIRECTIONAL_SYNC=PASS/FAIL
DUPLICATE_WRITE=<number>
SOURCE_ARCHIVE_INTACT=PASS/FAIL
FINAL_USER_ACCEPTANCE=PASS/FAIL
```

If a browser/provider blocks an action, report the single unavoidable approval/action. Do not ask the user to perform engineering diagnostics.
