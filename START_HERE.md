# START HERE

## 普通使用者

1. 确保电脑安装 Python 3.11+。
2. Windows 双击 `START_WINDOWS.bat`；macOS/Linux 运行 `./START_UNIX.sh`。
3. 浏览器打开 `http://127.0.0.1:8765`。
4. 在“本地教材库”导入文字型 PDF。
5. 先审核 KnowledgeUnit：对照“教材来源快照（只读）”，修订“学习单元文本（可编辑）”和学习目标；必要时拆分/合并。
6. 审核后进入完整闭卷。Session 会冻结本轮材料版本和学习目标，提交后查看“有效学习证据分”、来源恢复信号、关键冲突和待语义核对项。
7. 正文或学习目标后续改版时，旧掌握不会自动继承到新版本；新版本需重新形成证据。
8. 闪卡先独立回忆再显示答案；挖空命中高置信关键冲突时进入立即重做。
9. 在“学习证据”处理开放错因；只有对应修复 session 的新无提示有效复测达到门槛后，才会解锁人工确认关闭。
10. 关闭并重启应用，检查活动会话、历史材料快照、卡片、错因和到期任务仍可恢复。

自动分块、卡片和本地语义信号都属于学习辅助。正式复习前仍应核对权威教材；当前系统不提供正式法学阅卷或法条效力核验。

### 随身复习实验（v0.8.0）

1. 在“设置 → 随身复习实验”导出“今日 StudyPack”或“全部卡片”。
2. 打开 `portable-reviewer/index.html`（真实手机 Alpha 建议通过本地 HTTPS/静态托管打开），导入 StudyPack。
3. 离线完成闪卡/挖空后下载 StudyEvents JSON。
4. 回到桌面“设置 → 随身复习实验”，导入 StudyEvents。
5. 桌面会逐条显示 imported / duplicate / conflict，并由本地 Runtime 重新评分和计算 ReviewState。

当前这条链是**同一桌面 Runtime + 手动文件往返**。StudyPack 含答案与来源摘录，按私人学习文件处理；不要把它当成可公开分享的脱敏卡包。

## 开发者

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
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
.venv/bin/python -m uvicorn app.asgi:app --host 127.0.0.1 --port 8765
```

`browser_real_e2e.py` 在当前受限容器中采用真实 Chromium 页面 + 请求桥接真实 Uvicorn/FastAPI；它不使用 Mock API 数据，但也不等于浏览器直接 TCP 访问 localhost。

## 数据保护

Schema 4 修改了学习证据契约。开发、迁移或回退前先运行：

```bash
python3 scripts/backup_local.py
```

回退 v0.6.0 或更早代码前必须恢复 Schema 4 升级前备份。详见 `ROLLBACK.md`。

## 当前完整链路

```text
本地 PDF
→ SourcePage / 来源基底
→ KnowledgeUnit 人工审核
→ KnowledgeUnitVersion
├→ 完整闭卷 Session 材料冻结
│  → 原始来源覆盖
│  → 方法包/法律信号
│  → Evidence Verdict
│  → 精确版本 ReviewState / ErrorRecord
│  → 修复 Session → 有效复测 → 人工确认
└→ 闪卡/挖空 → 卡片快照 → 卡片级复习
→ 重启恢复 / 导出 / 备份
```
