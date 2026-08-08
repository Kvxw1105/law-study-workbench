# 架构说明

## 总体结构

```text
桌面浏览器 / 独立 Portable Reviewer / 未来 Agent
        ↓              ↓ 文件协议
FastAPI 本地服务 ← StudyPack / StudyEvents
        ↓
Evidence Contract Layer
  材料版本 / Session快照 / 有效证据裁决
        ↓
Study Engine + Method Pack + Retrieval Engine
        ↓
Knowledge Engine / Source Ledger
        ↓
SQLite Schema 4 + 本地 PDF
```

当前架构的核心约束是：**学习证据必须绑定当时材料和学习目标，历史记录不能被后来编辑重新解释。**

## 当前代码分层

- `app/main.py`：HTTP API、学习状态编排、KnowledgeUnit 版本操作、Session/Attempt/Error/Review 写入。
- `app/db.py`：SQLite Schema 4、幂等迁移和追加式事件日志。
- `app/services/evidence_integrity.py`：材料/来源哈希、版本快照、来源页定位和有效证据裁决。
- `app/services/legal_signals.py`：保守的法律高风险冲突/可能冲突检测。
- `app/services/method_packs.py`：`law_full_recall_v1@0.3.0` 路由、五维学习目标恢复检查和边界标记。
- `app/services/scorer.py`：原始来源覆盖 Provider；原始分不再直接等于有效学习证据分。
- `app/services/retrieval.py`：闪卡、挖空、卡片快照与卡片调度。
- `app/services/study_protocol.py`：StudyPack/StudyEvents 协议常量、Pack 规范哈希和跨端事件时间保护。
- `portable-reviewer/`：无桌面 API 依赖的独立移动训练客户端，只产生 StudyEvents。
- `app/services/importer.py` / `pdf_parser.py`：PDF 来源、页文本与初始 KnowledgeUnit。
- `app/static/`：无构建步骤的本地 Web UI。

## 来源与学习文本

### SourceDocument / SourcePage

保存不可变教材文件标识、页级解析文本、页码、质量和哈希。它们是来源账本。

### KnowledgeUnit

KnowledgeUnit 是当前学习工作对象。Schema 4 把：

- `source_basis_text/hash/status`：来源基底，只读；
- `body/body_hash`：可编辑学习单元文本；
- `objective_type`：本轮学习目标；
- `version`：证据版本；

明确分开。

正文或学习目标变化产生新的证据版本；标题独立修改不产生新证据版本。

### KnowledgeUnitVersion

`knowledge_unit_versions` 保存每个证据版本的标题、正文、正文哈希、来源基底、页码范围、目标类型和快照状态。旧版本不被新版本覆盖。

## 完整闭卷证据链

```text
审核后的 KnowledgeUnit
→ 创建 StudySession
→ 冻结 unit_version/body_hash/material snapshot/source anchor/method pack
→ 隐藏学习文本并主动提取
→ 提交 Attempt
→ Provider 原始来源覆盖反馈
→ Method Pack 五维来源恢复 + Legal Signals
→ Evidence Verdict 生成有效学习证据分
→ 仅在版本契约仍匹配时更新 ReviewState
→ 写入 ErrorRecord / StudyEvent
```

### StudySession

保存：

- `unit_version`
- `unit_body_hash`
- `unit_snapshot_json`
- `snapshot_status`

历史读取优先使用冻结快照。活动 session 中禁止修改正文或学习目标。

### Attempt

Attempt 固化其所属材料版本/哈希/快照状态，并在 `feedback_json` 中同时保存原始 Provider 分、有效证据裁决、方法包、五维结果和来源引用。

### ReviewState

ReviewState 绑定 `knowledge_unit_version + unit_body_hash`。当前 KnowledgeUnit 改版后，旧状态不会进入当前掌握、今日到期或建议逻辑。

## 有效证据裁决

`evidence_integrity.py` 将“字面覆盖”与“能否进入掌握证据”分开：

- hard conflict → `blocked_critical`，有效分最多45，立即修复；
- 结构异常 → `blocked_structure`，有效分最多55；
- possible conflict / 方法包未完成 → `needs_verification`；
- 无阻断 → `accepted`，进入现有复习策略。

该裁决是学习证据政策，不是正式法律阅卷器。

## 错因修复

ErrorRecord 保存错误实例。修复流程：

```text
open
→ repairing + frozen repair_session_id
→ 对应 session 完成 hint_level=0 Attempt
→ 有效分>=70 + evidence_weight>=0.99 + verdict=accepted
→ can_resolve
→ 用户人工确认
→ resolved
```

正文/学习目标产生新版本时，旧契约下仍开放或修复中的错误进入 `superseded`，防止旧错误污染新版本。

## Retrieval 证据

卡片系统继续保存每次 RetrievalAttempt 的题面、答案、来源摘录、内容哈希和卡片版本快照。正文改版会让相关活动卡片 `stale`；历史 RetrievalAttempt 不改写。

## Portable Study v0.1

跨端路径采用事件同步：

```text
Desktop Runtime
→ StudyPack（训练对象 + 导出时基线）
→ Portable Reviewer（离线训练）
→ StudyEvents（不可变 Attempt 行为）
→ Desktop Runtime（身份/版本/因果冲突裁决）
→ 权威评分 + Scheduler
→ RetrievalAttempt / ReviewState
```

当前 Kernel 规则：

- 不同步 SQLite 表或 ReviewState 派生字段；
- item 绑定 `id + version + content_hash`；
- Pack 绑定 `pack_id + pack_hash` 且必须能在当前 Runtime 的导出事件中确认；
- event 使用稳定 `event_id` 幂等；
- `base_last_attempt_id` 防止离线期间桌面历史前进后静默覆盖；
- flashcard 是 self-report evidence；cloze 回桌面重评；
- 同一 Runtime、手动文件传输是 v0.1 的有意边界。

这层证明“工作台只是客户端之一”，但尚未形成跨实例信任、Sync Transport、账号或 Agent Route。

## Schema 4 迁移

Schema 4 在 Schema 3 基础上新增：

- KnowledgeUnit 来源基底和正文哈希；
- `knowledge_unit_versions`；
- StudySession 材料快照与版本字段；
- Attempt 材料版本字段；
- ReviewState 精确版本/哈希绑定。

Schema 3 的历史 full-recall session 从未保存精确材料快照，因此迁移只能用当前可观察 KnowledgeUnit 回填，并标记 `legacy_backfilled_current`。如果旧 ReviewState 的最后 Attempt 早于当前 KnowledgeUnit 的修改时间，迁移保守删除该当前掌握状态，因为无法证明它属于现版本。

回退旧代码前必须恢复升级前完整备份。

## Method Pack 边界

`law_full_recall_v1@0.3.0` 仍只处理本地来源和用户答案。它不访问外部法条、判例或答案库，`semantic_correctness_verified=false`、`formal_legal_grade=false` 是持久化边界。

Legal Signals v2 增加主体关系、数字—动作绑定、短规则和双向矛盾扫描，但仍可能漏掉复杂指代、否定作用域和真正需要法律解释的语义。Possible Conflict 进入待核验，不直接判死。

## 浏览器验证结构

- `browser_smoke.py`、`browser_ui_round2.py`：真实 Chromium + deterministic Mock API，验证 UI/视觉状态；
- `http_smoke.py`：真实 Uvicorn/SQLite；
- `browser_real_e2e.py`：真实 Chromium 页面通过请求桥访问真实 Uvicorn/FastAPI，用于验证关键冲突的跨层语义接线。

当前执行环境策略禁止 Chromium 页面直接连接 localhost，因此第三项不是直接网络 E2E；这一限制必须在验收声明中保留。

## 下一阶段

优先用真实教材验证证据契约和冲突误报/漏报，再建设：精确 SourceChunk、RuleAtom/FactAtom/Issue、案例事实—要件映射、跨题根因聚类、真实数据驱动调度。避免在证据地基未通过 Alpha 前继续扩大“智能”名词层。
