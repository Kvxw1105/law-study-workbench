# Agent Handoff Contract

## 当前可信状态

- 产品：法学语义学习工作台 `0.8.0`
- SQLite：Schema 4
- 方法包：`law_full_recall_v1@0.3.0`
- 工程状态：`LOCALLY_VERIFIED / COMMITTED / PUSHED / PR_OPEN / REAL_USER_ALPHA_PENDING`
- Git：v0.8.0 基线已 commit 并 push 到分支 `alpha/import-v0.8.0-ui-v2.1`，以 Draft PR 提交审查；`main` 尚未直接接收本基线。无 GitHub CI / Release。真实用户 Alpha 验收仍 pending。
- 证据层级（只能声明有证据的层级）：`EDITED → LOCALLY_VERIFIED → COMMITTED → PUSHED → PR_UPDATED → CI_PASSED → RELEASED`

## v0.8 Portable Study 保护线

1. StudyPack/StudyEvents 是实验性跨端协议，不得退化为直接同步 SQLite/ReviewState。
2. portable client 只能提交 Attempt/Event；桌面 Runtime 权威重评 cloze 并重算 ReviewState。
3. portable event 必须保留 item version/hash、pack identity、base_last_attempt_id 与 event_id 幂等。
4. history/version/time 冲突必须显式返回 receipt，不允许 last-write-wins 静默覆盖。
5. 当前只验证同一 Runtime 的手动文件往返；不得声称云同步、跨实例、Agent 自动同步、真机 PWA 已完成。

## 第一性原理保护线

1. 学习证据必须绑定当时材料版本与学习目标。
2. 历史 Session/Attempt 不得被当前 KnowledgeUnit 编辑重新解释。
3. Provider 原始覆盖分不等于有效学习证据分。
4. Hard Conflict 必须真实影响 ReviewState、复习调度和 ErrorRecord；Possible Conflict 保守进入待核验。
5. ReviewState 只对精确 `knowledge_unit_version + unit_body_hash` 有效。
6. 来源基底只读，可编辑学习文本不能冒充不可变教材原文。
7. 错因 `resolved` 必须有对应 repair session 的新有效无提示复测，再由用户人工确认。
8. AI/启发式结果不得被包装成正式法学阅卷或法条效力结论。

## 数据保护

禁止：

- 删除、重置或覆盖 `data/`、用户 PDF、历史 Session/Attempt/RetrievalAttempt/ErrorRecord/事件；
- 把 `legacy_backfilled_current` 改称精确历史快照；
- 让旧版本 ReviewState 回流新版本；
- 未备份就变更 Schema；
- 用户主动 archived 的卡片被自动复活；
- 静默上传教材、答案、数据库或 API Key。

Schema 4 回退旧代码前必须恢复升级前完整备份。

## 当前关键数据契约

### KnowledgeUnit

- `version`
- `body_hash`
- `source_basis_text/hash/status`
- `objective_type`

正文或学习目标变化创建新的证据版本；标题独立变化不创建。

### KnowledgeUnitVersion

`knowledge_unit_versions` 保存历史材料、来源基底、页码、目标和版本。

### StudySession / Attempt

必须保存：

- `unit_version`
- `unit_body_hash`
- `unit_snapshot_json` / snapshot status（Session）
- Attempt 对应的 snapshot status

活动 Session 中禁止改变正文/学习目标。

### ReviewState

仅对与当前 KnowledgeUnit 精确 version/hash 匹配的状态生效。

### Evidence Verdict

- `blocked_critical`：有效分<=45、`需立即修复`、立即到期；
- `blocked_structure`：有效分<=55；
- `needs_verification`：待核验；
- `accepted`：可进入普通复习策略。

### Error repair

普通 `can_resolve` 至少要求：对应 frozen repair session、`hint_level=0`、有效分>=70、`evidence_weight>=0.99`、verdict accepted。

## 强制执行顺序

```text
1. 只读预检
2. 检查 Git/数据目录/Schema/项目状态
3. 备份本地学习库
4. 写明目标、保护区、迁移和验收
5. 修改最小完整切片
6. 静态/单测/真实HTTP/浏览器验证
7. 对抗性检查版本漂移、证据污染、误报漏报
8. 更新 PROJECT_STATE / CHANGELOG / HANDOFF
9. 打包后从压缩包重新解压验证
```

## 当前验证命令

```bash
python3 -m compileall -q app tests scripts
node --check app/static/app.js
pytest -q
python3 scripts/http_smoke.py
python3 scripts/backup_restore_smoke.py
python3 scripts/browser_smoke.py
python3 scripts/browser_ui_round2.py
python3 scripts/browser_real_e2e.py
python3 scripts/study_protocol_roundtrip_smoke.py
python3 scripts/portable_reviewer_smoke.py
python3 scripts/study_protocol_browser_roundtrip.py
```

当前基线：44 项 pytest 通过。

`browser_smoke.py` / `browser_ui_round2.py` 使用真实 Chromium + deterministic Mock API。`browser_real_e2e.py` 使用真实 Chromium 页面并桥接真实 Uvicorn/FastAPI，不使用 Mock API 数据；当前容器策略禁止 Chromium 页面直接访问 localhost，因此不得称为直接网络 E2E。

## 当前明确不能声称

- 完整法律语义正确性判断；
- 正式法学阅卷；
- 完整争点识别、事实—要件涵摄；
- 权威法条/司法解释效力核验；
- 精确 PDF 坐标级 SourceChunk；
- 跨题深层根因聚类；
- FSRS/个体化遗忘模型；
- 真题/案例/选择题/论述题成熟训练引擎。

## 下一开发顺序

1. 真实手机 Portable Study Alpha：同一 Runtime 手工导出/导入数天，验证 Safari/Chrome 文件流、PWA/localStorage 恢复、重复导入与时间偏差。
2. 继续真实教材 Alpha：KnowledgeUnit 改版率、Hard/Possible Conflict 误报漏报、错因复发。
3. 两条 Alpha 稳定后再决定 Sync Transport v0.1 / Agent Route；暂不造插件市场或通用模块画布。

## 提交报告

必须分开报告：`EDITED / LOCALLY_VERIFIED / COMMITTED / PUSHED / PR_UPDATED / CI_PASSED / RELEASED`。只能声明有证据的层级。

## 本地 Agent 操作指南（Operator Runbook）

以下命令让本地 Agent 直接作为本项目 Operator 使用。所有路径为项目根目录。

### 检查环境

```bash
git status --short --branch   # 分支与工作区状态
git log --oneline -3          # 最近提交
git rev-parse HEAD            # 当前 HEAD
python -m pytest -q           # 测试状态（基线 44 passed）
```

### 启动工作台（Windows）

```bash
# 推荐：使用项目 .venv
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-lock.txt pytest httpx playwright
LAW_STUDY_HOME=... .venv/Scripts/python -m uvicorn app.asgi:app --host 127.0.0.1 --port 8765
# 浏览器打开 http://127.0.0.1:8765
```

或直接运行 `START_WINDOWS.bat`（自动处理 .venv 与启动）。

### 健康检查

```bash
curl http://127.0.0.1:8765/api/health
# 期望 {"status":"ok","version":"0.8.0","storage":"local","ai_provider":"local"}
```

### 跑一次 Alpha 自检（完整命令链）

```bash
python -m compileall -q app tests scripts
node --check app/static/app.js portable-reviewer/app.js portable-reviewer/sw.js
python -m pytest -q
python scripts/http_smoke.py
python scripts/backup_restore_smoke.py
python scripts/study_protocol_roundtrip_smoke.py
python scripts/portable_reviewer_smoke.py
python scripts/study_protocol_browser_roundtrip.py
python scripts/browser_smoke.py
python scripts/browser_real_e2e.py
```

浏览器脚本需要 Chromium（默认 `/usr/bin/chromium`；Windows 可通过环境变量 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` 指向 chrome.exe）。

### 查看项目当前状态

- Git：见上；`main` 与本地分支是否同步用 `git fetch` + `git rev-parse` 对比。
- 数据：`data/` 目录（SQLite 与 library/exports/backups），默认忽略，不进入 Git。
- 健康：上节 health 检查。
- 状态：读 `.agent/PROJECT_STATE.md`（工程事实基线，网页端与本地 Agent 共用）。

### 产品操作 ≠ 改代码

- “准备今天的 StudyPack”：通过工作台 UI 导出（`/api/study-pack/export` 或设置页），是产品操作，不是修改代码。
- “网页端要审代码”：代码已在 GitHub，确保最新 commit / PR / Issue 状态清晰即可，不要重新打 ZIP 传递。
