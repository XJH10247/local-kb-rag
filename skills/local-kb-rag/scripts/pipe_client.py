# -*- coding: utf-8 -*-
"""共享 named-pipe 客户端模块：连接 / 拉起 server / 升级重启 / 健康检查 / 重试。

被 cli.py（标准 CLI）与 mcp_adapter.py（MCP）共用 —— 二者经同一条
pipe 调同一个常驻 server（混合架构）。

生命周期自管理：
1. pipe 可连通（server 存活）？否 → subprocess.Popen 后台拉起 server
2. 是 → 比对脚本 hash，变更则 shutdown 旧 server 并重启
3. 轮询 status 至 running（downloading/loading 阶段耐心等待）或超时
4. 发送 request（一请求一连接）
"""
from __future__ import annotations

import subprocess
import sys
import time
from multiprocessing.connection import Client

import common
from common import AUTH_KEY, PIPE_ADDRESS, SCRIPTS_DIR

log = common.setup_logging("pipe_client")

CONNECT_RETRY_S = 0.5
STARTUP_TIMEOUT_S = 90        # 冷启动预算（模型已下载 < 60s，留余量）
DOWNLOAD_TIMEOUT_S = 3600     # 首跑模型下载预算


class ServerUnavailable(RuntimeError):
    """server 不可用（退出码 5 语义）。"""


class BadRequest(ValueError):
    """请求参数错误（退出码 6 语义）。"""


def _send_raw(msg: dict, timeout_s: float = 120.0) -> dict:
    """单次 pipe 往返：send → recv → close，不复用连接。"""
    deadline = time.time() + timeout_s
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with Client(PIPE_ADDRESS, authkey=AUTH_KEY) as conn:
                conn.send(msg)
                return conn.recv()
        except (FileNotFoundError, ConnectionRefusedError, EOFError, OSError) as exc:
            last_err = exc
            time.sleep(CONNECT_RETRY_S)
    raise ServerUnavailable(f"pipe not reachable within {timeout_s}s: {last_err}")


def _spawn_server() -> None:
    """后台拉起 server（分离进程，不阻塞、不继承句柄）。

    stdout/stderr 落盘而非 DEVNULL：server 原生层崩溃时不会有任何日志，
    丢弃 stderr 会吞掉唯一的崩溃线索，落盘便于事后取证。
    """
    common.ensure_dirs()
    try:
        crash_log = open(common.LOGS_DIR / "server.stderr.log", "ab")
    except OSError:
        crash_log = subprocess.DEVNULL
    kwargs: dict = {
        "stdout": crash_log,
        "stderr": crash_log,
        "stdin": subprocess.DEVNULL,
        "cwd": str(SCRIPTS_DIR),
    }
    if sys.platform == "win32":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, str(SCRIPTS_DIR / "server.py")], **kwargs)
    log.info("server spawned")


def _server_alive() -> bool:
    """pipe 能连通才算存活（与 server 侧 _pipe_alive 同一判据）。

    不能用 pidfile + pid_alive：server 硬崩后 pidfile 残留、Windows PID
    被复用时会误判存活 → 不拉起新 server → 轮询 pipe 超时。
    """
    try:
        with Client(PIPE_ADDRESS, authkey=AUTH_KEY) as conn:
            conn.send({"op": "status"})
            conn.recv()
        return True
    except Exception:
        return False


def shutdown_server(timeout_s: float = 10.0) -> bool:
    """优雅关停 server；不存活视为成功。"""
    if not _server_alive():
        return True
    try:
        _send_raw({"op": "shutdown", "timeout": timeout_s}, timeout_s=5.0)
    except ServerUnavailable:
        pass
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _server_alive():
            return True
        time.sleep(0.3)
    return not _server_alive()


def ensure_server(wait_running: bool = True) -> dict:
    """确保 server 存活且脚本为最新版本；返回最后一次 status 应答。"""
    if _server_alive():
        # 脚本升级检测：hash 变化 → 重启
        recorded = ""
        try:
            recorded = common.HASHFILE.read_text(encoding="utf-8").strip()
        except Exception:
            pass
        if recorded and recorded != common.scripts_hash():
            log.info("script hash changed, restarting server")
            shutdown_server()
            _spawn_server()
    else:
        _spawn_server()

    if not wait_running:
        return _send_raw({"op": "status"}, timeout_s=STARTUP_TIMEOUT_S)

    # 轮询至 running / error / 超时；downloading 阶段用更长预算
    deadline = time.time() + STARTUP_TIMEOUT_S
    download_deadline = time.time() + DOWNLOAD_TIMEOUT_S
    while True:
        status = _send_raw({"op": "status"}, timeout_s=STARTUP_TIMEOUT_S)
        state = status.get("state")
        if state == "running":
            return status
        if state == "error":
            raise ServerUnavailable(f"server error: {status.get('error', '')[-2000:]}")
        effective_deadline = download_deadline if state == "downloading" else deadline
        if time.time() > effective_deadline:
            raise ServerUnavailable(f"server not running within budget (state={state})")
        time.sleep(1.0)


def call(msg: dict, timeout_s: float = 300.0) -> dict:
    """高层调用：确保 server 就绪后发送消息；业务错误按语义抛异常。"""
    if msg.get("op") == "status":
        # status 不强制等 running，直接反映当前状态；server 不在则先拉起
        if not _server_alive():
            _spawn_server()
        return _send_raw(msg, timeout_s=STARTUP_TIMEOUT_S)

    ensure_server(wait_running=True)
    reply = _send_raw(msg, timeout_s=timeout_s)
    if not reply.get("ok"):
        if reply.get("bad_request"):
            raise BadRequest(reply.get("error", "bad request"))
        raise ServerUnavailable(reply.get("error", "server error"))
    return reply
