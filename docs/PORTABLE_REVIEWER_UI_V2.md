# Portable Reviewer UI v2

## 范围

本轮只重构 `portable-reviewer/` 的视觉与交互呈现，Study Protocol、SQLite Schema、桌面 Runtime、评分和调度语义保持不变。

视觉命题：**冷静理性 + 暖纸题页 / 墨石外壳 / 铜件操作 + 册页边注 + 揭页式反馈 + 高频训练区克制。**

## 主要变化

- 导入页从工具表单升级为“导入 → 提取 → 回灌”的清晰任务入口。
- 训练区采用深色外壳 + 暖纸题页，来源、题面、回答、目标答案具有明确视觉职责。
- 闪卡答案揭示后出现四档自评，按钮包含“尽快重来 / 仍需加固 / 正常推进 / 稳定提取”的视觉副标签，但无障碍名称保持原有四档名称。
- 挖空核对后隐藏冗余的“核对答案”按钮，让“记录并下一题”成为唯一主动作。
- 增加待同步事件计数；设备支持时提供轻微震动反馈，失败时静默降级。
- 文件导入 label 补充键盘焦点与 Enter/Space 激活。
- 支持系统浅色/深色、320/390/430 手机尺寸、120% 文字缩放及 reduced-motion。
- PWA icon、theme/background 色与新视觉系统统一。

## 保护边界

以下内容未修改：

- `app/` 全部代码；
- SQLite Schema 4；
- StudyPack / StudyEvents 0.1 字段与 canonical hash；
- 桌面导入冲突、幂等、时钟校正与调度逻辑；
- 闪卡/挖空最终证据语义。

## 验证

- `diff -qr <v0.8 base>/app <ui-v2>/app`：无差异。
- `pytest -q`：44 项通过。
- `python3 scripts/study_protocol_roundtrip_smoke.py`：通过。
- `python3 scripts/portable_reviewer_smoke.py`：通过。
- `python3 scripts/portable_reviewer_ui_v2.py`：320/390/430、浅深主题、120% 文字、focus、触控尺寸、reduced-motion 通过。
- `python3 scripts/study_protocol_browser_roundtrip.py`：真实 Pack → 独立 Chromium → StudyEvents → Runtime 通过。

## 仍待真实设备验证

PWA 安装、Service Worker 生命周期、iOS/Android 浏览器被系统回收后的 localStorage 恢复、真实触觉反馈需要手机实机 Alpha。
