# -*- coding: utf-8 -*-
"""标准 CLI 客户端（短命进程）：命令行参数 → named pipe → server → JSON 输出。

run.ps1 的固定下游入口。所有结果以 UTF-8 JSON 打到 stdout。

用法示例：
    python cli.py status
    python cli.py ingest --source "C:/notes/spec.pdf"
    python cli.py ingest --content "会议纪要..." --doc-id meeting-0726
    python cli.py search --query "OpenVINO 如何部署到 NPU" --top-k 5
    python cli.py ask --query "本方案如何保证隐私不出机？"
    python cli.py list-sources
    python cli.py remove-source --doc-id a1b2c3
    python cli.py shutdown
"""
from __future__ import annotations

import argparse
import json
import sys

import common
from common import (EXIT_BAD_REQUEST, EXIT_NOT_AIPC, EXIT_OK,
                    EXIT_SERVER_UNAVAILABLE)


def _emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local-kb-rag", description="本地私有知识库 RAG 客户端")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="查询 server/索引状态")
    sub.add_parser("list-sources", help="列出已纳管文档")
    sub.add_parser("shutdown", help="关停常驻 server")

    p = sub.add_parser("ingest", help="摄入文档（PDF/Markdown/TXT 或原始文本）")
    p.add_argument("--source", default="", help="本地文件路径")
    p.add_argument("--content", default="", help="原始文本（与 --source 二选一）")
    p.add_argument("--doc-id", default="", help="自定义 doc_id，缺省按路径哈希")
    p.add_argument("--chunk-size", type=int, default=0)
    p.add_argument("--overlap", type=int, default=0)

    p = sub.add_parser("search", help="语义检索（不生成）")
    p.add_argument("--query", required=True)
    p.add_argument("--top-k", type=int, default=0)
    p.add_argument("--no-rerank", action="store_true", help="跳过精排")
    p.add_argument("--doc-id", default="", help="限定检索某文档")

    p = sub.add_parser("ask", help="带引用问答")
    p.add_argument("--query", required=True)
    p.add_argument("--top-k", type=int, default=0)
    p.add_argument("--max-tokens", type=int, default=0)

    p = sub.add_parser("remove-source", help="移除文档及其向量")
    p.add_argument("--doc-id", required=True)
    return parser


def to_message(args: argparse.Namespace) -> dict:
    cmd = args.command
    if cmd == "status":
        return {"op": "status"}
    if cmd == "shutdown":
        return {"op": "shutdown", "timeout": 10.0}
    if cmd == "ingest":
        return {"op": "request", "action": "ingest", "source": args.source,
                "content": args.content, "doc_id": args.doc_id,
                "chunk_size": args.chunk_size, "overlap": args.overlap}
    if cmd == "search":
        return {"op": "request", "action": "search", "query": args.query,
                "top_k": args.top_k, "rerank": not args.no_rerank,
                "filter": {"doc_id": args.doc_id} if args.doc_id else None}
    if cmd == "ask":
        return {"op": "request", "action": "ask", "query": args.query,
                "top_k": args.top_k, "max_tokens": args.max_tokens}
    if cmd == "list-sources":
        return {"op": "request", "action": "list_sources"}
    if cmd == "remove-source":
        return {"op": "request", "action": "remove_source", "doc_id": args.doc_id}
    raise ValueError(f"unknown command: {cmd}")


def main() -> int:
    common.force_utf8_stdio()
    args = build_parser().parse_args()

    # 硬件预检：OpenVINO 无任何可用 device → 非 AIPC（退出码 2）
    if args.command in ("ingest", "search", "ask"):
        devices = common.detect_devices()
        if not devices:
            _emit({"ok": False, "error": "no OpenVINO device available (not an AIPC?)"})
            return EXIT_NOT_AIPC

    import pipe_client
    try:
        if args.command == "shutdown":
            ok = pipe_client.shutdown_server()
            _emit({"ok": ok, "state": "shutdown" if ok else "still_alive"})
            return EXIT_OK if ok else EXIT_SERVER_UNAVAILABLE
        reply = pipe_client.call(to_message(args))
        _emit(reply)
        return EXIT_OK
    except pipe_client.BadRequest as exc:
        _emit({"ok": False, "error": str(exc)})
        return EXIT_BAD_REQUEST
    except pipe_client.ServerUnavailable as exc:
        _emit({"ok": False, "error": str(exc)})
        return EXIT_SERVER_UNAVAILABLE


if __name__ == "__main__":
    sys.exit(main())
