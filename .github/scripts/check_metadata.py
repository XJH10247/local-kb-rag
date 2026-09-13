# -*- coding: utf-8 -*-
"""仓库元数据与结构约定校验（CI `metadata` 作业使用）。

只依赖 Python 标准库（tomllib 需 3.11+），在 Linux/macOS/Windows 上均可运行。

校验内容：
  1. 仓库根必备文件齐全（README / LICENSE / 贡献指南 / 变更日志 / 行为准则 / 安全策略）
  2. `pyproject.toml` 的 `[project]` 元数据完整（名称 / 描述 / 关键词 / 版本 / 许可证）
  3. `skills/local-kb-rag/meta.json` 与 `pyproject.toml` 的 name / version / license 一致
  4. `skills/local-kb-rag/SKILL.md` frontmatter 合规，且 name / license 对齐
  5. Skill 包自包含约定：内部不得出现 README.md，必备文件齐全（run.ps1 等固定入口）
  6. README.md 覆盖项目简介 / 功能特性 / 目录结构 / 安装步骤 / 使用说明 / 贡献指南 / 许可证
  7. 仓库内无 `__pycache__` / `*.pyc` 等可再生缓存

用法：
    python .github/scripts/check_metadata.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "local-kb-rag"

errors: list[str] = []
warnings: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


# ---------------------------------------------------------------------------
# 1. 仓库根必备文件
# ---------------------------------------------------------------------------
REQUIRED_ROOT_FILES = (
    "README.md",
    "NOTICE.md",
    "LICENSE",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    ".gitignore",
    ".gitattributes",
    "pyproject.toml",
    ".github/workflows/ci.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    "docs/architecture.md",
)
for rel in REQUIRED_ROOT_FILES:
    check((REPO_ROOT / rel).is_file(), f"缺少仓库根文件：{rel}")

# ---------------------------------------------------------------------------
# 1b. README 必须显著提示 NOTICE.md（克隆者能一眼看到上手注意事项）
# ---------------------------------------------------------------------------
readme_path = REPO_ROOT / "README.md"
if readme_path.is_file():
    readme_text = readme_path.read_text(encoding="utf-8")
    check("NOTICE.md" in readme_text,
          "README.md 未提及 NOTICE.md —— 克隆者将看不到上手注意事项")

# ---------------------------------------------------------------------------
# 2. pyproject.toml 项目元数据
# ---------------------------------------------------------------------------
pyproject: dict = {}
try:
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        pyproject = tomllib.load(f)
except Exception as exc:  # noqa: BLE001
    errors.append(f"pyproject.toml 解析失败：{exc}")

project = pyproject.get("project", {})
for field in ("name", "version", "description", "license", "keywords",
              "requires-python", "readme"):
    check(bool(project.get(field)), f"pyproject.toml 的 [project].{field} 缺失或为空")

keywords = project.get("keywords") or []
check(isinstance(keywords, list) and len(keywords) >= 5,
      "pyproject.toml 的 [project].keywords 至少需要 5 个关键词")

# ---------------------------------------------------------------------------
# 3. meta.json 与 pyproject.toml 一致性
# ---------------------------------------------------------------------------
meta: dict = {}
try:
    meta = json.loads((SKILL_ROOT / "meta.json").read_text(encoding="utf-8"))
except Exception as exc:  # noqa: BLE001
    errors.append(f"meta.json 解析失败：{exc}")

for field in ("name", "display_name", "version", "description", "license", "author"):
    check(bool(meta.get(field)), f"meta.json 的 {field} 缺失或为空")

for field in ("name", "version", "license"):
    if field in meta and field in project:
        check(meta[field] == project[field],
              f"meta.json 的 {field}={meta[field]!r} 与 pyproject.toml 的 {project[field]!r} 不一致")

check(bool(meta.get("tags")), "meta.json 的 tags 不应为空")

# ---------------------------------------------------------------------------
# 4. SKILL.md frontmatter
# ---------------------------------------------------------------------------
skill_md = SKILL_ROOT / "SKILL.md"
frontmatter = ""
if not skill_md.is_file():
    errors.append("缺少 skills/local-kb-rag/SKILL.md")
else:
    text = skill_md.read_text(encoding="utf-8")
    check(text.startswith("---\n"), "SKILL.md 必须以 YAML frontmatter（---）开头")
    parts = text.split("\n---", 1)
    frontmatter = parts[0] if parts else ""
    check("name:" in frontmatter, "SKILL.md frontmatter 缺少 name")
    check("description:" in frontmatter, "SKILL.md frontmatter 缺少 description")
    check("license:" in frontmatter, "SKILL.md frontmatter 缺少 license")

    name_match = re.search(r"^name:\s*(\S+)\s*$", frontmatter, re.MULTILINE)
    if name_match:
        skill_name = name_match.group(1)
        check(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", skill_name) is not None,
              f"SKILL.md 的 name={skill_name!r} 必须为 kebab-case（小写字母/数字/连字符）")
        check(skill_name == project.get("name"),
              f"SKILL.md 的 name={skill_name!r} 与 pyproject.toml 的 {project.get('name')!r} 不一致")
    else:
        errors.append("SKILL.md frontmatter 的 name 无法解析")

    license_match = re.search(r"^license:\s*(\S+)\s*$", frontmatter, re.MULTILINE)
    if license_match and project.get("license"):
        check(license_match.group(1) == project["license"],
              "SKILL.md 的 license 与 pyproject.toml 不一致")

# ---------------------------------------------------------------------------
# 5. Skill 包自包含与固定入口
# ---------------------------------------------------------------------------
check(not (SKILL_ROOT / "README.md").exists(),
      "skills/local-kb-rag/ 内不得存放 README.md（skill-creator 规范；项目说明在仓库根）")

REQUIRED_SKILL_FILES = (
    "info.json",
    "requirements.txt",
    "assets/sample-note.md",
    "scripts/run.ps1",
    "scripts/install-env.ps1",
    "scripts/cli.py",
    "scripts/pipe_client.py",
    "scripts/mcp_adapter.py",
    "scripts/server.py",
    "scripts/rag_pipeline.py",
    "scripts/model_download.py",
    "scripts/common.py",
    "tests/test_split_smoke.py",
    "tests/test-e2e.ps1",
)
for rel in REQUIRED_SKILL_FILES:
    check((SKILL_ROOT / rel).is_file(), f"Skill 包缺少文件：skills/local-kb-rag/{rel}")

# 脚本重命名后的旧名不得回归（会导致文档与代码不一致）
for stale in ("scripts/client.py", "scripts/rag_client.py", "tests/test.ps1"):
    check(not (SKILL_ROOT / stale).exists(),
          f"检测到已废弃文件名 skills/local-kb-rag/{stale}，请使用现行命名")

try:
    info = json.loads((SKILL_ROOT / "info.json").read_text(encoding="utf-8"))
    check(bool(info.get("name")) and bool(info.get("models")) and bool(info.get("rag")),
          "info.json 缺少 name / models / rag 关键配置")
    check(info.get("name") == project.get("name"),
          "info.json 的 name 与 pyproject.toml 不一致")
except Exception as exc:  # noqa: BLE001
    errors.append(f"info.json 解析失败：{exc}")

# ---------------------------------------------------------------------------
# 6. README 章节完整性
# ---------------------------------------------------------------------------
readme_file = REPO_ROOT / "README.md"
if readme_file.is_file():
    readme = readme_file.read_text(encoding="utf-8")
    REQUIRED_SECTIONS = {
        "项目简介": ("项目简介", "简介"),
        "功能特性": ("功能特性",),
        "目录结构": ("目录结构",),
        "安装步骤": ("安装",),
        "使用说明": ("使用",),
        "贡献指南": ("贡献",),
        "许可证信息": ("许可证", "License", "LICENSE"),
    }
    for label, aliases in REQUIRED_SECTIONS.items():
        if not any(alias in readme for alias in aliases):
            errors.append(f"README.md 缺少「{label}」相关章节")

# ---------------------------------------------------------------------------
# 7. LICENSE 内容
# ---------------------------------------------------------------------------
license_file = REPO_ROOT / "LICENSE"
if license_file.is_file():
    license_text = license_file.read_text(encoding="utf-8", errors="replace")
    check("Apache License" in license_text, "LICENSE 不是 Apache License 全文")
    check("Version 2.0" in license_text, "LICENSE 缺少 Version 2.0")
    check("Copyright" in license_text, "LICENSE 缺少 Copyright 声明")

# ---------------------------------------------------------------------------
# 8. 无缓存 / 构建残留
#
# 只检查「被 git 跟踪」的文件：__pycache__ / .pytest_cache 已被 .gitignore 忽略，
# 且本地每次跑测试都会重新生成，因此真正的风险是有人用 `git add -f` 把它们提交进来。
# ---------------------------------------------------------------------------
try:
    tracked_raw = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, check=True,
    ).stdout
    tracked_files = [p for p in tracked_raw.split("\0") if p]
except Exception as exc:  # noqa: BLE001
    warnings.append(f"跳过 git 跟踪文件检查（{type(exc).__name__}: {exc}）")
    tracked_files = []

CACHE_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
for rel in tracked_files:
    parts = Path(rel).parts
    if any(part in CACHE_DIRS for part in parts):
        errors.append(f"缓存目录被纳入版本控制：{rel}")
    elif Path(rel).suffix in (".pyc", ".pyo"):
        errors.append(f"字节码文件被纳入版本控制：{rel}")

# Skill 包内不应出现仓库级资产（保持包自包含且可整体拷贝）
SKILL_ALLOWED = {"SKILL.md", "meta.json", "info.json", "requirements.txt",
                 "assets", "scripts", "tests"}
for entry in sorted(SKILL_ROOT.iterdir()):
    if entry.name not in SKILL_ALLOWED:
        warnings.append(f"skills/local-kb-rag/ 出现未列入约定的条目：{entry.name}")

# ---------------------------------------------------------------------------
# 9. PowerShell 脚本编码
#
# Windows PowerShell 5.1 在文件无 BOM 时按当前 ANSI 代码页解码脚本。
# 脚本内含非 ASCII（中文）字符串字面量时会被错误解码，导致「字符串缺少终止符」
# 一类的解析错误 —— 实测 tests/test-e2e.ps1 曾因此完全无法运行。
# 规则：含非 ASCII 字符的 .ps1 必须带 UTF-8 BOM。
# ---------------------------------------------------------------------------
UTF8_BOM = b"\xef\xbb\xbf"
for ps1 in sorted(SKILL_ROOT.rglob("*.ps1")):
    raw = ps1.read_bytes()
    if raw.startswith(UTF8_BOM):
        continue
    try:
        raw.decode("ascii")
    except UnicodeDecodeError:
        errors.append(
            f"{ps1.relative_to(REPO_ROOT)} 含非 ASCII 字符但缺少 UTF-8 BOM，"
            "Windows PowerShell 5.1 下会解析失败"
        )

# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
for item in warnings:
    print(f"WARN  {item}")
for item in errors:
    print(f"ERROR {item}")

print(f"\nmetadata check: {len(errors)} error(s), {len(warnings)} warning(s)")
if errors:
    sys.exit(1)
print("METADATA-OK")
