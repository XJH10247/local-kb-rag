# Changelog

本项目的所有重要变更都会记录在此文件。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/spec/v2.0.0.html)。

> 本仓库不预设远端地址。各版本的 diff 链接可在上传到 GitHub 后按
> `<REPO_URL>/compare/vX..vY` 格式补充。

## [Unreleased]

### Added

- **`NOTICE.md`**（仓库根）：面向克隆者的上手须知单页，涵盖
  - 环境要求（Python 3.10–3.12 硬上限、仅 Windows、内存/磁盘/网络）
  - 克隆后必做的两步（`install-env.ps1`、首次运行触发模型下载）
  - 4 处地址占位的说明与「留空不影响核心功能」的明确结论
  - 给部署者的额外提醒（开启私有漏洞报告、CI 无需改地址等）
  - 修改源码的硬约束（`.ps1` 必须带 UTF-8 BOM、Skill 包不放 README 等）
  - 隐私与安全边界
- `README.md` 顶部新增「⚠️ 克隆本仓库后请先阅读」区块，以表格列出 4 条关键注意事项并链向 `NOTICE.md`
- `.github/scripts/check_metadata.py` 新增两项强制校验：`NOTICE.md` 必须存在、`README.md` 必须引用它

### Changed

- **移除仓库地址绑定**：不再将任何具体远端地址写死进仓库。涉及位置改为占位符或动态获取：
  - `.github/ISSUE_TEMPLATE/config.yml` 的 3 处 URL → `<OWNER>/<REPO>` 占位（该文件只接受绝对 URL，无法动态获取；也可整体删除 `contact_links` 段规避）。文件头部已加入下游部署者提醒注释
  - `README.md` 顶部 CI 徽章 → 注释块 + `<OWNER>/<REPO>` 占位，并附 shields.io 动态徽章写法作为免写死的替代方案
  - `README.md` 的 `git clone` 地址 → `<REPO_URL>` 占位
  - `pyproject.toml` 的 `[project.urls]` → 整体注释（本项目不作为 Python 包分发，缺失不影响功能）
  - `SKILL.md` / `CHANGELOG.md` → 移除硬编码仓库链接
- `.github/ISSUE_TEMPLATE/bug_report.yml`：修正指向 `SECURITY.md` 的无效相对链接（`../blob/main/` 在该上下文无法解析），改为纯文本引用
- `README.md`：维护者清单重写为「上传到 GitHub 后的检查清单」，并修正重复的章节序号
- `README.md` / `SKILL.md`：宿主相关表述去厂商化，改为「Agent 宿主」「MCP / CLI」，避免绑定特定宿主产品
- `SKILL.md`：description 精简，正文增补 `NOTICE.md` 指引
- `CONTRIBUTING.md`：文档索引补充 `NOTICE.md`，并说明其受 CI 强制校验


## [1.0.0] - 2026-09-13

首个公开发布版本：`local-kb-rag` 作为可安装 Skill 打包为 GitHub 可托管仓库。

### Added

- 仓库级文档：`README.md`、`CONTRIBUTING.md`、`CODE_OF_CONDUCT.md`、`SECURITY.md`、`CHANGELOG.md`
- 项目元数据清单 `pyproject.toml`：统一声明名称、描述、关键词、版本、许可证、作者与 Python 版本约束
- Apache-2.0 `LICENSE`（Copyright 2026 local-kb-rag contributors）
- GitHub Actions 工作流 `.github/workflows/ci.yml`，含两个作业：
  - `metadata`：校验 `pyproject.toml` / `meta.json` / `SKILL.md` 元数据一致性与仓库结构约定
  - `smoke`：运行切分逻辑冒烟测试（不安装 OpenVINO，秒级完成）
- Issue 模板（`bug_report.yml` / `feature_request.yml` / `config.yml`）与 Pull Request 模板
- `docs/architecture.md`：分层架构、named pipe 协议、server 生命周期与运行时数据布局
- `assets/sample-note.md` 示例语料，供端到端测试与首次体验使用

### Changed

- 仓库结构改为 monorepo：可安装 Skill 包整体位于 `skills/local-kb-rag/`，仓库根仅保留项目文档与共享配置。Skill 包保持自包含，脚本内相对路径全部基于 `Path(__file__)` / `$PSScriptRoot` 解析，不依赖仓库根文件
- 统一文件命名约定（Python `snake_case` / PowerShell `kebab-case` / 仓库文档 `UPPER_SNAKE` / 其他文档 `kebab-case`）：
  - `skills/local-kb-rag/scripts/client.py` → `scripts/cli.py`（与传输层 `pipe_client.py` 区分）
  - `skills/local-kb-rag/scripts/rag_client.py` → `scripts/pipe_client.py`（语义即 named pipe 传输层）
  - `skills/local-kb-rag/tests/test.ps1` → `tests/test-e2e.ps1`
  - `.github/workflows/smoke.yml` → `.github/workflows/ci.yml`
- `meta.json` 的 `author` 统一为 `local-kb-rag contributors`，`description` 表达与 `pyproject.toml` 对齐
- `SKILL.md` frontmatter 补充 `license`，Python 版本要求与 `pyproject.toml` 的 `requires-python` 对齐
- `.gitignore` 规范化：补充构建产物、测试缓存、编辑器与打包产物忽略规则
- 新增 `.gitattributes` 固定换行符策略（源码与文档 LF、PowerShell 脚本 CRLF、二进制不转换），使行为不再依赖各机器的 `core.autocrlf`
- `README.md` 全面重写

### Removed

- `skills/local-kb-rag/scripts/__pycache__/` 字节码缓存（可再生，不应入库）
- 空目录 `.worktrees/` 与 `docs/compose/`
- `docs/specs/`：开发期的交付规格与过程记录（含任务编号、复审结论、分支与历史提交信息），属内部产物，不随公开仓库分发；相关引用已从 README、CONTRIBUTING 与 CHANGELOG 移除

### Fixed

- `skills/local-kb-rag/tests/test-e2e.ps1` 在 Windows PowerShell 下完全无法解析。脚本含中文字符串字面量（如 `'什么是叠加态'`）却未带 UTF-8 BOM，PowerShell 5.1 按 ANSI 代码页解码后字面量被截断，报「字符串缺少终止符」。为 `scripts/run.ps1`、`scripts/install-env.ps1`、`tests/test-e2e.ps1` 统一补上 UTF-8 BOM，并在 CI 中加入防回归校验（含非 ASCII 的 `.ps1` 必须带 BOM）

### Security

- 隐私设计不变：语料、向量库与模型权重全部驻留本机，仅答案文本回传 Agent 宿主；首次模型下载完成后可完全离线运行
