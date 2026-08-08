# law_full_recall_v1 方法包契约

状态：`LOCALLY_VERIFIED`

方法包版本：`law_full_recall_v1@0.3.0`

产品版本：`0.7.0`

## 目的

把完整闭卷组织成冻结学习目标受限的法学结构训练，同时把高置信冲突信号接入有效学习证据裁决。方法包负责训练方向、来源恢复维度和风险信号；最终是否进入掌握状态由 Evidence Verdict 决定。

当前方法包不承担正式法学评分、事实—要件涵摄、外部法条核验或任意语义等价判断。

## 输入契约

方法包在 Session 开始时读取并冻结：

- `KnowledgeUnit.version/body/body_hash/page_start/page_end/objective_type`；
- 来源基底与来源页锚点；
- 方法包 ID/version/profile。

提交时使用**Session 冻结材料快照**、用户答案、置信度、提示级别和基础 Provider 反馈。当前 KnowledgeUnit 后来发生变化，不得改变本轮方法包的材料或目标。

## 路由与版本

`objective_type` 决定训练重点顺序：精确复现、辨析、适用、理解解释、表达或综合。正文或学习目标变化构成新的证据版本；标题独立修改不构成新的学习证据目标。

当前不同 profile 主要改变训练重点与解释顺序，尚未形成彼此独立的法律推理器。不得把“已路由”描述为成熟自适应教学引擎。

## 五个维度

| 维度 | 当前能力 | 当前不能证明 |
|---|---|---|
| 核心设问 | 来源主线恢复、结构提醒、部分关系冲突 | 真正完成争点识别 |
| 规则与要件 | 规则/条件来源句覆盖 + 高风险冲突 | 条件逻辑完整正确 |
| 例外与边界 | 例外模式与来源恢复 | 完整相邻制度辨析 |
| 法律效果 | 效力/权利/义务来源恢复 + 极性/关系冲突 | 案例结论法律上正确 |
| 术语与规范表达 | 来源术语和结构信号 | 正式阅卷得分 |

### 维度状态

- `strong`：较高学习目标恢复信号；
- `partial`：部分学习目标恢复；
- `missing`：学习目标恢复较弱；
- `not_applicable`：来源中未检出该类明确内容；
- `critical_conflict`：高置信关键关系/极性/数字等冲突；
- `uncertain`：存在 possible conflict、完整同义改写或结构可疑，当前本地算法不安全下结论；
- `unavailable`：方法包降级。

`strong` 永远不能解释为“法律答案正确”。

## Legal Signals v2

`app/services/legal_signals.py` 当前包含保守的高风险检测：

- 应当/不应当、必须/无需；
- 可以/不得/不可以；
- 有效/无效、生效/不生效、成立/不成立；
- 权限、责任、适用、善意/恶意；
- 中文/阿拉伯数字和期限单位；
- 主体—动作—对象关系；
- 数字—期限—动作绑定；
- 短规则保护；
- 中文标点式关键词堆砌；
- 双向句对扫描。

复杂否定作用域如“并非无效”“不当然无效”优先进入 possible/uncertain，避免把词面反义误判成确定法律冲突。

## Evidence Verdict

方法包结果不会直接等于掌握。`evidence_integrity.py` 再做学习证据裁决：

- Hard Conflict → `blocked_critical`，有效分上限45，掌握“需立即修复”，立即到期；
- 结构阻断 → `blocked_structure`，有效分上限55；
- Possible Conflict / 方法包异常 → `needs_verification`；
- 无阻断 → `accepted`。

Provider 原始分保留在反馈中用于诊断，但 ReviewState 和复习调度使用有效证据结果。

## 持久化

方法包和证据快照进入：

- `study_sessions.method_pack_json`；
- `study_sessions.unit_version/unit_body_hash/unit_snapshot_json`；
- `attempts.unit_version/unit_body_hash/unit_snapshot_status`；
- `attempts.feedback_json.method_pack/dimension_results/evidence_verdict/generated_flags`；
- `study_events`。

Schema 4 的 ReviewState 同时绑定当前 KnowledgeUnit version 和 body hash。

持久化边界：

```json
{
  "learning_target_bounded": true,
  "learning_target_provenance": "source_exact | edited_learning_text | legacy_unverified | source_basis_pending",
  "source_exact": "boolean",
  "source_bounded": "true only when the frozen learning target exactly matches the source basis",
  "external_knowledge_used": false,
  "heuristic_diagnostic": true,
  "lexical_source_signal": true,
  "semantic_correctness_verified": false,
  "formal_legal_grade": false
}
```

## 降级

方法包异常时仍保存真实作答；方法包维度标记不可用，并进入 `needs_verification`，不能因为基础字符串覆盖很高直接形成强掌握。

## 版本演化

### v0.1.0

建立方法包选择冻结、五维来源受限快照和持久化。

### v0.2.0

增加关键法律冲突与 uncertain 状态，用户可见名称从法学诊断收紧为来源恢复检查。

### v0.3.0

把方法包与 Schema 4 证据契约连接：Session 冻结材料/目标；Hard Conflict 进入有效证据裁决并真实影响掌握和调度；Possible Conflict 保守进入待核验；加强主体关系、数字动作、短规则、双向矛盾和否定作用域处理。历史 v0.1/v0.2 Attempt 不被新版本重写。
