# Alpha Performance Baseline

生成时间：2026-08-09T06:38:00.147926+00:00
环境：Windows / Python 3.12.3 / SQLite WAL / 本机合成数据（tempdir，不含真实数据）

## 规模

- 合成知识单元：150
- 合成检索项（flashcard/cloze）：1001
- 导入 StudyEvents：500
- 数据库大小：2516 KiB

## 测量

| 操作 | 耗时 |
| --- | --- |
| seed_sources | 18.855 s |
| seed_retrieval_items | 5.917 s |
| due_query | 0.017 s |
| pack_export | 0.105 s |
| events_import | 7.243 s |
| summary_after_import | 0.016 s |
| backup | 0.104 s |
| restore_validate | 0.062 s |
| startup_health | 0.094 s |

## 说明

- 全部为合成数据，测量前无真实用户数据参与。
- 若单条本地操作出现明显秒级以上异常或 N² 行为，需定位根因并做低风险修复。
- 真实设备（手机）PWA 与真实教材规模仍为 REAL_DEVICE_PENDING / REAL_USER_ALPHA_PENDING。
