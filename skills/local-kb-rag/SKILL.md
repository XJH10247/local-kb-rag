---
name: local-kb-rag
description: |
  本地私有知识库 RAG Skill：把 PDF/Markdown/TXT 摄入本地向量库，提供带引用的语义检索与问答，
  全链路 OpenVINO 本地推理（NPU 跑 Embedding/Rerank，iGPU 跑 LLM，CPU 兜底），语料不出机。
  Use when the user asks to "检索我的笔记/文档"、"问一下知识库"、"PDF 问答"、"本地 RAG"、
  "私有第二大脑"、"研报摘要"、"知识库里有什么"、"ingest/search/ask my knowledge base"、
  "local private RAG over PDF/Markdown"、"query my notes"、"offline knowledge assistant"。
  经 MCP 工具 kb_ingest / kb_search / kb_ask / kb_list_sources / kb_status 调用。
  触发词：知识库 / 笔记 / RAG / 问答 / 检索 / 摄入 / PDF / Markdown / 私有 / 离线 /
  第二大脑 / 引用 / knowledge base / KB / local RAG / retrieval / citation / ingest。
license: Apache-2.0
---

# 本地私有知识库 RAG（local-kb-rag）

把个人 PDF/Markdown 笔记沉淀为「永不掉线、完全私有」的数字第二大脑。
全链路 OpenVINO 本地推理：BGE-M3 Embedding 与 BGE-reranker 精排跑在 **NPU**，
Qwen2.5-7B-Instruct INT4 生成跑在 **iGPU**，无加速硬件时自动回退 CPU。
语料、向量、模型全部驻留本机，仅答案文本回传 Agent。

> 本 Skill 目录自包含，可单独拷贝使用，不依赖仓库根文件。
> 完整的使用注意事项（环境要求、首次运行、地址占位、修改源码的硬约束）见项目仓库根目录的 **NOTICE.md**；
> 架构说明与故障排查见 `docs/architecture.md` 与 `README.md`。

## 何时使用本 Skill

| 用户意图 | 应调用的工具 |
|---|---|
| 「把这个 PDF/笔记加入知识库」「记住这份文档」 | `kb_ingest` |
| 「在我的笔记里找…」「知识库里关于 X 的片段」（只要原文，不要生成） | `kb_search` |
| 「根据我的文档回答…」「知识库问答」（需要归纳的答案 + 引用） | `kb_ask` |
| 「知识库里都有什么文档」 | `kb_list_sources` |
| 「RAG 服务状态怎么样」「模型跑在什么设备上」 | `kb_status` |

## 工具使用指引（供 Agent 大脑决策）

1. **先摄入后问答**：若用户给出文件路径，先 `kb_ingest(path=...)`；`kb_ingest` 幂等，
   同一 doc_id 重复摄入会覆盖更新。
2. **search vs ask**：用户要「原文片段/出处定位」用 `kb_search`（<2s）；
   要「归纳性答案」用 `kb_ask`（检索+精排+本地 LLM，约 5–15s）。
3. **引用可信**：`kb_ask` 返回的 `citations[]` 是真实检索片段回填，
   答案中 [1][2] 编号与之对应，可直接展示给用户核对出处。
4. **首次调用**：会自动拉起常驻推理 server；首跑需下载模型（数 GB，支持断点续传），
   请先调用 `kb_status` 告知用户 `state`（downloading/loading/running）。
5. **空文件/不支持格式**：`kb_ingest` 支持 `.pdf` `.md` `.markdown` `.txt`；
   其他格式请先转换或用 `content` 参数直接传入文本。

## 接入方式

### 方式 A：MCP（推荐）

在宿主的 MCP 配置（`mcp.json`）中注册：

```json
{
  "mcpServers": {
    "local-kb-rag": {
      "command": "%USERPROFILE%\\.openvino\\venvs\\local-kb-rag\\Scripts\\python.exe",
      "args": ["<skill_root>\\scripts\\mcp_adapter.py"]
    }
  }
}
```

`args` 必须是 `mcp_adapter.py` 的**绝对路径**。首次注册前先执行 `scripts\install-env.ps1` 完成环境安装。

### 方式 B：标准 CLI（`run.ps1` 入口）

```powershell
.\scripts\run.ps1 status
.\scripts\run.ps1 ingest --source "C:\notes\spec.pdf"
.\scripts\run.ps1 search --query "OpenVINO 如何部署到 NPU"
.\scripts\run.ps1 ask --query "本方案如何保证隐私不出机？"
.\scripts\run.ps1 list-sources
.\scripts\run.ps1 shutdown
```

两种方式经同一条 named pipe（`\\.\pipe\local-kb-rag`）调同一个常驻 server，
模型只加载一次；空闲 300s 自动关停释放显存。

## 运行要求

- Windows AIPC（Intel Core Ultra 推荐，NPU/iGPU 自动探测，无则 CPU 兜底）
- 内存 ≥ 8GB；磁盘 ≥ 10GB（模型缓存）
- Python 3.10–3.12（依赖预编译轮子上限；更高版本易触发源码编译失败）；首跑需联网下载模型（ModelScope），此后完全离线
