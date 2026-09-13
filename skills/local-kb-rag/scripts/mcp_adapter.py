# -*- coding: utf-8 -*-
"""薄 MCP 适配层：把 named-pipe RAG server 暴露为 5 个 MCP 工具，供宿主 Agent 调用。

工具映射：
    kb_ingest        → pipe action ingest
    kb_search        → pipe action search
    kb_ask           → pipe action ask
    kb_list_sources  → pipe action list_sources
    kb_status        → pipe op status

传输：stdio（MCP 标准接入方式）。本层不做任何推理，只做协议翻译，
与 cli.py 共用 pipe_client 经同一条 pipe 调同一个常驻 server。

宿主注册示例（mcp.json）：
    {
      "mcpServers": {
        "local-kb-rag": {
          "command": "<venv>/Scripts/python.exe",
          "args": ["<skill>/scripts/mcp_adapter.py"]
        }
      }
    }
"""
from __future__ import annotations

import json
import sys

import common

common.force_utf8_stdio()
log = common.setup_logging("mcp_adapter")

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover
    print("ERROR: mcp package not installed, run install-env.ps1 first", file=sys.stderr)
    sys.exit(common.EXIT_ENV_ERROR)

import pipe_client

mcp = FastMCP(
    "local-kb-rag",
    instructions=(
        "本地私有知识库 RAG：把 PDF/Markdown 摄入本地向量库，提供带引用的语义检索与问答。"
        "全链路 OpenVINO 本地推理（NPU/GPU/CPU），语料不出机。"
        "典型流程：kb_ingest 摄入文档 → kb_search 检索片段 / kb_ask 带引用问答。"
        "首次调用会自动拉起常驻推理服务，冷启动可能需要数十秒。"
    ),
)


def _json(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _safe_call(msg: dict, timeout_s: float = 300.0) -> str:
    """统一错误包装：MCP 工具永远返回 JSON 字符串，不抛异常给宿主。"""
    try:
        return _json(pipe_client.call(msg, timeout_s=timeout_s))
    except pipe_client.BadRequest as exc:
        return _json({"ok": False, "error": f"参数错误: {exc}"})
    except pipe_client.ServerUnavailable as exc:
        return _json({"ok": False, "error": f"RAG 服务不可用: {exc}"})
    except Exception as exc:  # noqa: BLE001
        log.exception("tool call failed")
        return _json({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


@mcp.tool()
def kb_ingest(path: str = "", content: str = "", doc_id: str = "",
              chunk_size: int = 0) -> str:
    """把本地文档（PDF/Markdown/TXT）或一段原始文本摄入本地私有知识库。

    Args:
        path: 本地文件绝对路径（与 content 二选一），如 C:/notes/spec.pdf
        content: 原始文本内容（与 path 二选一）
        doc_id: 可选自定义文档 ID；缺省按路径哈希生成；重复摄入同一 doc_id 会覆盖更新
        chunk_size: 可选切分块大小（字符数），缺省 512

    Returns:
        JSON: {ok, doc_id, doc, chunks, elapsed_s}
    """
    return _safe_call({"op": "request", "action": "ingest", "source": path,
                       "content": content, "doc_id": doc_id,
                       "chunk_size": chunk_size}, timeout_s=1800.0)


@mcp.tool()
def kb_search(query: str, top_k: int = 5, rerank: bool = True,
              doc_id: str = "") -> str:
    """在本地知识库中语义检索相关片段（只检索不生成，速度快）。

    Args:
        query: 检索问题或关键词（中英文均可）
        top_k: 返回片段数，缺省 5
        rerank: 是否用本地 Reranker 精排，缺省 true
        doc_id: 可选，限定只在某个文档内检索

    Returns:
        JSON: {ok, hits:[{doc_id, doc, chunk_id, score, text, location:{page, offset}}], elapsed_s}
    """
    return _safe_call({"op": "request", "action": "search", "query": query,
                       "top_k": top_k, "rerank": rerank,
                       "filter": {"doc_id": doc_id} if doc_id else None})


@mcp.tool()
def kb_ask(query: str, top_k: int = 5, max_tokens: int = 512) -> str:
    """基于本地知识库做带引用的问答：检索 → 精排 → 本地 LLM 生成，引用真实片段。

    Args:
        query: 用户问题（中英文均可）
        top_k: 用于生成的上下文片段数，缺省 5
        max_tokens: 生成答案最大 token 数，缺省 512

    Returns:
        JSON: {ok, answer, citations:[{index, doc_id, doc, chunk_id, page, text}], elapsed_s}
    """
    return _safe_call({"op": "request", "action": "ask", "query": query,
                       "top_k": top_k, "max_tokens": max_tokens}, timeout_s=600.0)


@mcp.tool()
def kb_list_sources() -> str:
    """列出本地知识库已纳管的全部文档及其块数、摄入时间。

    Returns:
        JSON: {ok, sources:[{doc_id, doc, chunks, ingested_at}]}
    """
    return _safe_call({"op": "request", "action": "list_sources"})


@mcp.tool()
def kb_status() -> str:
    """查询本地 RAG 服务状态：状态机阶段、文档/块数量、各模型运行的 device。

    Returns:
        JSON: {ok, state, pid, uptime_s, docs, chunks, devices}
    """
    return _safe_call({"op": "status"})


if __name__ == "__main__":
    log.info("mcp adapter starting (stdio)")
    mcp.run(transport="stdio")
