# Project State

更新时间：2026-08-08
模式：IMPLEMENT → REVIEW → HANDOFF
工程状态：LOCALLY_VERIFIED / NO_GIT_METADATA / REAL_USER_ALPHA_PENDING
产品版本：0.8.0
数据库 Schema：4
方法包：law_full_recall_v1@0.3.0

## 当前可信定位

这是一个已经形成真实本地数据闭环、并开始具备版本化证据完整性的“法学学习证据与主动提取工作台”。当前核心价值是来源、材料版本、真实作答、掌握状态和修复记录之间的可追溯关系。法律语义智能仍是保守安全闸门与来源恢复层，不能声称正式阅卷、完整争点推理或事实—要件涵摄。

## v0.8.0 Portable Study 契约

1. StudyPack 是可携带训练对象，不是 SQLite 备份；当前只承载 flashcard/cloze。
2. 跨端只回灌 Attempt/Event，不让客户端覆盖 `due_at`、streak、mastery 等派生状态。
3. 每个 portable event 绑定 item id/version/content_hash、pack id/hash 和导出时的 base_last_attempt_id。
4. 桌面 Runtime 是 v0.1 的权威 evaluator/scheduler；cloze 必须在桌面重评，flashcard 明确为 self-report evidence。
5. 重复事件幂等；历史前进、版本漂移、未知 Pack、明显时钟异常都显式冲突，不静默覆盖。
6. 当前只证明同一 Runtime 的手动文件往返；不声称云同步、跨实例同步、账号或 Agent 自动同步已完成。

## v0.7.0 第一性原理契约

1. 每次学习证据绑定当时的 KnowledgeUnit 版本、正文哈希和材料快照。
2. 正文或学习目标变化产生新的证据版本；标题独立修改不产生新证据版本。
3. 活动闭卷冻结材料，进行中禁止修改正文/学习目标。
4. Hard Conflict 必须进入有效证据裁决，真实影响分数、掌握状态、复习间隔和 ErrorRecord。
5. ReviewState 只对精确 `unit_version + body_hash` 生效；改版后旧掌握不能继承。
6. ErrorRecord 只有新的无提示、有效分达门、无阻断的修复复测才可进入人工确认关闭。
7. 来源基底只读，可编辑学习文本与来源身份分离。

## 当前已验证主链

PDF 导入 → 页级来源 → KnowledgeUnit → 来源基底/学习文本分层 → 人工审核 → 版本冻结 → 完整闭卷/卡片 → 有效证据裁决 → ReviewState/ErrorRecord → 针对性无提示复测 → 人工关闭 → 重启恢复/备份/导出。

## v0.7.0 增量

- Schema 4：`knowledge_unit_versions`、KnowledgeUnit 来源基底/哈希、Session/Attempt 快照、ReviewState 精确版本绑定。
- `evidence_integrity.py`：原始覆盖分与有效学习证据分分离；hard conflict/structure/verification/accepted 四类裁决。
- Legal Signals 硬化：主体关系、数字—动作绑定、短规则、双向矛盾扫描、中文标点关键词堆砌、否定作用域 possible 分层。
- KnowledgeUnit：正文/目标改版清空当前掌握并 supersede 旧开放错误；活动 session 禁止改材料；draft 默认先审核。
- Error repair：有效分 >=70、evidence_weight >=0.99、verdict accepted、无提示复测才解锁人工关闭。
- UI：只读来源基底与可编辑学习文本分开；反馈显示有效证据分并在必要时显示原始覆盖分。

## 验证证据

- `python3 -m compileall -q app tests scripts`
- `node --check app/static/app.js`
- `pytest -q`：44 passed
- `python3 scripts/http_smoke.py`：真实 Uvicorn、Schema 4、版本化闭卷、关键冲突与修复链
- `python3 scripts/backup_restore_smoke.py`：Schema 4 备份/破坏/恢复
- `python3 scripts/browser_smoke.py`
- `python3 scripts/browser_ui_round2.py`：真实 Chromium + deterministic Mock API 的视觉/交互回归
- `python3 scripts/browser_real_e2e.py`：真实 Chromium UI + 请求桥接到真实 Uvicorn/FastAPI，验证关键冲突跨层接线。当前容器策略禁止 Chromium 直接访问 localhost，因此此项不能描述成直接网络 E2E。
- `python3 scripts/study_protocol_roundtrip_smoke.py`：真实 FastAPI 的 StudyPack → StudyEvents → ReviewState 往返与幂等。
- `python3 scripts/portable_reviewer_smoke.py`：Chromium 执行独立 reviewer 的真实 JS/CSS、文件输入、两种训练和 StudyEvents 下载。
- `python3 scripts/study_protocol_browser_roundtrip.py`：真实 FastAPI 导出 Pack → Chromium 独立训练 → 实际下载事件文件 → 原文件回灌真实 FastAPI。

## 保护区

- 不删除/覆盖 `data/`、用户教材、历史 Session/Attempt/RetrievalAttempt/ErrorRecord/事件。
- 不把 `legacy_backfilled_current` 冒充成精确历史快照。
- 不让旧版本 ReviewState 污染新版本 KnowledgeUnit。
- 不静默把可编辑学习文本冒充不可变教材来源。
- 不把高置信冲突检测器宣传为完整法律语义正确性判断。
- 没有用户真实作答，不产生掌握证据。

## 当前明确限制

- Legal Signals 仍是保守词典/关系启发式，不能覆盖所有否定作用域、指代和实体法语义。
- Source anchor 仍以页范围/页哈希为主，尚无稳定的段落/坐标级 PDF 高亮。
- Schema 3 历史 full-recall session 无法重建当时精确正文，只能显式标记迁移回填状态。
- Error repair 的 70 分门槛是本地证据政策，不等于法律实体正确性证明。
- 无跨题语义根因聚类、RuleAtom/FactAtom/Issue 推理、成熟真题训练、OCR、个体化调度。
- Portable Study 当前没有真实手机 Safari/Chrome 的文件生命周期、Service Worker/PWA 安装和 localStorage 重开验收；没有云/局域网 Sync Transport。
- v0.1 只接受当前桌面 Runtime 自己导出的 Pack；Pack 为明文私人文件，尚无签名、加密或跨实例信任。

## 下一步

先做双重真实 Alpha：一章真实法学教材继续验证证据契约；同时用真实手机完成数天 StudyPack → 随身复习 → StudyEvents 回灌，记录文件摩擦、恢复、冲突和使用频率。两条证据稳定后，再决定 Sync Transport、Agent Route 与 SourceChunk/RuleAtom/FactAtom/Issue。

Git 状态（2026-08-08 导入公开仓库后）：v0.8.0 基线已作为 `chore: import verified v0.8.0 alpha baseline` 提交到分支 `alpha/import-v0.8.0-ui-v2.1`，以 Draft PR 提交审查；`main` 未被直接修改，未创建 release/CI/部署。公开仓库按 `PUBLIC_REPO_POLICY.md` 只保存可公开源码、测试、协议与经检查文档，不含任何真实用户数据。

## UI/UX v3.0 前端重构（2026-08-08）

状态：LOCALLY_VERIFIED / FRONTEND_ONLY / BUSINESS_CONTRACTS_FROZEN

- 采用“金石理性 × 纸本编辑部”视觉方向；主原型仍为教育服务型，辅助原型为高频个人工作台。
- `styles.css` 追加可删除式 v3 视觉层；`index.html` 仅增加主题色、视觉方向标记和移动端视觉短标签元数据。
- 没有修改 `app.js`、API、Schema 4、评分、调度、EvidenceVerdict、Legal Signals 或学习证据状态机。
- 新增 `scripts/browser_ui_v3.py`；覆盖 320/390/430/768/1024/1440/1700，多尺寸无页面级横向溢出，并检查 reduced-motion / focus。
- 430 教材库第一轮曾出现桌面双栏规则覆盖手机布局，已修复并加入 v3 回归。
- 120% 字体比例下 Today/Library/Study 代表尺寸无横向溢出。
- 详细视觉、验证与回退说明见 `docs/UI_UX_V3_REFACTOR.md`。
