# -*- coding: utf-8 -*-
r"""local-kb-rag 常驻 server：状态机 + named-pipe Listener + 模型常驻 + 请求分发。

协议（named-pipe 契约）：
- 地址 \\.\pipe\local-kb-rag，authkey b"local-kb-rag"
- multiprocessing.connection Listener/Client，一请求一连接（send → recv → close）
- op: status / request / shutdown；request 以 action 字段分发 RAG 动作

状态机：
starting → downloading → loading → running；任意阶段异常 → error；shutdown 后退出。
模型加载在后台线程执行，主循环任意状态都能应答 status（含下载进度/错误 traceback）。

生命周期：
- 启动即写 pidfile + 脚本 hash（供 client 检测升级重启）
- 空闲超过 info.json server_alive_timeout 秒自动 shutdown 释放显存（-1=永不）
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from multiprocessing.connection import Client, Listener

import common
from common import AUTH_KEY, PIPE_ADDRESS

log = common.setup_logging("server")


class RagServer:
    def __init__(self):
        self.info = common.load_info()
        self.state = "starting"
        self.error_msg = ""
        self.progress = ""            # downloading 阶段的进度描述
        self.started_at = time.time()
        self.last_request_at = time.time()
        self.stop_event = threading.Event()
        self.pipeline = None          # RagPipeline，loading 完成后可用
        self.req_lock = threading.Lock()  # RAG 动作串行执行（模型非线程安全）

    # -- 初始化（后台线程） --------------------------------------------------
    def initialize(self) -> None:
        try:
            import model_download

            missing = model_download.check_all_models()
            if missing:
                self._transition("downloading")
                model_download.ensure_all_models(progress_cb=self._on_download_progress)

            self._transition("loading")
            from rag_pipeline import RagPipeline
            self.pipeline = RagPipeline()
            self._transition("running")
        except Exception:  # noqa: BLE001
            self.error_msg = traceback.format_exc()
            self._transition("error")
            log.error("initialize failed:\n%s", self.error_msg)

    def _on_download_progress(self, name: str, stage: str) -> None:
        self.progress = f"{name}: {stage}"
        log.info("download progress: %s", self.progress)

    def _transition(self, new_state: str) -> None:
        log.info("state: %s -> %s", self.state, new_state)
        self.state = new_state

    # -- 请求分发 -------------------------------------------------------------
    def handle(self, msg: dict) -> dict:
        op = msg.get("op")
        if op == "status":
            reply = {
                "ok": self.state != "error",
                "state": self.state,
                "pid": os.getpid(),
                "uptime_s": round(time.time() - self.started_at, 1),
                "script_hash": common.scripts_hash(),
            }
            if self.state == "downloading":
                reply["progress"] = self.progress
            if self.state == "error":
                reply["error"] = self.error_msg
            if self.state == "running" and self.pipeline is not None:
                reply.update(self.pipeline.stats())
            return reply

        if op == "shutdown":
            self.stop_event.set()
            return {"ok": True, "state": "shutting_down"}

        if op == "request":
            self.last_request_at = time.time()
            if self.state != "running":
                return {"ok": False, "error": f"server not ready (state={self.state})",
                        "state": self.state}
            return self._dispatch_action(msg)

        return {"ok": False, "error": f"unknown op: {op!r}"}

    def _dispatch_action(self, msg: dict) -> dict:
        action = msg.get("action")
        try:
            with self.req_lock:
                if action == "ingest":
                    result = self.pipeline.ingest(
                        source=msg.get("source", ""), content=msg.get("content", ""),
                        doc_id=msg.get("doc_id", ""),
                        chunk_size=msg.get("chunk_size", 0), overlap=msg.get("overlap", 0))
                elif action == "search":
                    result = self.pipeline.search(
                        query=msg.get("query", ""), top_k=msg.get("top_k", 0),
                        rerank=msg.get("rerank", True), filter=msg.get("filter"))
                elif action == "ask":
                    result = self.pipeline.ask(
                        query=msg.get("query", ""), top_k=msg.get("top_k", 0),
                        max_tokens=msg.get("max_tokens", 0))
                elif action == "list_sources":
                    result = self.pipeline.list_sources()
                elif action == "remove_source":
                    result = self.pipeline.remove_source(msg.get("doc_id", ""))
                else:
                    return {"ok": False, "error": f"unknown action: {action!r}",
                            "bad_request": True}
            result["ok"] = True
            return result
        except ValueError as exc:  # 参数错误（退出码 6 语义）
            return {"ok": False, "error": str(exc), "bad_request": True}
        except Exception as exc:  # noqa: BLE001
            log.exception("action %s failed", action)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # -- 空闲超时看门狗 --------------------------------------------------------
    def watchdog(self) -> None:
        timeout = self.info.get("server_alive_timeout", 300)
        if timeout is None or timeout < 0:
            return  # -1 = 永不关停
        while not self.stop_event.wait(5.0):
            if self.state == "running" and time.time() - self.last_request_at > timeout:
                log.info("idle > %ss, auto shutdown", timeout)
                self.stop_event.set()
                # 自连一次 pipe 以解除 accept 阻塞
                try:
                    with Client(PIPE_ADDRESS, authkey=AUTH_KEY) as conn:
                        conn.send({"op": "status"})
                        conn.recv()
                except Exception:
                    pass
                return

    # -- 主循环 ---------------------------------------------------------------
    def serve_forever(self) -> None:
        common.ensure_dirs()
        common.write_pidfile(os.getpid())
        common.HASHFILE.write_text(common.scripts_hash(), encoding="utf-8")

        listener = Listener(PIPE_ADDRESS, authkey=AUTH_KEY)
        log.info("listening on %s (pid=%d)", PIPE_ADDRESS, os.getpid())

        threading.Thread(target=self.initialize, daemon=True, name="init").start()
        threading.Thread(target=self.watchdog, daemon=True, name="watchdog").start()

        try:
            while not self.stop_event.is_set():
                try:
                    conn = listener.accept()
                except Exception as exc:  # noqa: BLE001
                    if self.stop_event.is_set():
                        break
                    log.warning("accept failed: %s", exc)
                    continue
                # 一请求一连接：recv → handle → send → close
                try:
                    msg = conn.recv()
                    reply = self.handle(msg if isinstance(msg, dict) else {})
                    conn.send(reply)
                except EOFError:
                    pass
                except Exception as exc:  # noqa: BLE001
                    log.warning("connection error: %s", exc)
                    try:
                        conn.send({"ok": False, "error": str(exc)})
                    except Exception:
                        pass
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
        finally:
            listener.close()
            try:
                common.PIDFILE.unlink(missing_ok=True)
            except Exception:
                pass
            log.info("server exited (pid=%d)", os.getpid())


def _pipe_alive() -> bool:
    """探测是否已有存活 server 在监听 pipe（单实例判活的唯一可靠依据）。

    不能只查 pidfile + pid_alive：server 硬崩后 pidfile 残留，Windows PID
    被其他进程复用时会误判「已有实例」导致新 server 拒启，skill 整体不可用。
    """
    try:
        with Client(PIPE_ADDRESS, authkey=AUTH_KEY) as conn:
            conn.send({"op": "status"})
            conn.recv()
        return True
    except Exception:
        return False


def main() -> int:
    common.force_utf8_stdio()
    # 单实例保护：pipe 能连通才算已有存活 server；反之视为残留 pidfile，照常启动
    if _pipe_alive():
        log.info("another server listening on pipe, exit")
        return common.EXIT_OK
    RagServer().serve_forever()
    return common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
