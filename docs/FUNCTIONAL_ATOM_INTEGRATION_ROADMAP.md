# 功能原子到运行时方法包：集成路线

## 目标

把第一阶段审计得到的 259 个功能原子逐步转化为可版本化、可路由、可测试、可回溯的学习方法包。系统共享结构化学习对象和证据协议，按学习任务调用最小充分模块，避免超级提示词、无边界角色扮演和一次性超长输出。

## 当前差距

v0.7.0 已经把“学习证据必须绑定材料版本”提升为运行时契约：KnowledgeUnit 证据版本、Session/Attempt 材料快照、ReviewState 精确版本绑定、Hard Conflict 有效证据阻断和修复门已经落地；当前方法包为 `law_full_recall_v1@0.3.0`，SQLite 为 Schema 4。语义编译、法律争点、事实—要件映射、跨题根因聚类、精确 SourceChunk 和其他组合配方仍未形成完整运行时契约。

当前代码里可直接复用的入口包括：

- KnowledgeUnit.objective_type：已有初步任务类型，可用于路由。
- Feedback：已有 matched、missing、incorrect、expression、next_action 和 evidence。
- feedback_json：可保存方法包与维度快照，暂不修改公开请求。
- study_events：可追加方法选择、版本和状态迁移事件。
- provider_runs：可记录模型或本地规则运行事实。
- 本地来源受限评分器：可作为方法包的确定性降级路径。

## 设计原则

1. 来源原文、认知重构、模型推断和用户确认永久分层。
2. 方法包声明输入、输出、启用条件、禁止项、版本和验收标准。
3. 学习任务先经过路由，再调用最小模块链。
4. 没有用户作答，不生成掌握证据。
5. 旧方法版本产生的历史 Attempt 保留当时快照，不随新版本改写。
6. 本地规则始终提供可运行的降级路径，云端模型只做可替换增强。

## 分阶段路线

### Phase A：方法包契约与首个闭卷包（首个切片已本地验证）

首包：law_full_recall_v1。

训练维度：

- core_question：是否识别并回答核心设问。
- rule_elements：规则、构成要件或条件是否完整。
- exceptions_boundaries：例外、限制和边界是否恢复。
- legal_effect：法律效果或结论是否明确。
- terminology_expression：规范术语、逻辑连接和答案结构是否合格。

运行结果至少包含：method_pack_id、method_pack_version、selection_reason、dimension_results、source_refs、generated_flags、next_action。

首版把方法包快照写入 `attempts.feedback_json` 与 `study_events`。v0.7.0 已因对抗审查暴露的历史漂移问题升级到 Schema 4，将材料版本、正文哈希、Session/Attempt 快照和 ReviewState 版本绑定显式化。当前实现与早期原子映射见 `M3A_ATOM_TRACEABILITY.md`；v0.7 的证据契约见 `V0.7_EVIDENCE_INTEGRITY_REPORT.md`。

### Phase B：知识单元类型与人工审阅（v0.7.0 证据版本已完成，材质本体仍待深化）

已实现人工编辑、确认、光标拆分和相邻合并，并用归档旧单元保护历史证据。`objective_type` 仍只有旧的粗粒度类型，尚未升级为定义、规则、程序、辨析、案例争点等稳定材质本体；拆分也尚未重建精确 SourceChunk。

### Phase C：错误分类与修复配方（v0.7.0 有效证据门已完成，根因聚类仍待深化）

已形成 `open → repairing → resolved` 单条错误状态机，关闭前要求对应修复 session 的新无提示闭卷和人工确认。ErrorRecord 分类仍偏粗，跨题根因聚类、稳定错误本体、自动选择对比/边界/规范表达修复配方尚未完成。

### Phase D：题目与规范表达方法包

逐步落地 RCP-04、RCP-07、RCP-08、RCP-09：争点攻坚、题目训练、错题组根因修复和主观题表达训练。真题、官方解析、教材例题和 AI 生成题必须使用不同 source_type。

### Phase E：外部工具与 Agent

在核心学习闭环稳定后，再接入 OCR、FTS5/本地检索、MCP、桌面壳和可选云端模型。Agent 只能在确定性状态机与权限回执内行动。

## 首个切片验收

- 同一个知识单元启动闭卷时，方法包选择可预测且可解释。
- 闭卷页面能看到本轮能力检查项，且不提前暴露答案。
- 提交后返回五维诊断和来源证据。
- 方法包 ID、版本和维度快照在重启后仍可读取。
- 老数据库、老 API 调用和现有测试保持兼容。
- 方法包失败时退回 local_evidence_v1，并明确降级原因。
- 新测试证明的是行为成立，包括错误路径、历史快照和来源边界。

## 暂缓项

故事化编码、游戏化、完全遗忘止损、自动高频判断、永久记忆和后台定时任务暂不进入默认核心。它们只有在真实学习数据证明收益大于干扰后，才作为独立插件进入。

## v0.5.0 完成证据

- 选择：按 `objective_type` 确定性路由，并在会话事件中冻结方法包快照。
- 执行：提交后产生五维来源受限诊断；没有明确例外时返回 `not_applicable`。
- 持久化：方法包 ID、版本、选择理由、状态、诊断和来源引用进入 `feedback_json` 与 `study_events`。
- 降级：方法包异常不阻断提交，明确回退 `local_evidence_v1`。
- 验证：20 项测试、真实 HTTP 重启恢复、备份恢复及桌面/移动端 Chromium 回归通过。

这只证明 Phase A 的首个最小切片成立，不代表 259 个原子已全部运行时化。

## v0.6.0 硬化证据

- 法学关键极性/期限/数字冲突进入确定性闸门；完整闭卷支持 `critical_conflict` / `uncertain`。
- KnowledgeUnit 支持人工审核、编辑、拆分、合并；归档旧结构不会进入当前学习队列。
- ErrorRecord 形成可追溯修复 session 和人工关闭链。
- 验证：25 项 pytest、真实 HTTP、备份恢复、Chromium 审核器与错因修复队列回归。

这仍然只代表“来源与学习证据基础层”被压实，尚未进入正式法律语义推理层。

## v0.7.0 证据完整性证据

- Schema 4 固化 KnowledgeUnit 版本、来源基底、Session/Attempt 材料快照与 ReviewState 精确版本绑定。
- 正文/学习目标改版使当前掌握失效；标题独立修改不制造新证据版本。
- Hard Conflict 通过 Evidence Verdict 真正阻断有效分、掌握状态与调度，Possible Conflict 进入待核验。
- 错因普通关闭要求对应 repair session 的新无提示、有效分达门、`accepted` 证据。
- 验证：36 项 pytest、真实 HTTP、Schema 4 备份恢复、Chromium UI 回归，以及真实 Chromium UI 请求桥接真实 FastAPI 的关键冲突跨层 E2E。

该阶段解决的是证据地基，不代表已经实现法律语义推理层。
