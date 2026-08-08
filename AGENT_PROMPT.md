你正在维护“法学语义学习工作台” v0.8.0。先阅读 START_HERE.md、docs/PRODUCT_INVARIANTS.md、docs/ARCHITECTURE.md、docs/V0.7_EVIDENCE_INTEGRITY_REPORT.md、docs/STUDY_PROTOCOL_V0.md、docs/V0.8_PORTABLE_STUDY_REPORT.md、.agent/PROJECT_STATE.md 和 AGENT_HANDOFF.md。

先做只读预检：检查 Git/源码快照状态、用户数据目录、SQLite Schema 4、当前 KnowledgeUnit/Session/Attempt/ReviewState 证据契约、测试和相关调用链。不得删除或重置用户 `data/`。在修改前明确本轮可观察目标、保护区、Schema/迁移影响、验证命令和回滚路径。

核心不变量：StudyPack/StudyEvents 只同步 Attempt/Event、桌面 Runtime 权威评分和调度、portable event 必须绑定 item/pack/base-history 身份且冲突显式拒绝；教材来源与可编辑学习文本分层；学习证据绑定当时 KnowledgeUnit version/body_hash/Session snapshot；正文或学习目标改版后旧 ReviewState 不得继承；Hard Conflict 必须真实影响有效证据分、掌握、调度和错因；Possible Conflict 保守进入待核验；历史 evidence 不随当前材料改写；没有真实作答不产生掌握；错因 resolved 必须有对应 repair session 的新有效无提示复测和人工确认；AI/启发式不得冒充正式法学阅卷或权威法律结论。

完成后至少运行：compileall、桌面与 portable reviewer 的 node --check、pytest、真实 HTTP、备份恢复以及与改动相关的 Chromium 验证；涉及 Portable Study 时还要运行三条 study_protocol/portable_reviewer roundtrip smoke。若修改跨越 UI 与后端证据语义，优先补真实 Chromium UI → 真实 FastAPI 的跨层验收。当前容器若继续阻止 Chromium 直接 localhost 网络访问，可使用现有 browser_real_e2e 请求桥，但必须如实标注其边界。

交付时严格区分 EDITED / LOCALLY_VERIFIED / COMMITTED / PUSHED / PR_UPDATED / CI_PASSED / RELEASED，并更新 PROJECT_STATE、CHANGELOG 和 HANDOFF。
