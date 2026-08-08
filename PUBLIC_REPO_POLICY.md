# PUBLIC_REPO_POLICY — 公开仓库政策

本仓库是 **Public（公开）** 仓库。公开仓库只保存：

- 可公开的源码
- 协议（protocols）
- 测试代码
- 匿名 / 合成测试材料
- 经过检查的项目文档

## 严禁提交（FORBIDDEN）

以下内容**一律不得**提交到本公开仓库：

| 类别 | 示例 / 说明 |
| --- | --- |
| 真实用户教材与商业版权材料 | 教材 PDF、出版物、商业课程内容 |
| Source excerpt 数据集 / 来源摘录 | 数据集及其来源摘录 |
| StudyPack / StudyEvents 学习活动数据 | `StudyPack*.json`、`StudyEvents*.json` 等 |
| SQLite 数据库 | `*.db`、`*.sqlite`、`*.sqlite3` |
| 学习历史 | 用户学习记录、进度数据 |
| 环境变量 | `.env`、`.env.*` |
| Token / API Key | 令牌、密钥、凭据文件（`*.pem`、`*.key` 等） |
| 本机用户名与私人绝对路径 | 如 `C:\Users\<用户名>\...`、`D:\...` 个人目录 |

## 提交前检查

每次提交前确认：

1. `git status` 中只包含计划提交的文件；
2. 不包含上述任何禁止类别；
3. 不包含本机私人路径、用户名、密钥。

> 本仓库处于 **Personal Alpha / Research Preview** 阶段，仅用于个人 Alpha 开发与测试，不代表 production ready。
