# HANDOFF：给下一任接手 Agent 的提示词

> 使用方式：把本文件**全文**（或"第 1 节到第 13 节"正文）直接复制粘贴给接手 Agent。
> 本文件由上一任 Agent 在 2026-08-09 交接时撰写，其中每一节都标注了信息来源（【用户明确】【仓库事实】【前任推断】【可能下一步】），请勿把推断当作事实。

---

## 0. 你是谁、被派来做什么

你是这个项目的**新任维护 Agent**。上一个 Agent 已完成一轮建设并移交。你的任务**不是**继续机械执行上一任的思路，而是：

1. **先理解**：读懂用户真正想要什么、产品现在是什么、代码和仓库实际状态是什么；
2. **再核验**：上一任说的每件事，你自己去仓库/代码/运行中验证，不要轻信本文件；
3. **再判断**：重新推导当前最优路径，可以质疑上一任的任何决策，发现隐藏需求，提出更好的方案；
4. **再行动**：确认了再动手，不要重复已完成的工作。

工作目录：`D:\A-Project\1法学学习台`（Windows，Git Bash）。GitHub 远程：`https://github.com/Kvxw1105/law-study-workbench`（`origin/main`，当前与本地同步于 `3024ca6`）。

---

## 1. 项目背景【仓库事实 + 用户明确】

- 这是一个**完全本地运行**的法学学习工具，服务地址 `http://127.0.0.1:8765`，双击根目录 `START_WINDOWS.bat` 启动（自动建/复用 `.venv`、装依赖、启动、开浏览器）。
- 产品形态：用户导入法考教材 PDF → 自动切成章节单元 → 生成/手动划选**挖空与闪卡** → 每日闭卷自测 + 间隔复习 → 每次作答记录为**学习证据**（StudyPack 可导出/导入）。全程本地，**零云端、零 token、无 AI 参与**——所有规则都是本地代码（启发式规则，非模型）。
- 技术栈：FastAPI + 原生 JS（无前端框架）+ SQLite（`data/workbench.db`，Schema 4）+ PyMuPDF（PDF 解析/句子定位）+ 自研 pdf.js 阅读器（`app/static/vendor/pdfjs`，本地托管）。
- 用户正在用的真实教材：《2025民法强化讲义》（198 页，已导入并重新解析为 72 个单元），数据库里有用户真实学习数据（教材 + 少量作答记录）。

## 2. 用户真正想解决的问题【用户明确 + 前任推断】

**用户明确说过的：**
- 用户要准备法考，要背"确定性内容"（构成要件、条件、期限、例外、规则数字），需要把教材变成**可复习、可自测、可回溯原文**的形式。
- 用户明确要求**零云端、零 token、不依赖 AI**（这是产品不变量，用户反复强调）。
- 用户重视"证据"：每次学习动作留痕，能查"这道题出自教材哪一句"（PDF 句子级定位是用户明确要的功能，已实现）。
- 用户要**客观**：他要求工具"能做到什么、不能做到什么"如实说，不要吹。

**前任推断（待你验证，不是事实）：**
- 用户的最终目的可能是"通过法考"，工具只是手段——所以工具的价值在"帮他把教材吃透、可检验"，而非功能堆砌。
- 用户可能有"害怕假装学习/想量化投入"的动机，证据链设计正是为此。
- 用户当前阶段拒绝 AI 可能是成本/隐私/可控性考量，**未来可能想加 AI 讲解/批改**——但这只是假设，用户从未说要加 AI。

## 3. 长期目标【前任推断，需继续验证】

用户最终想得到的结果（假设层级）：**一套他自己能长期用、把教材变成"可复习 + 可自测 + 可回溯 + 有证据"的学习系统，让他能确信自己真的记住了，而不是感觉记住了。** 任何有助于这个结果、且不破坏"本地优先、零 token、可靠"约束的方向，都值得探索。

## 4. 当前状态【仓库事实】

- `main` = `3024ca6`，已推送 GitHub，与远程同步；工作区干净。
- 151 个 pytest 测试函数全部通过（push 前全量验证）；`scripts/alpha_doctor.py --full` 自检通过；`scripts/public_repo_guard.py --tracked` 0 findings。
- 服务当前**未运行**（环境会回收后台进程）；用户双击 `START_WINDOWS.bat` 或让 Agent 启动即可。数据在 `data/`（`workbench.db` + `library/` 教材 + `backups/` 备份 + `exports/`）。
- GitHub 有 CI（`.github/workflows/ci.yml`）：push/PR 自动跑 guard + 编译 + pytest + smokes。
- 仓库是 **public**（Kvxw1105/law-study-workbench），但**所有用户数据都在本地，从未上传**（`.gitignore` 保护，有 `PUBLIC_REPO_POLICY.md` 约定）。

## 5. 已经完成的工作【仓库事实】

- **教材导入/解析**：PDF → 单元；修复了 CJK 跨行断字（"两\n\n个"→"两个"）、章节标题智能提取（`app/services/pdf_parser.py`、`app/services/text_utils.py`）。
- **挖空/闪卡升级**：多空挖空（一句最多 3 空，逐空评分）、挖空带段落上下文、素材分流（判定句→挖空、逻辑句→闪卡，不重复）、9 类闪卡提问模板、水印句过滤（`app/services/retrieval.py`、`app/main.py`）。
- **划选建卡**（思源式）：教材正文划选 → 浮动条"挖空/闪卡"建卡；`==内容==` 标记自动转多空卡（`app/static/app.js`）。
- **自研 PDF 阅读器**：应用内嵌（dialog + pdf.js canvas），不依赖浏览器插件、防下载扩展劫持；**句子级定位**（卡片/反馈 → 自动跳原句页 + 黄色高亮 + 滚动居中，后端 `/api/locate`）。
- **证据链**：Study Pack/Study Events（Protocol 0.1）、作答快照、错误修复流程（有门槛）、学习者模型。
- **工程质量**：151 测试、`alpha_doctor`/`alpha_status`/`alpha_launcher`/`alpha_perf_benchmark`/`public_repo_guard` 脚本、CI、性能基准文档。

## 6. 验证结果【仓库事实】

- 151 pytest 全绿；性能基准：150 单元 / 1001 卡片 / 500 事件全亚秒。
- 阅读器 + 定位：playwright + 视觉模型双重验收通过（高亮矩形定位准确）。
- 用户真实场景：教材重新导入 72 单元、断字残留 0、挖空上下文完整；用户已用真实使用中（发现过挖空质量差→已修）。
- push 前 guard 0 findings；未上传任何用户数据。

## 7. 关键决策（及理由）【仓库事实 / 前任决策，可质疑】

| 决策 | 理由 | 可质疑点 |
| --- | --- | --- |
| 本地优先、零 token、无 AI | 用户明确要求 | 用户未来可能改变（见第 2 节假设） |
| 评分只认确定性内容（关键词/要件） | 本地规则能做；开放论述评不了，已如实告知用户 | 是否有更聪明的本地评分（如语义相似度库）值得探索 |
| 证据链 + 快照 + 版本失效 | 防止"正文改了旧掌握状态无效"，保证证据可追溯 | 复杂度与用户实际收益的平衡 |
| 复习调度用固定档位（10min/1天/3天/7天） | 简单可靠；**不是** FSRS 类自适应算法 | 用户数据多了以后是否该上自适应算法 |
| 公开仓库 + 本地数据严格隔离 | 用户要 GitHub 容器 | 是否该加 release/tag 管理 |
| Schema 4 / Protocol 0.1 为当前基线 | 已固化、有迁移测试 | 只在有充分理由时升级 |

## 8. 已知问题与限制【事实 + 推断区分】

**明确限制（用户已知悉）：**
- ❌ 不支持扫描件 OCR（只认可搜索文字 PDF）。
- ❌ 无 AI 讲解/答疑/论述批改（评分是"关键词覆盖检查"，不是理解）。
- ❌ 无云同步/多设备；移动端 PWA 只在电脑浏览器验证过（REAL_DEVICE_PENDING）。
- ❌ 数据明文存储（无加密）、无自动备份策略（有手动备份/恢复）。

**已知质量问题（事实）：**
- 正文解析会混入页眉/版权水印（生成卡片时过滤，但正文可见）。
- 句子定位对"断字严重/跨页"的句子可能失败，静默回退到页码。
- 闪卡自评是自我报告，靠用户诚实；学习者模型数据少时是空壳。
- 后台服务会被环境回收（Windows 下需重新启动）。
- 挖空/闪卡自动生成是模板式，质量"可用但平庸"（用户接受，手动划选建卡是他更信任的方式）。

## 9. 未完成事项与可能的下一步【前任推断，别当既定路线】

- **真实使用验证**：用户刚开始真实使用（REAL_USER_ALPHA_PENDING）——他用了之后反馈的问题，是最高优先级输入。
- **移动端真机验证**（REAL_DEVICE_PENDING）：PWA 离线复习在真机未验收。
- **潜在方向（全部只是候选，需你重新判断优先级）**：FSRS 式调度；本地语义评分；OCR；AI 讲解（若用户改变零 AI 立场）；更智能的出题；学习统计报表；卡片更细的编辑/停用/替换体验。
- **没有既定路线**：上一任没有为"下一步"定死方向。你先听用户怎么说、看代码里哪里最痛，再定。

## 10. 重要文件与仓库地图【仓库事实】

- `app/main.py`（全部 API 端点）、`app/db.py`（Schema 4）、`app/config.py`、`app/services/`（importer / pdf_parser / text_utils / retrieval / scorer / scheduler / study_protocol / evidence_integrity / legal_signals / method_packs）
- `app/static/`（index.html + app.js + styles.css + vendor/pdfjs）
- `tests/`（151 个：protocol conformance / evidence conformance / recovery / launcher / sentence quality / card quality / portable lifecycle 等）
- `scripts/`（alpha_status / alpha_doctor / alpha_launcher / alpha_perf_benchmark / public_repo_guard / 各种 smoke）
- `docs/`（ARCHITECTURE / PRODUCT_INVARIANTS / STUDY_PROTOCOL_V0 / MVP_PRD / SECURITY_AND_PRIVACY / UX_GAP_ANALYSIS / HANDOFF_TO_NEXT_AGENT.md 等）
- `portable-reviewer/`（手机离线复习 PWA）
- `AGENT_HANDOFF.md`（产品状态说明）、`.agent/PROJECT_STATE.md`（工程状态）、`PUBLIC_REPO_POLICY.md`、`CHANGELOG.md`、`ROLLBACK.md`、`requirements-lock.txt`

## 11. 不可破坏的约束【用户明确 / 仓库事实】

1. **本地优先、零云端、零 token、无 AI 介入**——产品不变量，用户反复强调。任何功能不得引入在线依赖或悄悄改变这一点。
2. **公开仓库永不混入用户数据**：教材 PDF、`data/` 数据库、StudyPack、备份、截图一律不进 Git（`.gitignore` + `public_repo_guard` 双保险，push 前必须跑 guard）。
3. **证据链/协议完整性不降级**：Schema 4、Study Protocol 0.1、Evidence Integrity 门槛（评分、修复流程）不能为了"看起来好用"而放松。
4. **测试不降门槛**：改代码要补/更新测试，151 全绿是基线；修改前先跑测试。
5. **法律文本准确性**：教材正文是用户复习依据，解析/评分改动不得引入丢字、错字（上一任为此修过断字，有回归测试）。
6. **诚实交付**：用户要求客观——能做到什么、不能做到什么如实说，不夸大。
7. push/建 PR/删数据等**外部可见或不可逆操作，先问用户**（用户会明确授权）。

## 12. 给接手 Agent 的接管指令

**第一步：理解与核验（约 30 分钟，不写代码）**
- 读 `README.md`、`AGENT_HANDOFF.md`、`.agent/PROJECT_STATE.md`、`docs/PRODUCT_INVARIANTS.md`、`docs/ARCHITECTURE.md`、`docs/UX_GAP_ANALYSIS.md`。
- 跑 `python scripts/alpha_status.py`、`python scripts/alpha_doctor.py --quick`、`python -m pytest -q`（151 应全绿）。
- 启动服务（`START_WINDOWS.bat` 或 `.venv/Scripts/python -m uvicorn app.asgi:app --port 8765`），打开 `http://127.0.0.1:8765` 走一遍：教材库 → 打开 PDF → 卡片 → 练习 → 今日任务，亲手确认产品现状。
- 检查 `git log`、`git status`、`git remote`，确认与上面描述一致。

**第二步：独立判断（不急着动手）**
- 重新审视"用户最终想要什么"（第 2、3 节）：哪些是用户明确说的，哪些是上一任的推断？你有没有发现隐藏需求？
- 挑出你认为**最痛**的 1-3 件事（结合代码里最别扭的地方 + 用户最可能先踩的坑），形成自己的优先级，**允许推翻上一任的任何决策**。
- 把你的判断（而不是直接开干）先用简短方案和用户对齐（尤其是要动约束 1/2/3 的任何方向）。

**第三步：行动**
- 从你自己排的最高优先级开始，小步验证、每步有测试、按第 11 节约束执行。
- 外部可见操作（push/PR/删数据）先问用户。
- 不要重复已完成的工作：上一任已交付解析修复、卡片体验、阅读器定位、证据链、测试/CI/工具链——**不要再"重做"，要"改进或质疑"**。

---

> 交接人记录（上一任 Agent）：最后交互确认过：用户已授权 push（已完成），用户要求 HANDOFF 给下一任。服务重启方法、性能基准、协议细节见 `docs/` 与 `scripts/`。
