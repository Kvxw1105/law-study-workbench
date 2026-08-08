# 验收与证据

## 当前状态

`LOCALLY_VERIFIED_REAL_USER_ACCEPTANCE_PENDING`

产品版本 `0.8.0`、SQLite Schema 4、方法包 `law_full_recall_v1@0.3.0`。当前容器已经验证版本化材料快照、有效证据裁决、关键法律冲突接入掌握状态、KnowledgeUnit 改版失效、错因修复门、真实 HTTP、备份恢复和 Chromium 代表性用户路径。尚未完成用户真实 Windows 环境、真实法学教材和跨周学习周期的外部验收。

## 已执行命令

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

结果：

- Python 编译通过；
- JavaScript 语法通过；
- `pytest -q`：44 项通过；
- 真实 Uvicorn HTTP：导入、版本化完整闭卷、方法包 0.3.0、有效证据裁决、关键冲突、错因修复、卡片提取和重启恢复通过；
- SQLite Schema 4 backup API：备份、故意破坏、恢复与完整性检查通过；
- Chromium Mock API：桌面/移动端、KnowledgeUnit 审核器、错因修复、来源恢复反馈和断线恢复通过；
- Chromium + 真实 FastAPI 桥接：关键冲突从浏览器输入到后端有效证据分、ReviewState 和 ErrorRecord 的跨层语义一致性通过。

## v0.8.0 Portable Study 关键行为验收

- StudyPack 是独立协议对象，不包含数据库 tables dump；当前输出 flashcard/cloze、精确 item version/hash、来源和导出时 Review 基线。Portable Reviewer 会在训练前重算 canonical SHA-256；浏览器回归已验证篡改答案但保留旧 hash 的 Pack 会被拒绝。
- StudyEvents 只提交 Attempt 行为；重复 event-id 幂等，不重复写历史。
- 桌面历史在离线期间前进、卡片版本/hash 漂移、未知 Pack、hash 不匹配、明显未来/回拨时钟均会显式冲突。
- cloze 事件的移动端本地判断不作为权威；桌面重新执行正式本地 `grade_cloze`。
- 轻微设备时钟回拨被校正后，Attempt `created_at` 与 scheduler 使用同一个 effective time，避免记录时间和 due_at 时序脱节。
- 真实 FastAPI 导出 StudyPack → Chromium 独立 reviewer 训练并下载 StudyEvents → 将该真实文件回灌 FastAPI → SQLite ReviewState 更新，已验证。
- 原生手机 Safari/Android Chrome、Service Worker 安装、PWA 主屏幕和 reload/localStorage 恢复受当前容器浏览器策略限制，状态仍为 `pending_real_device_alpha`。

## v0.7.0 关键行为验收

### 1. 材料版本必须冻结

已验证：

- Session 开始时固化 `unit_version`、`unit_body_hash` 和 `unit_snapshot_json`；
- 历史 Session/Attempt 读取被冻结文本，不随当前 KnowledgeUnit 改写；
- 活动完整闭卷期间禁止修改正文或 `objective_type`；
- 标题独立修改不产生新证据版本；
- 正文或学习目标修改产生新版本，并使旧 ReviewState 对当前单元失效；
- 新版本重新进入学习建议，不继承旧掌握；
- 来源基底与可编辑学习文本分开展示。

Schema 3 迁移到 4 时，旧 full-recall session 无法证明当时精确材料，因此回填当前可见版本并显式标记 `legacy_backfilled_current`。该标记属于证据限制，不能解释成精确历史快照。

### 2. Hard Conflict 必须真正阻断掌握

对抗回归覆盖：

- 法律效果正反；
- 正确规则后追加相反结论；
- 债务人/债权人主体关系反转；
- `30日通知 / 60日起诉` 对调；
- 短规则 `合同无效`；
- 中文顿号/逗号式关键词堆砌；
- `并非无效` 等复杂否定进入 possible/uncertain，避免直接误杀。

Hard Conflict 进入 `evidence_verdict=blocked_critical` 后，要求：有效分 `<=45`、ReviewState=`需立即修复`、立即到期，并产生 `critical_legal_conflict` ErrorRecord。Provider 原始覆盖分可以保留作诊断信息，但不能继续驱动掌握和调度。

### 3. Error repair 必须有有效新证据

普通关闭入口要求被冻结 repair session 的最新复测同时满足：

```text
hint_level = 0
effective score >= 70
evidence_weight >= 0.99
evidence_verdict.status = accepted
```

1分复测、hard conflict、待核验结果或非对应 repair session 的作答都不能解锁 `can_resolve`。最终关闭仍由用户人工确认。

### 4. 草稿不能静默绕过审核

前端 draft 单元显示“先审核再学习”；后端在 `approve_unit=false` 时也拒绝直接启动 draft。显式审核/批准后才能进入正式完整闭卷证据链。

## 方法包边界

当前 `law_full_recall_v1@0.3.0` 仍是冻结学习目标受限、无外部知识的学习协议。五个维度用于训练导航和高风险安全信号，不构成正式法学评分。

持久化契约继续包含：

```json
{
  "learning_target_bounded": true,
  "learning_target_provenance": "source_exact | edited_learning_text | legacy_unverified | source_basis_pending",
  "source_exact": "boolean",
  "source_bounded": "true only when the frozen learning target exactly matches the source basis",
  "external_knowledge_used": false,
  "lexical_source_signal": true,
  "semantic_correctness_verified": false,
  "formal_legal_grade": false
}
```

## 浏览器验收边界

`browser_smoke.py` 与 `browser_ui_round2.py` 使用真实 Chromium + 确定性 Mock API，适合验证视觉、状态和前端交互。

当前执行环境的 Chromium 管理策略会阻止页面直接访问 localhost。`browser_real_e2e.py` 因此使用浏览器请求桥：页面/CSS/JS 在真实 Chromium 中运行，每个 `/api/*` 请求转发到真实 Uvicorn/FastAPI，返回真实后端响应，不使用 Mock API 数据。该测试验证跨层语义接线，但不能冒充直接浏览器网络连接 localhost 的验收。

## 仍需真实用户 Alpha

1. 一章真实中文法学教材的来源基底、KnowledgeUnit 修订率和证据版本变化；
2. Hard/possible conflict 的误报率、漏报率和人工核对成本；
3. 同义改写、双重否定、指代、省略主语和复杂条件句；
4. 错因修复后在隔日、隔周和真题中的复发率；
5. 数百页教材解析、列表、版本历史和备份性能；
6. Windows 启动、125%/150%缩放、触屏和屏幕阅读器；
7. 真实云端 Provider 的超时、结构化输出和降级；
8. 两到四周复习调度效果。

只有这些外部路径完成后，状态才可以升级为 `USER_ACCEPTED`。
