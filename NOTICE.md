# NOTICE —— 克隆本仓库后请先读这一页

本页汇总**上手前必须知道的事项**。全部读一遍约 1 分钟，能省掉大部分返工。

---

## 一、环境要求（最容易踩坑的一条）

| 项目 | 要求 | 说明 |
|---|---|---|
| **Python** | **3.10 – 3.12** | 依赖钉在预编译轮子覆盖范围内。**3.13 及以上会回退到源码编译，极易失败**（需要 C 编译器）。用 `python --version` 确认，不符请装 3.12 |
| 操作系统 | Windows 10 / 11 | 依赖 Windows named pipe（`\\.\pipe\local-kb-rag`）与 PowerShell 脚本，**Linux / macOS 无法直接运行** |
| 内存 | ≥ 8 GB | 门槛写在 `skills/local-kb-rag/info.json` 的 `mem_need_gb` |
| 磁盘 | ≥ 10 GB | 模型缓存占用；运行时数据写在 `%USERPROFILE%\.openvino\`，**不在仓库内** |
| 网络 | 首次需联网 | 从 ModelScope 下载模型（数 GB，支持断点续传）；下载完成后可**完全离线**运行 |

> 无 NPU / iGPU 也能跑：OpenVINO 会自动回退 CPU，功能不变、速度下降。

## 二、克隆后必须做的两件事

### 1. 安装环境（幂等，可重复执行）

```powershell
cd skills\local-kb-rag
powershell -ExecutionPolicy Bypass -File scripts\install-env.ps1

# 国内网络建议加 -Mirror 走清华 PyPI 镜像
powershell -ExecutionPolicy Bypass -File scripts\install-env.ps1 -Mirror
```

### 2. 首次运行会下载数 GB 模型

```powershell
.\scripts\run.ps1 status
```

首次调用会自动拉起常驻服务并触发模型下载。`state` 依次经过
`downloading → loading → running`，**看到 `"state": "running"` 才算装好**。
下载耗时取决于网络，中断后重跑会续传。

最短验证路径：

```powershell
.\scripts\run.ps1 ingest --source ".\assets\sample-note.md" --doc-id sample-note
.\scripts\run.ps1 ask --query "本地 RAG 如何保证隐私不出机？"
```

## 三、仓库地址相关配置（按需处理，不处理也能用）

本仓库**不预设远端地址**（未初始化 `.git`，也未写死任何具体仓库地址）。以下位置的
地址均为**占位符**，不替换也不影响核心功能，只影响少数外围体验：

| 位置 | 留空的表现 | 想修的话 |
|---|---|---|
| `.github/ISSUE_TEMPLATE/config.yml` | Issue 选择页的 3 个联系入口指向无效地址 | 把 3 处 `<OWNER>/<REPO>` 整体替换为你的 `用户名/仓库名`；**或删掉整个 `contact_links` 段** |
| `README.md` 顶部 CI 徽章 | 徽章不显示（处于注释状态） | 取消注释并替换 `<OWNER>/<REPO>`；或启用 shields.io 动态写法（README 内有注释说明） |
| `README.md` 的 `git clone` 示例 | 只是一段示例文本 | 换成你的实际克隆地址 |
| `pyproject.toml` 的 `[project.urls]` | 无任何影响 | 通常无需处理（见下方说明） |

**共 4 处占位**。快速定位全部占位符：

```powershell
Select-String -Path .\README.md,.\NOTICE.md,.\pyproject.toml,.\.github\ISSUE_TEMPLATE\config.yml `
  -Pattern '<OWNER>/<REPO>','<REPO_URL>'
```

> **为什么 `config.yml` 不能自动跟随仓库地址？** GitHub 的 `contact_links.url`
> 只接受**绝对 URL**（`http(s)://` 开头），既不支持相对路径，也不支持
> `${{ }}` 表达式。这是该文件的硬限制，无法动态取值。
>
> **`pyproject.toml` 的 `[project.urls]` 无需处理**：默认整体注释。本项目
> 不作为 Python 包分发（没有 `pip install`），缺失该字段不影响功能。

## 四、给部署者（把本仓库放到 GitHub 的人）的额外提醒

1. **开启私有漏洞报告** —— 仓库 Settings → Security → Private vulnerability
   reporting。`SECURITY.md` 与 Issue 模板中的私下上报渠道依赖此开关，
   **未开启时相关链接会 404**。
2. **CI 无需改地址** —— `.github/workflows/ci.yml` 只用 `${{ github.* }}`
   上下文变量，换账号、改仓库名都不用动。
3. **建议开启分支保护** —— 要求 PR 通过 CI 的 `metadata` 与 `smoke` 两个作业。
4. **不要提交运行时数据** —— `%USERPROFILE%\.openvino\` 下的模型、向量库、
   日志都已在 `.gitignore` 覆盖范围内，请勿用 `git add -f` 强行加入。

## 五、修改源码时的硬约束

| 约束 | 原因 |
|---|---|
| **`skills/local-kb-rag/` 下不得放 `README.md`** | Skill 包规范；说明写在仓库根 README |
| **含中文的 `.ps1` 必须保留 UTF-8 BOM** | Windows PowerShell 5.1 在无 BOM 时按 ANSI 解码，中文字符串字面量被截断，脚本**完全无法解析**。CI 会校验 |
| **换行符交给 `.gitattributes`** | 源码/文档 LF，`.ps1` CRLF。不要手工转换 |
| **`run.ps1` / `mcp_adapter.py` 不要改名** | 宿主集成契约；`mcp.json` 中注册的是这些路径 |

## 六、隐私与安全边界

- 语料、向量库、模型权重**全部驻留本机**，仅答案文本回传 Agent 宿主
- named pipe 的 authkey 只是源码内常量，**仅防无关进程误连，不构成访问控制**
- 语料文件（尤其 PDF）视为**不可信输入**，解析属攻击面
- 详见 [`SECURITY.md`](SECURITY.md)

---

有疑问先看 [`README.md`](README.md) 的「故障排查」，或提 Issue。
