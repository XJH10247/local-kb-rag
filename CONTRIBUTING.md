# 贡献指南

感谢关注 local-kb-rag。本仓库是一个 **monorepo**：

- `skills/local-kb-rag/` — 可安装的 Skill 包，自包含，是真正的交付物
- 仓库根 — GitHub 项目文档、元数据与 CI，**不参与 Skill 运行时**

## 目录与命名约定

新增文件前请先确认落位与命名。命名按语言/类型区分，不要混用：

| 类型 | 约定 | 示例 |
|---|---|---|
| Python 模块与测试 | `snake_case`，测试为 `test_*.py` | `rag_pipeline.py`、`test_split_smoke.py` |
| PowerShell 脚本 | `kebab-case` | `install-env.ps1`、`test-e2e.ps1` |
| 仓库根标准文档 | `UPPER_SNAKE.md` | `README.md`、`CONTRIBUTING.md`、`CHANGELOG.md` |
| 其他 Markdown 文档 | `kebab-case.md` | `docs/architecture.md` |
| JSON 配置 | `snake_case.json` | `meta.json`、`info.json` |

**不要改名的文件**（属于外部契约，改名会打断宿主集成）：

- `skills/local-kb-rag/scripts/run.ps1` — Skill 固定 CLI 入口
- `skills/local-kb-rag/scripts/mcp_adapter.py` — 用户 `mcp.json` 中注册的路径
- `skills/local-kb-rag/SKILL.md`、`meta.json`、`info.json` — Skill 平台约定文件名

## 结构硬约束

1. **Skill 包必须自包含**：`skills/local-kb-rag/` 内脚本的相对路径只允许依赖该目录内部文件
   （通过 `Path(__file__)` / `$PSScriptRoot` 解析），禁止引用仓库根文件。
2. **不得在 `skills/local-kb-rag/` 内放置 `README.md`**（Skill 包规范要求目录内只保留
   `SKILL.md` 承载元数据）。项目说明统一写在仓库根 `README.md`。
3. **不要提交**：`__pycache__`、`*.pyc`、模型权重、`%USERPROFILE%\.openvino\` 运行时数据。
4. **元数据单一事实来源**：`pyproject.toml` 的 `name` / `version` / `license`
   必须与 `skills/local-kb-rag/meta.json`、`SKILL.md` frontmatter 一致，由 CI 校验。
5. **PowerShell 脚本编码**：含非 ASCII（中文）字符的 `.ps1` 必须带 **UTF-8 BOM**。
   Windows PowerShell 5.1 在无 BOM 时按当前 ANSI 代码页解码脚本，中文字符串字面量
   会被截断，直接导致「字符串缺少终止符」之类的解析错误而无法运行。
   保存时请确认编辑器没有把 BOM 去掉，CI 会校验这一点。
6. **换行符**：由 `.gitattributes` 统一管理（源码/文档 LF，`.ps1` CRLF）。
   不要自行修改 `core.autocrlf`，也不要手工转换换行符。

## 开发环境

- Windows + Python 3.10 – 3.12
- 完整运行时：执行 `skills\local-kb-rag\scripts\install-env.ps1`（国内网络可加 `-Mirror`）
- 只改切分/解析逻辑时无需安装 OpenVINO，直接跑轻量冒烟即可

## 本地检查

提交 PR 前请至少跑完前两项：

```powershell
# 1. 切分逻辑冒烟（轻量，秒级，不需 OpenVINO / 模型）
python skills\local-kb-rag\tests\test_split_smoke.py

# 2. 仓库元数据与结构约定校验（CI 同款）
python .github\scripts\check_metadata.py

# 3. 端到端测试（可选，需 Windows AIPC + 已下载模型，耗时长）
powershell -ExecutionPolicy Bypass -File skills\local-kb-rag\tests\test-e2e.ps1
```

预期输出：`SMOKE-OK: ...`、`METADATA-OK`、端到端脚本 `FAIL: 0`。

## 提交信息

采用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)：

```text
<type>(<scope>): <subject>
```

常用 `type`：`feat`、`fix`、`docs`、`refactor`、`perf`、`test`、`chore`、`ci`。
`scope` 常用取值：`skill`、`scripts`、`docs`、`ci`、`repo`。

例：`fix(scripts): 修正 pipe_client 在 server 硬崩后的重试预算`

## PR 约定

- 说明动机与可观察的行为变化（用户可见的 CLI / MCP 工具行为）
- 列出你**实际运行过**的检查命令与结果，不要只写「已测试」
- 涉及 `info.json` / `requirements.txt` 变更时，说明兼容性与磁盘、内存、模型下载量的影响
- 新功能优先补上可独立验证的测试或可复现步骤
- 文档与代码同步更新：README 路径、SKILL.md 工具表、退出码表、CHANGELOG

## 高影响改动

以下改动会影响既有用户，请在 PR 中显著标出并说明迁移方式：

- named pipe 协议或 authkey
- MCP 工具名称 / 参数 / 返回结构
- 默认模型、设备偏好、chunk 参数
- 退出码语义
- `run.ps1` / `mcp_adapter.py` 的路径或行为

## 不在范围内

- 把语料或向量上传到云端、引入非本地推理后端
- 创建远端 GitHub 仓库或发布流程本身
- 多语言 README（主要受众为简体中文）

## 文档索引

- [`README.md`](README.md) — 项目简介、安装、使用
- [`NOTICE.md`](NOTICE.md) — 上手注意事项、地址占位说明、修改源码的硬约束
- [`docs/architecture.md`](docs/architecture.md) — 架构、协议、生命周期
- [`CHANGELOG.md`](CHANGELOG.md) — 变更记录
- [`SECURITY.md`](SECURITY.md) — 安全策略与威胁模型

> 修改仓库根文件清单时注意：`NOTICE.md` 与 `README.md` 的“NOTICE.md 引用”
> 由 `.github/scripts/check_metadata.py` 强制校验，删除或漏引会导致 CI 失败。

## 许可证

贡献即表示同意以 [Apache-2.0](LICENSE) 授权你的提交。
