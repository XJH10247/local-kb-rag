# -*- coding: utf-8 -*-
"""local-kb-rag 共享基础模块。

职责：
- 统一路径约定（skill 根目录 / 数据目录 / 模型缓存 / 日志目录 / pidfile）
- 退出码常量
- UTF-8 stdout/stderr 强制编码
- 日志初始化（写 %USERPROFILE%/.openvino/logs/local-kb-rag/server.log）
- info.json 配置加载
- 脚本 hash 计算（脚本升级 → server 重启）
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 退出码
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_NOT_AIPC = 2        # 非 AIPC / 硬件不满足
EXIT_ENV_ERROR = 3       # 环境/依赖错误
EXIT_DOWNLOAD_FAILED = 4 # 模型下载失败
EXIT_SERVER_UNAVAILABLE = 5  # server 不可用
EXIT_BAD_REQUEST = 6     # 请求参数错误

# ---------------------------------------------------------------------------
# 路径约定
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPTS_DIR.parent

HOME = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or "~").expanduser()
OPENVINO_HOME = HOME / ".openvino"

SKILL_NAME = "local-kb-rag"
DATA_DIR = OPENVINO_HOME / "data" / SKILL_NAME          # ChromaDB 向量库 + 语料清单
MODELS_DIR = OPENVINO_HOME / "models" / SKILL_NAME      # OpenVINO IR 模型缓存
LOGS_DIR = OPENVINO_HOME / "logs" / SKILL_NAME          # 日志
RUNTIME_DIR = OPENVINO_HOME / "runtime" / SKILL_NAME    # pidfile / hashfile

PIDFILE = RUNTIME_DIR / "server.pid"
HASHFILE = RUNTIME_DIR / "server.hash"
LOG_FILE = LOGS_DIR / "server.log"

# named-pipe 协议常量
PIPE_ADDRESS = r"\\.\pipe\local-kb-rag"
AUTH_KEY = b"local-kb-rag"

# server 状态机内核依赖的脚本：任何一个 hash 变化都触发重启
CORE_SCRIPTS = ("server.py", "rag_pipeline.py", "model_download.py", "common.py")


def ensure_dirs() -> None:
    """幂等创建所有运行时目录。"""
    for d in (DATA_DIR, MODELS_DIR, LOGS_DIR, RUNTIME_DIR):
        d.mkdir(parents=True, exist_ok=True)


def sanitize_pythonpath() -> None:
    r"""剥离外部 PYTHONPATH 注入的 sys.path 条目，防止全局包目录遮蔽 venv 里的包。

    机器级 PIP_TARGET/PYTHONPATH 若指向共享包目录（如 D:\python-package），
    其中旧版/异构包会优先于 venv 被 import 导致运行时崩溃。
    同时从 os.environ 移除 PYTHONPATH，确保拉起的子进程（server）也不受污染。
    """
    extra = os.environ.pop("PYTHONPATH", None)
    if not extra:
        return
    bad = {os.path.normcase(os.path.abspath(p)) for p in extra.split(os.pathsep) if p}
    sys.path[:] = [p for p in sys.path if os.path.normcase(os.path.abspath(p or ".")) not in bad]


# 模块加载即生效：所有入口（server/client/mcp_adapter）均先 import common，
# 保证在 openvino/chromadb 等重依赖 import 之前完成路径净化
_ = sanitize_pythonpath()


def force_utf8_stdio() -> None:
    """Windows 控制台默认 GBK，强制 stdout/stderr 为 UTF-8。"""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
        elif hasattr(stream, "buffer"):
            setattr(sys, name, io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"))


def setup_logging(name: str = "local-kb-rag", to_file: bool = True) -> logging.Logger:
    """初始化 UTF-8 日志：文件 + stderr 双写。"""
    ensure_dirs()
    logger = logging.getLogger(name)
    if logger.handlers:  # 幂等
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    if to_file:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


def load_info() -> dict:
    """加载 skill 运行时配置 info.json。"""
    with open(SKILL_ROOT / "info.json", "r", encoding="utf-8") as f:
        return json.load(f)


def scripts_hash() -> str:
    """核心脚本联合 hash，用于「脚本升级 → server 重启」检测。"""
    h = hashlib.sha256()
    for fname in CORE_SCRIPTS:
        fpath = SCRIPTS_DIR / fname
        if fpath.exists():
            h.update(fpath.read_bytes())
    return h.hexdigest()


def read_pidfile() -> int | None:
    """读取 pidfile；不存在/损坏返回 None。"""
    try:
        return int(PIDFILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def write_pidfile(pid: int) -> None:
    ensure_dirs()
    PIDFILE.write_text(str(pid), encoding="utf-8")


def pid_alive(pid: int) -> bool:
    """判断进程是否存活（跨平台）。"""
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        if os.name == "nt":
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def detect_devices() -> list[str]:
    """探测可用 OpenVINO device 列表；OpenVINO 不可用返回空表。"""
    try:
        import openvino as ov
        return list(ov.Core().available_devices)
    except Exception:
        return []


def pick_device(preference: list[str], available: list[str]) -> str:
    """按偏好顺序选择 device，全部不可用兜底 CPU。"""
    for dev in preference:
        for avail in available:
            if avail == dev or avail.startswith(dev + "."):
                return avail
    return "CPU"
