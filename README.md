# law-study-workbench

**Status: Personal Alpha / Research Preview**

> 本公开仓库为个人 Alpha 研究与开发容器，不代表 production ready。
> 提交内容受 [PUBLIC_REPO_POLICY.md](PUBLIC_REPO_POLICY.md) 约束：只保存可公开源码、协议、测试代码、匿名/合成测试材料与经过检查的文档。

---

<!-- v0.8.0 product docs imported from locally-verified baseline -->

# 法学语义学习工作台

一个本地优先、证据驱动的应试学习工作台。教材文件、解析结果、学习记录、错因、卡片和复测状态默认保存在用户电脑；云端模型属于可替换增强层，不拥有学习记忆。

当前版本：`0.8.0`。Schema 4 证据完整性契约保持不变；本轮新增实验性的 `StudyPack v0.1 / StudyEvents v0.1`，第一次把闪卡与挖空从桌面工作台抽离到独立移动复习器。移动端只产生不可变 Attempt 事件，桌面 Runtime 继续负责正式评分、调度和 ReviewState 投影。当前仍是同一桌面 Runtime 的手动文件往返实验，不等于云同步。

## 当前已经能做什么

### 本地知识与学习闭环

- 导入本地文字型 PDF，按内容哈希去重，并在后台解析页级文本。
- 标记低文本页面，为后续 OCR 和人工修复预留入口。
- 将教材内容转换为带页码来源的知识单元。
- 启动完整闭卷会话，默认隐藏原文，记录提示、草稿、置信度、用时和重启恢复状态。
- 从知识单元本地生成闪卡与单空挖空题；也可手动建立、编辑和停用卡片。
- 闪卡先隐藏答案，服务端确认本轮已经显示答案后，才允许按“忘记、困难、记得、轻松”自评。
- 挖空提交后在本地进行规范化与相似度核对，再显示标准答案和教材来源。
- 为每张卡片独立保存作答、得分、连续成功、遗忘次数和下一次复测时间。
- 修改知识单元正文后，将相关旧卡片标记为 `stale`；历史作答继续保留当时的题面、答案、来源、内容哈希和版本快照。标题独立修改不制造新的学习证据版本。
- 使用本地证据覆盖评分器处理完整闭卷；默认不发送任何内容到云端。
- 导出结构化学习数据，并提供本地完整备份与受控恢复脚本。

### v0.8.0 Portable Study / Study Protocol v0.1

- 新增 `GET /api/study-pack/export`：导出独立于 SQLite 表结构的 `StudyPack v0.1`，当前只覆盖活动 `flashcard / cloze`。
- 新增 `POST /api/study-events/import`：回灌 `StudyEvents v0.1`；同步 Attempt/Event，不同步 `due_at`、`streak` 等派生状态。
- 所有移动事件绑定 `item_id + item_version + content_hash + pack_id + pack_hash + base_last_attempt_id`；桌面历史已前进、卡片改版、明显时钟异常都会显式冲突，禁止静默覆盖。
- 闪卡保持“揭示后自评”证据；挖空只接收移动端原始回答，由桌面正式 `grade_cloze` 重新评分。正式 ReviewState 只由桌面 scheduler 重算。
- 新增完全独立的 `portable-reviewer/` 静态移动复习器：导入 StudyPack、离线完成闪卡/挖空、下载 StudyEvents；不依赖桌面 API。
- 独立复习器实现未导出会话的 localStorage 恢复与 Service Worker 静态缓存壳，但由于当前容器浏览器安全策略，原生刷新恢复、安装到主屏幕和真机离线仍待 iOS/Android Alpha。
- 当前明确不做账号、云同步、CRDT、第三方插件、跨桌面实例信任或更多题型。协议说明见 `docs/STUDY_PROTOCOL_V0.md`。

### v0.7.0 证据完整性重构

- SQLite 升级到 Schema 4；新增 KnowledgeUnit 证据版本、来源基底、Session/Attempt 材料快照和 ReviewState 精确版本绑定。
- 正文或学习目标变化产生新的证据版本并使旧掌握失效；标题独立修改不产生新学习证据版本。
- 完整闭卷 Session 冻结本轮正文、页码、学习目标和方法包；活动会话期间禁止修改正文/学习目标。
- 新增 Evidence Verdict，把原始来源覆盖分和“有效学习证据分”分离。Hard Conflict 会把有效分压到 45 以下、掌握状态改为“需立即修复”、立即到期，并产生关键冲突错因。
- `law_full_recall_v1` 升级到 `0.3.0`；加强主体—动作—对象、数字—动作绑定、短规则、双向矛盾和中文标点关键词堆砌检测；复杂否定优先进入待核验。
- Error repair 普通关闭要求对应 repair session 的新无提示复测达到有效证据门并且 verdict 为 accepted。
- 教材来源基底改为只读展示，可编辑学习单元文本与来源身份分层。详细契约见 `docs/V0.7_EVIDENCE_INTEGRITY_REPORT.md`。

### v0.6.0 真实性硬化

- 挖空先检查法律关键冲突。应当/不应当、允许/禁止、效力正反、善意/恶意、期限与数字等冲突固定进入 `again`，不能再被字符串相似度平滑成“困难”。
- `law_full_recall_v1` 升级为 `0.2.0`；五维结果改称“来源恢复检查”，增加 `critical_conflict` 和 `uncertain`，并持久化 `semantic_correctness_verified=false`。
- 教材库新增 KnowledgeUnit 审核器，可编辑标题、正文和学习材质，保存确认，按光标拆分，并合并相邻单元。结构变更采用“归档旧单元 + 新建草稿”，历史作答不迁移、不改写。
- 归档单元退出今日任务、当前掌握统计、活动卡片和错因修复队列；历史证据仍可查询。
- 错因进入 `open → repairing → resolved` 闭环。必须在被冻结的修复会话中完成新的无提示闭卷，再由用户人工确认关闭。
- “学习者模型”界面降级为“学习证据画像”；考试日期和每日学习分钟明确标注目前只记录，尚未参与自动排程。
- 当前仍没有正式法学评分、完整争点推理、事实—要件涵摄或自动语义切分。详细边界见 `docs/V0.6_HARDENING_REPORT.md`。

### v0.5.0 版本化法学闭卷方法包

- 每次完整闭卷会话根据知识单元 `objective_type` 确定并冻结 `law_full_recall_v1@0.1.0` 方法包快照。
- 作答前只显示训练方向，不提前显示教材原文答案：核心设问、规则与要件、例外与边界、法律效果、术语与规范表达。
- 提交后按五个维度返回 `strong / partial / missing / not_applicable` 诊断、修复动作、来源页码和原子引用。
- 方法包 ID、版本、选择理由、诊断结果和来源引用写入 `attempts.feedback_json` 与追加式 `study_events`；服务重启后仍可恢复。
- 方法包诊断坚持来源受限和确定性启发式，不调用外部知识，也不宣称正式法学评分。
- 方法包运行失败时，提交不会被阻断；系统显式降级到 `local_evidence_v1` 基础来源覆盖反馈。

### v0.4.0 前端与交互重构

- 重建 Application Shell：今日轨道、上下文标题、模型与隐私状态、主题切换、快捷键入口和移动端底部导航。
- 今日学习页根据真实状态自动确定主行动：继续会话、完整复测、短卡复测、开始新单元或导入教材。
- 教材库改为“来源轨道 + 知识单元工作区”，增加搜索、状态筛选、来源质量提示和知识单元级学习入口。
- 闭卷学习改为三阶段工作台：闭卷提取、来源对照、修复复测。桌面端采用来源、编辑器、证据栏三列布局。
- 增加草稿状态、字数、置信度、回忆检查项、提示债务和证据权重的可视化反馈。
- 闪卡与挖空中心增加到期队列、卡片筛选、搜索、键盘评分和专注练习界面。
- 学习者模型增加置信度校准、掌握分布、反复错误和最近证据时间线。
- 手动建卡与编辑改为可访问的对话框表单，取消依赖浏览器 `prompt()`。
- 提供深色、浅色和跟随系统主题；提供舒适/紧凑密度、字体比例与减少动效设置，并保存在本机。
- 支持 390px 手机和常见桌面宽度；移动端重新组织任务，而非整体缩小桌面布局。
- 支持 `focus-visible`、跳转主内容、44px 左右触控目标和 `prefers-reduced-motion`。

## 最快启动

Windows 用户可双击：

```text
START_WINDOWS.bat
```

macOS 或 Linux：

```bash
./START_UNIX.sh
```

首次运行会创建 `.venv` 并安装依赖。浏览器地址为：

```text
http://127.0.0.1:8765
```

手动启动：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.asgi:app --host 127.0.0.1 --port 8765
```

Windows 手动命令需将 `.venv/bin/python` 替换为 `.venv\Scripts\python.exe`。

## 本地数据在哪里

默认数据目录：

```text
data/
├── workbench.db       # SQLite：教材索引、知识单元、作答、卡片、复测和事件
├── library/           # 导入后由工作台管理的 PDF 文件
├── exports/           # JSON 数据导出
└── backups/           # 完整本地备份
```

可通过环境变量修改：

```text
LAW_STUDY_HOME=D:\path\to\your\study-data
```

界面主题、密度、动效和字体比例保存在浏览器本机存储中，不进入云端。

## 快捷键

- `Ctrl / Cmd + S`：立即保存闭卷草稿。
- `Ctrl / Cmd + Enter`：提交闭卷回答并对照来源。
- `Space`：闪卡显示答案。
- `1 / 2 / 3 / 4`：闪卡评分为忘记、困难、记得、轻松。
- `/`：聚焦当前页面搜索框。
- `?`：打开快捷键说明。

输入框、文本域和中文输入法组合输入期间，不触发页面级快捷键。

## 挖空与闪卡的证据规则

- 新卡首次生成后立即进入到期队列。
- 闪卡答案在用户主动显示前不会出现在练习接口中。
- 闪卡必须在本轮通过服务端揭示答案后才能评分；提交后本轮揭示失效，避免重复提交和伪造客户端状态。
- 挖空默认忽略空格、全半角和常见标点，并使用本地字符串相似度判断。
- 每次卡片作答固定保存当时的卡片快照。后续编辑卡片会重置当前复习状态，不会改写历史证据。
- “忘记”约 10 分钟后再测；“困难”约 1 天；“记得”从约 3 天起；“轻松”从约 7 天起。
- 当前调度器是可解释的初版规则，尚未经过长期真实学习数据校准。

## 云端模型是可选增强层

默认配置为：

```text
LAW_STUDY_AI_PROVIDER=local
```

此模式使用本地证据覆盖评分和本地卡片生成，教材、答案和学习记录不离开本机。需要连接兼容 JSON 输出的云端评分接口时，参考 `.env.example`。API Key 通过环境变量提供，当前原型不会将 Key 写入数据库。

## 验证命令

```bash
python3 -m compileall -q app tests scripts
node --check app/static/app.js
node --check portable-reviewer/app.js
node --check portable-reviewer/sw.js
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

- 44 项 `pytest` 测试覆盖原有 Schema 4 证据链，并新增 StudyPack/StudyEvents、幂等导入、历史前进、版本漂移、Pack 身份、时钟异常和权威调度时间回归。
- `http_smoke.py` 启动真实 Uvicorn 服务，通过 HTTP 导入 PDF、完成 Schema 4 版本化闭卷、有效证据裁决、关键冲突、错因修复、卡片提取，并在重启后核验状态。
- `backup_restore_smoke.py` 创建包含卡片与作答的本地备份，故意破坏数据库后执行受控恢复和完整性检查。
- `browser_smoke.py` 回归原有挖空与闪卡主链。
- `browser_ui_round2.py` 验证深浅主题、桌面教材库、KnowledgeUnit 审核器、错因修复队列、手动建卡、闭卷方法包、来源恢复检查、快捷键和移动端布局。
- `browser_real_e2e.py` 在真实 Chromium 页面中把 `/api/*` 请求桥接到真实 Uvicorn/FastAPI，验证关键冲突从浏览器输入到有效证据分、ReviewState 和 ErrorRecord 的跨层一致性。当前容器策略阻止 Chromium 页面直接访问 localhost，因此此项不能描述成直接网络 E2E。

前两套浏览器回归使用真实 Chromium 和确定性 Mock API；真实后端行为由 `http_smoke.py` 与 `browser_real_e2e.py` 的真实 FastAPI 桥接路径验证。

## 当前明确限制

- 优先支持可直接提取文字的 PDF；扫描件只会被标记，尚未集成 OCR。
- 自动知识单元和卡片生成仍使用本地启发式规则，真实教材中需要人工核对和编辑。
- 当前挖空仅支持单空；关键否定、善恶意、期限与数字已有硬闸门，但同义答案组、多空联动和更完整的法学限定词词典仍未实现。
- 当前卡片调度器尚未采用 FSRS，也没有经过长期遗忘曲线数据校准。
- 本地评分器、方法包和 Legal Signals 只提供学习目标恢复信号、高置信关键冲突和待核验提示；不能替代高质量法学主观题评分、事实—要件适用判断或权威答案。复杂否定、指代和同义改写仍可能需要人工核对。
- 云端兼容 Provider 已有接口，尚未在真实供应商账户中完成集成验收。
- 尚未封装为 Tauri 或原生 Windows 安装包，当前形态是本地 Web 工作台。
- 已有独立静态 `portable-reviewer` 验证手动文件式离线复习；尚无真实手机 PWA 外部验收、自动跨设备传输、账号或云同步。
- 浅色主题、紧凑密度和极端长文本仍需要在真实用户数据上继续验收。

## 核心文档

- `docs/PRODUCT_INVARIANTS.md`：不能被功能扩张破坏的产品原则。
- `docs/ARCHITECTURE.md`：本地数据面、学习引擎、方法包、卡片引擎和模型适配层。
- `docs/MVP_PRD.md`：当前 MVP 的范围、路径与验收。
- `docs/UI_UX_ROUND2.md`：第二轮前端重构的视觉命题、交互状态、响应式和浏览器证据。
- `docs/SECURITY_AND_PRIVACY.md`：本地 Agent、文档提示注入和数据发送边界。
- `docs/METHOD_PACK_LAW_FULL_RECALL_V1.md`：首个版本化法学闭卷方法包的运行契约。
- `docs/V0.7_EVIDENCE_INTEGRITY_REPORT.md`：Schema 4 材料版本、有效证据裁决、冲突接线和修复门。
- `docs/V0.6_HARDENING_REPORT.md`：上一阶段法学关键冲突、KnowledgeUnit 审核器和错因状态机历史。
- `docs/M3A_ATOM_TRACEABILITY.md`：本切片实际引用的功能原子与代码落点。
- `docs/ACCEPTANCE.md`：当前验证证据与外部验收边界。
- `AGENT_HANDOFF.md`：交给后续本地 Agent 或 Codex 的执行契约。
