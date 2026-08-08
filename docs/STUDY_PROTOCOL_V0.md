# Study Protocol v0.1

状态：实验性、可运行、仅覆盖 `flashcard` 与 `cloze`。

## 目标

证明学习内容与学习进度可以脱离当前桌面 UI 存在：

`Desktop Runtime -> StudyPack -> Portable Reviewer -> StudyEvents -> Desktop Runtime`

这不是通用插件平台，也不是云同步协议。v0.1 只验证“学习对象可携带、学习行为可回灌、派生状态由权威 Runtime 重算”。

## 第一性原理

1. 内容事实与学习历史分离。
2. 同步 Attempt/Event，不同步 `due_at`、`streak` 等派生状态。
3. 任何事件必须绑定精确 `item_id + item_version + content_hash`。
4. Portable Reviewer 在训练前重新计算 `pack_hash` 校验文件完整性；导入事件还必须基于桌面导出的同一个 StudyPack，并绑定 `pack_id + pack_hash`。
5. 桌面 Runtime 是当前 v0.1 的权威评分与调度者。
6. 冲突宁可显式拒绝，也不能静默覆盖桌面学习历史。
7. 移动端不直接读写 SQLite。

## StudyPack v0.1

协议标识：`study-pack/0.1`

核心字段：

```json
{
  "protocol": "study-pack/0.1",
  "pack_id": "uuid",
  "pack_hash": "sha256",
  "exported_at": "ISO-8601",
  "producer": {"product": "law-study-workbench", "version": "0.8.0"},
  "contract": {
    "event_protocol": "study-events/0.1",
    "authoritative_evaluation": "desktop-runtime",
    "state_sync": "attempt-events-only",
    "offline_capable": true
  },
  "items": []
}
```

每个 item 包含：

- `id`
- `version`
- `type`: `flashcard | cloze`
- `content_hash`
- `knowledge_unit_id`
- `unit_title`
- `content.prompt / answer / cloze_text`
- `source.document_name / page_start / page_end / excerpt`
- `review_base.last_attempt_id / interval_minutes / streak / lapses`

`review_base` 只用于建立事件因果基线；客户端不得把它当成可直接覆盖桌面的 ReviewState。

## StudyEvents v0.1

协议标识：`study-events/0.1`

```json
{
  "protocol": "study-events/0.1",
  "bundle_id": "uuid",
  "pack_id": "uuid",
  "pack_hash": "sha256",
  "device": {
    "id": "portable-device-id",
    "label": "手机复习器",
    "client": "portable-reviewer/0.1"
  },
  "events": []
}
```

每个事件包含：

- `event_id`
- `event_type = retrieval_attempt`
- `item_id`
- `item_version`
- `content_hash`
- `base_last_attempt_id`
- `occurred_at`
- `response_text`
- `rating`
- `elapsed_ms`
- `revealed_answer`

## 导入裁决

桌面端按事件逐条处理：

1. `event_id` 已存在 -> `duplicate`，不重复写入。
2. StudyPack 不属于当前 Runtime -> 整包拒绝。
3. `pack_hash` 不匹配 -> 整包拒绝。
4. item 不存在或停用 -> conflict。
5. item version/hash 漂移 -> conflict。
6. `base_last_attempt_id` 与当前桌面 ReviewState 不一致 -> `history_advanced` conflict。
7. 事件明显早于 Pack 导出时间或明显晚于服务器时间 -> conflict。
8. flashcard 必须包含揭示与自评；评分仍属于 self-report evidence。
9. cloze 只信任 `response_text`，桌面使用当前正式 `grade_cloze` 重新评分。
10. 成功事件写入 `retrieval_attempts`，`snapshot_status=portable_v0`，再由桌面 `retrieval_review_plan` 计算 ReviewState。

事件导入允许部分成功。失败项有逐条 receipt；重试依靠 `event_id` 保证幂等。

## 当前独立客户端

`portable-reviewer/` 是无框架、无桌面 API 依赖的静态移动复习器：

- 导入 StudyPack JSON；
- 闪卡：先揭示，再自评；
- 挖空：输入答案，离线仅字面核对；
- 生成 StudyEvents JSON；
- 支持 `prefers-reduced-motion`；
- 包含 Service Worker 静态缓存；
- 实现本地未导出会话恢复逻辑。
- 导入 Pack 前用 Web Crypto（可用时）或内置 SHA-256 fallback 重算 canonical hash；Pack 被修改/损坏时拒绝进入训练。

当前容器安全策略禁止 Chromium 导航到 localhost、虚拟域名或 file URL，因此 Service Worker 安装和刷新后的原生 localStorage 恢复仍需要手机/真实浏览器 Alpha。Chromium 中的核心训练、事件下载已通过 `set_content + real JS/CSS` 验证。

## 明确非目标

v0.1 不做：

- 云同步；
- 账号和身份体系；
- 第三方插件；
- CRDT；
- 多人协作；
- 跨桌面实例导入；
- 事件签名；
- 加密 StudyPack；
- 通用 LearningItem 类型系统；
- Agent API；
- MCQ / Case / Essay 等更多活动类型。

## 下一阶段判定门

只有真实用户 Alpha 证明以下指标成立，才继续扩协议：

- 手机复习能显著降低打开桌面工作的摩擦；
- StudyPack / StudyEvents 手动往返不造成不可接受的操作成本；
- version/hash/history conflict 能被用户理解；
- 移动端事件恢复可靠；
- 不出现学习证据错位或重复污染。

通过后，优先建设 Sync Transport 与 Agent Route，而不是先造插件市场。
