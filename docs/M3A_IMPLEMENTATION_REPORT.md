# M3A 实现报告

## 结果

产品版本从 `0.4.0` 推进到 `0.5.0`，完成首个版本化法学完整闭卷方法包 `law_full_recall_v1@0.1.0`。当前工程状态为 `LOCALLY_VERIFIED`，没有 Git 元数据，未执行 commit、push、PR、CI 或 release。

## 行为增量

- 会话开始时根据 `objective_type` 选择并冻结方法包。
- 闭卷作答前显示五维训练方向，不提前显示教材答案。
- 提交后返回来源受限五维诊断、来源引用、修复动作和原子引用。
- 方法包快照进入 `feedback_json` 和 `study_events`，重启后可恢复。
- 方法包异常时显式降级，不阻断真实作答。
- 保持 Schema 3、现有请求负载、闪卡/挖空调度和历史证据语义不变。

## 主要修改

- 新增 `app/services/method_packs.py`
- 修改 `app/main.py`
- 修改 `app/static/app.js`、`app/static/styles.css`
- 新增 `tests/test_method_packs.py`
- 扩展 `scripts/http_smoke.py`、`scripts/browser_ui_round2.py`
- 更新版本、架构、验收、交接与方法包文档

## 本地验证

```text
python3 -m compileall -q app tests scripts               PASS
node --check app/static/app.js                            PASS
pytest -q                                                 20 PASS
python3 scripts/http_smoke.py                              PASS
python3 scripts/backup_restore_smoke.py                    PASS
python3 scripts/browser_smoke.py                           PASS
python3 scripts/browser_ui_round2.py                       PASS
```

真实 HTTP 冒烟覆盖方法包选择、完整闭卷提交、五维结果、卡片提取以及服务重启后的方法包和卡片恢复。Chromium 回归覆盖桌面与 390px 移动端方法包和五维诊断，同时保留既有主题、卡片、窄屏和断线重连检查。

## 剩余风险

- 五维分数是文本启发式，尚未用用户真实法学教材进行误判率校准。
- 术语抽取、规则/例外模式和中文长句切分仍可能漏检。
- `app/main.py` 和 `app/static/app.js` 仍是大型单体文件，本切片控制了改动半径，没有顺手重构。
- 259 个原子尚未完成全量运行时映射；本切片仅追溯实际使用的 12 个原子。
- 真实 Windows、真实教材、长期学习效果和云端 Provider 仍待外部验收。
