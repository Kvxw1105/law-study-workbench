# 回滚与恢复

## 修改代码或升级 Schema 前

```bash
python3 scripts/backup_local.py
```

脚本使用 SQLite backup API 创建一致数据库快照，并打包 `library/` 教材。

## Schema 4 迁移注意

v0.7.0 会把 Schema 3 升级到 Schema 4，新增 KnowledgeUnit 证据版本、来源基底、Session/Attempt 材料快照和 ReviewState 版本绑定。

Schema 3 的历史 full-recall session 没有精确材料快照。迁移只能用升级时可观察到的当前 KnowledgeUnit 回填，并标记 `legacy_backfilled_current`。该状态不能被解释成精确历史。

旧 ReviewState 如果无法证明对应当前正文，会被保守失效。迁移不会删除历史 Attempt/RetrievalAttempt；但旧版代码不了解 Schema 4 的证据语义，因此：

**回退 v0.6.0 或更早版本前，必须恢复 Schema 4 升级前的完整备份。**

不要仅把代码文件换回旧版后继续写同一个 Schema 4 数据库。

## 恢复本地学习库

1. 关闭工作台和所有访问 `workbench.db` 的进程。
2. 确认目标备份。
3. 执行：

```bash
python3 scripts/restore_local.py data/backups/law-study-backup-YYYYMMDD-HHMMSS.zip
```

4. 输入 `RESTORE` 确认。
5. 重启并检查教材、KnowledgeUnit 版本、活动会话、最近 Attempt、ReviewState、卡片和错因。

恢复脚本执行数据库完整性检查。当前数据目录会移动到 `rollback-时间戳/`，不会直接销毁。

## 仅回滚代码

若未来进入 Git 管理，优先使用新分支或 `git revert`。不要执行 `git clean -fdx`，它可能删除本地学习数据、备份和验收材料。

## 证据对象回滚原则

- 用户作答、历史 Session/Attempt/RetrievalAttempt 和事件属于受保护证据，不静默删除或改写。
- 派生卡片可 stale/重建，但历史卡片作答快照保留。
- KnowledgeUnit 新版本不能借用旧版本 ReviewState。
- 旧错误如果因新证据版本失去当前意义，使用 `superseded`，不要伪装成 `resolved`。
