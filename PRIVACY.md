# Privacy Policy｜隱私權政策

**Multi-AI Local Memory**  
Effective date / 生效日期: 2026-10-25

## 中文（繁體）

### 1. 這個擴充功能做什麼

Multi-AI Local Memory 讓支援的 AI 網頁（例如 ChatGPT、Grok）透過使用者自己電腦上的 Local Bridge，共用同一份本地記憶。

擴充功能會在支援的 AI 網頁中讀取使用者送出的訊息與模型回覆，以便在送出前取得相關本地記憶（Recall），並在回覆完成後將符合記憶規則的內容送回 Local Bridge（Capture）。

### 2. 處理的資料類型

為提供核心功能，擴充功能可能處理：

- 使用者在支援 AI 網頁中輸入的訊息
- AI 模型回覆內容
- 與 Local Bridge 連線所需的本機驗證憑證
- 擴充功能本機設定
- Capture 失敗時的本機待重送佇列
- 與同步及錯誤診斷有關的本機狀態

### 3. 資料儲存與傳輸

擴充功能設計為將資料傳送至**使用者自己電腦上的 Local Bridge**，而不是開發者經營的雲端資料庫。

開發者不會將使用者的 AI 對話內容、Local Bridge 憑證或本地記憶上傳至開發者控制的遠端伺服器。

Local Bridge 可依使用者設定將記憶保存在本地記憶軟體中；預設支援 Obsidian，亦可使用其他相容的本地儲存 Adapter。

### 4. 長期記憶

不是所有聊天內容都會自動成為長期記憶。

Local Bridge 會依記憶規則決定哪些內容值得長期保存，例如：

- 穩定偏好
- 使用者明確要求記住的內容
- 長期規則
- 已確認決策
- 專案狀態
- 其他具持久價值的資訊

一般短暫對話、確認語或低價值訊息不應自動保存為長期記憶。

### 5. 原始記憶保存

若使用者匯入既有記憶，系統設計為保留原始來源資料。任何語意索引、搜尋索引或其他衍生資料均不得取代原始來源記憶。

### 6. 第三方 AI 服務

當使用者使用 ChatGPT、Grok 或其他第三方 AI 服務時，使用者與該服務之間的資料處理仍受該第三方服務自己的隱私政策與條款約束。

Multi-AI Local Memory 不控制第三方 AI 服務如何處理使用者直接傳送給該服務的資料。

### 7. 資料販售與廣告

開發者不會：

- 販售或出租使用者資料
- 將使用者資料提供給資料仲介商
- 使用使用者資料進行與本擴充功能單一用途無關的廣告或行銷
- 使用使用者資料進行信用評分或貸款資格判斷

### 8. 權限用途

擴充功能只要求提供核心功能所需的權限，例如：

- `storage`：儲存本機設定、Local Bridge 憑證及待重送 Capture
- `alarms`：定期重試因 Local Bridge 暫時無法使用而未送出的 Capture
- 支援 AI 網站的網站存取權限：在 ChatGPT、Grok 等支援網頁執行 Recall / Capture
- localhost / 127.0.0.1 存取：與使用者電腦上的 Local Bridge 通訊

### 9. 遠端程式碼

擴充功能不會下載、`eval` 或執行遠端 JavaScript。

所有可執行程式碼均包含在已安裝的 Chrome 擴充功能套件中。

### 10. 資料控制與刪除

本地記憶由使用者自己控制。使用者可以直接在其本地記憶軟體或 Local Bridge 中管理、修改或刪除資料。

解除安裝瀏覽器擴充功能不應自動刪除使用者的本地記憶資料。

### 11. 政策變更

若本隱私權政策有重大變更，更新版本將發布在本專案的公開來源頁面。

### 12. 聯絡與專案來源

Project / 專案：
https://github.com/a7904282000/multi-ai-local-memory

Issues / 問題回報：
https://github.com/a7904282000/multi-ai-local-memory/issues

---

## English

### 1. What this extension does

Multi-AI Local Memory allows supported AI web applications, such as ChatGPT and Grok, to share one user-owned local memory through a Local Bridge running on the user's own computer.

The extension processes the user's outgoing messages and AI responses on supported AI websites so it can recall relevant local memory before a message is sent and capture eligible durable memory after the AI response is completed.

### 2. Data processed

To provide its core functionality, the extension may process:

- messages entered by the user on supported AI websites
- AI-generated responses
- local authentication credentials used to connect to the Local Bridge
- local extension settings
- locally stored retry/outbox data for failed capture operations
- local synchronization and diagnostic state

### 3. Storage and transmission

The extension is designed to transmit data to a **Local Bridge running on the user's own computer**, not to a developer-operated cloud database.

The developer does not upload users' AI conversation content, Local Bridge credentials, or local memory to developer-controlled remote servers.

The Local Bridge may store memory in a local memory application selected by the user. Obsidian is supported by default, and other compatible local storage adapters may also be used.

### 4. Long-term memory

Not every conversation automatically becomes long-term memory.

The Local Bridge applies memory rules to determine which information has durable value, such as:

- stable preferences
- explicit remember requests
- durable rules
- confirmed decisions
- project state
- other persistent information

Transient conversation, acknowledgements, and low-value messages should not automatically become long-term memory.

### 5. Source-memory preservation

When existing memories are imported, the system is designed to preserve the original source data. Semantic indexes, search indexes, and other derived data must not replace the original source memory.

### 6. Third-party AI services

When a user interacts with ChatGPT, Grok, or another third-party AI service, the data exchanged directly with that service remains subject to that third party's own privacy policy and terms.

Multi-AI Local Memory does not control how third-party AI providers process data that users directly submit to those services.

### 7. Data sale and advertising

The developer does not:

- sell or rent user data
- transfer user data to data brokers
- use user data for advertising or marketing unrelated to the extension's single purpose
- use user data for credit scoring or lending decisions

### 8. Permission usage

The extension requests only permissions required for its core functionality, including:

- `storage`: local settings, Local Bridge credentials, and durable capture retry/outbox data
- `alarms`: periodic retry of capture operations when the Local Bridge is temporarily unavailable
- supported AI website access: recall and capture on supported AI web applications such as ChatGPT and Grok
- localhost / 127.0.0.1 access: communication with the user's Local Bridge

### 9. Remote code

The extension does not download, `eval`, or execute remote JavaScript.

All executable code is packaged with the installed Chrome extension.

### 10. User control and deletion

Local memory is controlled by the user. Users can manage, modify, or delete their memory through their local memory application or Local Bridge.

Uninstalling the browser extension should not automatically delete the user's local memory.

### 11. Policy changes

Material updates to this Privacy Policy will be published through the project's public source repository.

### 12. Contact and source

Project:
https://github.com/a7904282000/multi-ai-local-memory

Issues:
https://github.com/a7904282000/multi-ai-local-memory/issues
