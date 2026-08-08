# Portable Reviewer UI v2

- 重构独立随身复习器为“金石理性 × 纸本编辑部”移动视觉系统。
- 升级导入、题卡、答案揭示、四档评级、待同步状态和完成页。
- 增加浅深主题、320/390/430 响应式、键盘导入入口与 reduced-motion。
- Study Protocol 仍为 0.1；桌面 Runtime、Schema、评分和调度语义不变。

# Changelog

## 0.8.0

- 新增实验性 `StudyPack v0.1 / StudyEvents v0.1`，把闪卡/挖空训练内容与桌面 SQLite 备份格式分离。
- 桌面新增 StudyPack 导出和 StudyEvents 回灌；事件绑定卡片版本/hash、Pack 身份和导出时的 `base_last_attempt_id`，支持 event-id 幂等和显式冲突回执。
- 移动端不写 ReviewState；闪卡为自评证据，挖空由桌面重新执行正式本地 grade，下一次复习时间由桌面 scheduler 权威重算。
- 新增独立 `portable-reviewer/`：无桌面 API 依赖的静态 HTML/CSS/JS 移动复习器，可导入包、完成训练并下载事件文件；实现本地未导出会话恢复与 PWA shell。
- 新增真实跨端文件往返验证：真实 FastAPI 导出 StudyPack → Chromium 独立复习器训练并下载 StudyEvents → 原文件回灌真实 FastAPI → SQLite ReviewState 更新。
- 对抗覆盖重复事件、历史前进、item 版本漂移、未知/伪造 Pack、未来/回拨设备时钟；事件校正时间与调度时间统一。
- Schema 保持 4；没有加入云同步、账号、CRDT、插件市场或跨实例自动合并。
- 自动化测试增至 44 项。

## UI v3.0（0.7.0 兼容，前端重构）

- 采用“金石理性 × 纸本编辑部”视觉方向，重建深浅主题 Design Tokens、字体角色、边界/圆角/材质和 Application Shell。
- Today、Library、Study、Retrieval、Evidence、Settings 统一从圆角 SaaS 卡片语法转向册页、边注、纸本和索引柜式空间秩序。
- 保留现代功能语言和全部后端/API/Schema 4/学习证据语义；未引入远程字体、图片、WebGL 或新前端依赖。
- 移动端导航使用短视觉标签但保留完整 accessible name；修复 430px 教材库响应式覆盖问题。
- 新增 `browser_ui_v3.py`，覆盖 320/390/430/768/1024/1440/1700、reduced-motion、focus-visible 和 120% 字体比例补充检查。

## 0.7.0

- SQLite 升级到 Schema 4；新增 `knowledge_unit_versions`，并给 KnowledgeUnit、StudySession、Attempt、ReviewState 增加材料版本/哈希/快照契约。
- 完整闭卷 Session 冻结材料与学习目标；活动会话期间禁止修改正文/目标，历史 Session/Attempt 不再随当前 KnowledgeUnit 漂移。
- 正文或 `objective_type` 变化产生新证据版本并使旧当前掌握失效；标题独立修改不产生新证据版本。
- 新增 `evidence_integrity.py`，将 Provider 原始覆盖分与有效学习证据分分离；Hard Conflict 真正阻断 ReviewState/调度并产生 `critical_legal_conflict`。
- `law_full_recall_v1` 升级到 `0.3.0`；Legal Signals 增强主体关系、数字—动作绑定、短规则、双向矛盾和中文标点关键词堆砌检测，并将复杂否定保守分为 possible/uncertain。
- 来源基底与可编辑学习文本分层；草稿默认先审核，后端也拒绝未显式批准的 draft 直接进入正式闭卷。
- Error repair 关闭门升级：对应 repair session 的新复测必须无提示、有效分>=70、证据权重>=0.99 且 verdict=accepted。
- 自动化测试增至 36 项；增加真实 Chromium UI 请求桥接真实 FastAPI 的跨层关键冲突 E2E。
- Schema 3 历史 full-recall snapshot 无法精确重建，迁移显式标记 `legacy_backfilled_current` 并保守失效无法证明属于当前正文的旧 ReviewState。

## 0.6.0

- 新增法律关键冲突闸门，覆盖极性/效力、善恶意、期限数字、常见主体等高风险信号；挖空命中关键冲突固定进入 `again`。
- `law_full_recall_v1` 升级到 `0.2.0`，五维结果改为“来源恢复检查”，增加 `critical_conflict` / `uncertain`，明确 `semantic_correctness_verified=false`。
- 新增 KnowledgeUnit 审核器：标题/正文/材质编辑、确认、按光标拆分、相邻合并。结构变化归档旧单元并使旧活动卡片 `stale`，历史作答保持原 ID。
- 归档 KnowledgeUnit 退出今日复测、当前掌握统计、活动卡片与错因修复队列，并拒绝通过直接 API 重新启动学习或建立卡片。
- 启用错因 `open → repairing → resolved` 状态机；关闭错因前必须在对应修复会话中完成新的无提示完整闭卷，并由用户人工确认。
- 前端把“学习者模型”降级为“学习证据画像”，并明确考试日期/每日学习分钟暂未参与任务排程。
- 自动化测试增至 25 项；真实 HTTP 增加关键冲突与错因修复链；Chromium 增加 KnowledgeUnit 审核器和错因修复队列回归。
- 保持 SQLite Schema 3；没有修改历史 Attempt、卡片作答快照或既有来源证据。

## 0.5.0

- 新增 `law_full_recall_v1@0.1.0` 版本化法学完整闭卷方法包。
- 按知识单元目标类型确定性选择训练重点，并在会话开始时冻结选择快照。
- 闭卷界面新增核心设问、规则与要件、例外与边界、法律效果、术语与规范表达五个训练维度。
- 提交后新增来源受限五维诊断、修复动作、来源引用、原子引用和明确的非正式评分标记。
- 方法包快照写入 `attempts.feedback_json` 和 `study_events`，服务重启后保持历史版本可读。
- 方法包异常时显式降级到 `local_evidence_v1`，不阻断真实作答提交。
- 新增 5 项方法包单元/集成/兼容/降级测试，测试总数增至 19。
- 扩展真实 HTTP 冒烟，覆盖完整闭卷方法包、持久化和重启恢复；扩展 Chromium 回归，覆盖桌面与 390px 移动端五维诊断。
- 保持 SQLite Schema 3、既有请求负载、闪卡/挖空调度和历史卡片快照语义不变。

## 0.4.0

- 完成第二轮 UI/UX 深度重构，冻结后端 API、数据库 Schema 和学习证据语义。
- 重建 Application Shell，增加今日轨道、页面上下文说明、主题切换、快捷键入口和移动端底部导航。
- 今日学习页改为状态驱动的单一主行动，并增加证据账本、今日计划轨道和分层任务队列。
- 教材库改为来源轨道与知识单元工作区，增加搜索、状态筛选、来源质量信息和更清晰的操作层级。
- 闭卷学习改为三阶段工作台，增加来源、编辑器和证据栏三列布局、草稿状态、字数、置信度、回忆检查项、提示债务和证据权重。
- 反馈页重构为结果总览、四类诊断、来源证据和复测工单。
- 挖空与闪卡中心增加队列进度、卡片筛选、搜索、专注练习、键盘评分和移动端结果界面。
- 学习者模型增加置信度校准、掌握分布、优先错误和最近证据时间线。
- 手动建卡和编辑改为可访问的 `<dialog>` 表单，移除浏览器 `prompt()` 交互。
- 新增深色、浅色、系统主题、舒适/紧凑密度、字体比例和减少动效偏好，本地持久化。
- 新增 `browser_ui_round2.py`，覆盖桌面深色、浅色、390px 手机、快捷键、对话框、结果页和横向溢出检查。

## 0.2.0

- 新增统一的 `retrieval_items` 主动提取对象，支持闪卡与单空挖空题。
- 新增本地规则生成器、内容哈希去重、来源摘录和页码回指。
- 新增闪卡答案揭示与四档自评；服务端确认本轮揭示后才允许评分，一次揭示只对应一次提交。
- 新增挖空本地规范化、相似度评分、标准答案和来源反馈。
- 新增卡片级作答记录、复习状态、连续成功、遗忘次数和可解释调度。
- 新增卡片中心、今日到期卡片、知识单元自动生成与手动建卡入口、编辑和停用交互。
- 新增知识单元内容变化后的旧卡片失效机制；历史作答固化题面、答案、来源、内容哈希和卡片版本快照。
- 再次生成时可重新启用仍与当前知识单元一致的 stale 卡片，用户主动停用的卡片不会被自动复活。
- Schema 升级到 3；增加 v1/v2 数据库无损迁移测试，并明确标记 Schema 2 历史快照的回填来源。
- 新增真实 Uvicorn HTTP 冒烟测试和扩展 Chromium 界面冒烟测试。

## 0.1.0

- 建立 FastAPI + SQLite 本地优先原型。
- 增加 PDF 魔数验证、流式写入、SHA-256 去重、后台页级解析和质量状态。
- 增加知识单元启发式生成、来源页码和目标类型。
- 增加唯一活动闭卷会话、提示记录、草稿自动保存、置信度、计时和重启恢复。
- 增加本地证据覆盖评分 Provider、错因、证据权重、掌握状态和复测排程。
- 增加今日学习、教材库、闭卷学习、学习者模型和设置界面。
- 增加结构化数据导出、完整本地备份和受控恢复。
- 增加自动化后端测试和 Chromium 浏览器冒烟测试。

## Portable Reviewer UI v2.1

- Removed the high-contrast “dark shell around white paper” treatment in dark mode.
- Rebuilt the practice card as deep warm paper with off-white ink and low-contrast grid/edge detail.
- Removed the near-black folio strip from light mode and replaced it with warm tonal paper/stone.
- Preserved Portable Reviewer behavior and Study Protocol 0.1 semantics.
