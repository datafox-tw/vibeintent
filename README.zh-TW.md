# vibeintent

VibeIntent 是一個本地端、工具無關的 AI coding 觀測層。它會記錄你的開發意圖、分析 Git diff，並產生一份可以在 code review 前閱讀或貼進 PR 的 Markdown 報告。

一句話定位：

> 讓你享受 vibe coding 的速度，同時保有向 mentor 解釋每個重要改動的底氣。

## 為什麼需要它

AI coding 工具像 Codex、Claude Code、Cursor 可以很快改出一大包 code，但問題是：你可能不知道它到底動了什麼、多做了什麼、少做了什麼。

這對實習生、junior developer、或正在用 AI agent 做產品的人特別危險。因為最後要負責的人不是 AI，而是你。

VibeIntent 的目標是幫你回答：

- 這次到底改了哪些檔案？
- 哪些 function / class 被新增、修改或刪除？
- 這些改動跟我原本的 intent 是否一致？
- AI 有沒有順手改了不該改的設定、schema、dependency？
- 我拿這份 code 給 mentor 或 reviewer 看之前，應該先理解哪些點？

## v0.1 能做什麼

這一版刻意保持簡單、離線、零外部依賴。

- `vibeintent intent "..."` 記錄你這次想讓 AI 做什麼。
- `vibeintent check` 分析目前 Git diff，產生 session report。
- `vibeintent init` 安裝非阻擋式 `post-commit` hook，commit 後自動在背景產報告。
- Python 檔案會用標準庫 `ast` 做 best-effort function/class/constant 摘要。
- 只掃描新增行的基本資安 delta，例如疑似 secret、`eval`、`shell=True`、debug mode。
- 報告存在 `.vibeintent/sessions/`。

## 快速開始

在這個專案本地開發時：

```bash
pip install -e .
```

到任意 Git repo 裡：

```bash
vibeintent init
vibeintent intent "幫登入加 rate limiting，不要動其他 auth flow"
# 接著用 Codex / Claude Code / Cursor / 手動修改 code
vibeintent check
```

你會得到一份類似這樣的報告：

```markdown
# vibeintent Session Report

**Intent:** 幫登入加 rate limiting，不要動其他 auth flow

## Changed Files

| File | Status | + | - | Intent Fit |
|---|---:|---:|---:|---|
| `auth/login.py` | modified | 20 | 3 | OK |
| `settings.py` | modified | 1 | 0 | Review |

## Function And Class Changes

- `auth/login.py:12` `function login_view` modified

## Intent Gap

**Unexpected or needs reviewer attention**
- settings.py (modified)
```

## pip 套件開發檔案

這個 repo 現在不只是「一包 Python code」，而是開始具備 pip package 的基本形狀：

- `pyproject.toml`：定義套件名稱、版本、Python 版本、build backend、CLI entrypoint。
- `src/vibeintent/`：真正會被安裝的 package code。
- `src/vibeintent/__main__.py`：讓使用者可以跑 `python -m vibeintent`。
- `src/vibeintent/py.typed`：告訴 type checker 這個 package 有型別資訊。
- `LICENSE`：授權條款，沒有它就不太像正式開源套件。
- `CHANGELOG.md`：記錄每個版本改了什麼。
- `.gitignore`：避免把 build artifact、cache、venv 放進 Git。
- `docs/publishing.md`：TestPyPI / PyPI 發佈流程筆記。

這裡最重要的是 `src/` layout。它可以避免你在本地測試時不小心 import 到 repo 根目錄的檔案，讓測試更接近真正安裝後的狀態。

## 指令

```bash
vibeintent init
vibeintent intent "your intent"
vibeintent check
vibeintent report
vibeintent report --pr
vibeintent log
vibeintent show <session-or-report-id>
vibeintent explain path/to/file.py
```

## v0.1 設計邊界

- 不做 `pre-commit` 阻擋。
- 不在 commit 時跳 TUI。
- `post-commit` hook 會背景執行，不阻擋 VS Code、Cursor 等 GUI commit flow。
- 不解析 Claude Code、Cursor 或其他 AI 工具的私有 log / JSONL。
- 不讀 clipboard。
- 不呼叫 LLM。
- Python symbol 分析是 best-effort，不宣稱完整 semantic diff。

這些限制是刻意的。v0.1 的重點不是炫，而是穩：不要卡 commit、不要吃 private internal format、不要要求公司環境一定能連網。

## 隱私

VibeIntent 預設完全本地執行。

- 不上傳 code。
- 不上傳 prompt。
- 不讀 clipboard。
- 不呼叫第三方 API。

## 適合誰

- 正在準備或進行軟體實習、需要向 mentor 解釋 PR 的學生。
- 剛開始用 AI coding tool 的 junior developer。
- 用 AI agent 快速做產品，但想知道 AI 到底改了什麼的 indie hacker / founder。
- 想把每次 AI-assisted coding session 留成學習紀錄的人。

## 下一步方向

短期最重要的不是加更多 AI，而是把它變成一個真的好用的 pip 套件。

建議路線：

1. 穩定 CLI 體驗
   - 錯誤訊息要清楚。
   - 沒有 Git repo、沒有 commit、沒有 diff、沒有 intent 時都要優雅處理。
   - `vibeintent check` 的報告要短而有用。

2. 補 packaging 基礎
   - 加上 LICENSE。
   - 加上 changelog。
   - 確認 `pip install -e .`、`python -m vibeintent`、`vibeintent --version` 都穩。
   - 之後再發 TestPyPI，不急著直接上 PyPI。

3. 改善報告品質
   - 讓 `Intent Fit` 更準。
   - 對 config、dependency、migration、auth/security 檔案給更明確提醒。
   - 加上「Reviewer Questions」區塊，幫 intern 準備 code review 會被問的問題。

4. 增加語言支援
   - v0.1 先 Python。
   - v0.2 可以加 JavaScript / TypeScript 的 regex 級 symbol 掃描。
   - 不要太早跳 full tree-sitter semantic diff。

5. 做 dogfooding
   - 先拿 VibeIntent 來分析 VibeIntent 自己的 commit。
   - 每次你用 Codex 改這個 repo 前先跑 `vibeintent intent`。
   - 這會很快暴露報告哪裡真的有用、哪裡只是看起來很厲害。

## 發佈文件

- [英文 README](README.md)
- [發佈流程](docs/publishing.md)
- [版本紀錄](CHANGELOG.md)
