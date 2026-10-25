# Multi-AI Local Memory

**一份存在自己電腦上的記憶，讓多個 AI 一起讀、一起寫、一起更新。**

ChatGPT、Grok、OpenClaw 與其他支援的模型／Agent，都可以透過同一個 Local Bridge 使用同一個本地 `memory_space`。預設記憶軟體是 Obsidian；OpenClaw 是預設中繼，但兩者都可以替換。

## 主要功能

- 多模型共享同一份本地長期記憶。
- Web / Desktop / Agent / Intermediary 共用，不按模型分裂記憶。
- 自動 Recall、Capture、雙向同步、去重與重啟恢復。
- 不是所有聊天都變成記憶，只保存有長期價值的內容。
- 舊記憶遷移時 100% byte-for-byte 保存原始來源。
- Semantic Index 只是可重建的衍生層，不能取代原始記憶。
- 預設 Obsidian，也可接 SQLite 或其他 Adapter。
- 使用者驗收採簡單跨模型測試，不要求工程診斷。

## 使用方式

當 AI/Agent 能在使用者本機執行程式時，優先執行：

```bash
python scripts/install.py
```

若目前 AI surface 無法操作使用者本機，Skill 必須明確說明 `BLOCKED`，並引導使用者使用 Local Bridge/桌面安裝器；不得假裝已完成本地同步。

瀏覽器若要求「Add extension」確認，這是允許保留的外部安全確認；其餘 token、Extension ID、memory_space、Bridge URL 與同步設定應自動完成。

## 文件

- `SKILL.md` — 共用 Skill 與硬規則
- `QUICK_DESCRIPTION.md` — 最短產品說明
- `RELEASE_CHANNELS.md` — ChatGPT / Grok / OpenClaw / Browser / Bridge 發布方式
- `RELEASE_PIPELINE.md` — Public Beta → Stable 發布流程
- `USER_ACCEPTANCE.md` — 使用者最後實機驗收
- `runtime/multi-ai-local-bridge/` — 本地 Bridge runtime source
- `references/` — architecture / memory policy / security / E2E
