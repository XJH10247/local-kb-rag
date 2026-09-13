# -*- coding: utf-8 -*-
"""模型下载 + 断点续传 + OpenVINO IR 导出 + required_files 校验。

策略：
- ModelScope 下载原始模型/预转换 OV 模型（国内网络友好，SDK 自带断点续传）
- 下载到 <MODELS_DIR>/<name>.partial 临时目录，完成校验后原子 rename 为正式目录，
  避免半成品目录被误判为可用（.partial 原子写）
- 对需要转换的模型（export=true）调用 optimum-cli export openvino 转 IR
- required_files 逐一校验，缺失即视为不完整 → 下次继续续传
- CLI 支持 --continue：供上层在超时后重入续传（--continue 协议）

用法：
    python model_download.py            # 下载全部缺失模型
    python model_download.py --check    # 只校验，缺失打印并退出码 4
    python model_download.py --continue # 续传（语义同默认，显式表达重入）
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

import common
from common import EXIT_DOWNLOAD_FAILED, EXIT_OK, MODELS_DIR

log = common.setup_logging("model_download")


def model_dir(name: str) -> Path:
    return MODELS_DIR / name


def _partial_dir(name: str) -> Path:
    return MODELS_DIR / (name + ".partial")


def is_model_ready(mconf: dict) -> bool:
    """required_files 全部存在且非空 → 模型就绪。"""
    mdir = model_dir(mconf["name"])
    if not mdir.is_dir():
        return False
    for rel in mconf.get("required_files", []):
        matches = list(mdir.rglob(rel))
        if not matches or all(p.stat().st_size == 0 for p in matches):
            return False
    return True


def _download_modelscope(repo: str, target: Path) -> Path:
    """ModelScope snapshot 下载（SDK 内置分片校验与续传），返回快照实际目录。"""
    from modelscope import snapshot_download
    log.info("downloading from modelscope: %s -> %s", repo, target)
    path = snapshot_download(repo, local_dir=str(target))
    return Path(path)


def _export_openvino(src: Path, dst: Path, task: str) -> None:
    """optimum-cli 一键导出 OpenVINO IR（FP16 权重）。

    注意：必须用 venv Scripts 下的 optimum-cli 可执行文件；
    `python -m optimum.exporters.openvino` 不是 CLI 入口（只定义 API，
    参数被忽略且退出码 0，会出现导出"成功"但无产物的情况）。
    """
    log.info("exporting to OpenVINO IR: %s (task=%s)", src, task)
    exe_name = "optimum-cli.exe" if sys.platform == "win32" else "optimum-cli"
    optimum_cli = Path(sys.executable).with_name(exe_name)
    if not optimum_cli.exists():
        raise RuntimeError(f"optimum-cli not found: {optimum_cli} (run install-env.ps1 first)")
    cmd = [
        str(optimum_cli), "export", "openvino",
        "--model", str(src),
        "--task", task,
        "--weight-format", "fp16",
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"optimum export failed: {result.stderr[-2000:]}")
    log.info("export finished: %s", dst)


def download_one(mconf: dict, progress_cb=None) -> None:
    """下载（含续传）并就位单个模型。progress_cb(name, stage) 用于状态回传。"""
    name = mconf["name"]
    if is_model_ready(mconf):
        log.info("model ready, skip: %s", name)
        return

    partial = _partial_dir(name)
    final = model_dir(name)
    common.ensure_dirs()
    t0 = time.time()
    if progress_cb:
        progress_cb(name, "downloading")

    if mconf.get("export"):
        # 原始模型下到 .partial/raw，导出 IR 到 .partial/ov，最终只保留 ov
        raw = partial / "raw"
        ov_out = partial / "ov"
        _download_modelscope(mconf["repo"], raw)
        if progress_cb:
            progress_cb(name, "exporting")
        if ov_out.exists():
            shutil.rmtree(ov_out)
        _export_openvino(raw, ov_out, mconf["task"])
        staged = ov_out
    else:
        # 预转换 OV 模型直接下载即用
        staged = partial / "ov"
        _download_modelscope(mconf["repo"], staged)

    # 校验 staged 内 required_files
    for rel in mconf.get("required_files", []):
        matches = list(staged.rglob(rel))
        if not matches or all(p.stat().st_size == 0 for p in matches):
            raise RuntimeError(f"model {name} incomplete after download: missing {rel}")

    # 原子就位：staged -> final
    if final.exists():
        shutil.rmtree(final)
    staged.rename(final)
    # 清理 .partial 残留（raw 原始权重不再需要）
    if partial.exists():
        shutil.rmtree(partial, ignore_errors=True)
    log.info("model %s ready in %.1fs", name, time.time() - t0)


def ensure_all_models(progress_cb=None) -> list[str]:
    """确保 info.json 中所有模型就绪；返回本次实际下载的模型名。"""
    info = common.load_info()
    downloaded = []
    for mconf in info["models"]:
        if not is_model_ready(mconf):
            download_one(mconf, progress_cb=progress_cb)
            downloaded.append(mconf["name"])
    return downloaded


def check_all_models() -> list[str]:
    """返回缺失模型名列表。"""
    info = common.load_info()
    return [m["name"] for m in info["models"] if not is_model_ready(m)]


def main() -> int:
    common.force_utf8_stdio()
    parser = argparse.ArgumentParser(description="local-kb-rag model downloader")
    parser.add_argument("--check", action="store_true", help="仅校验 required_files")
    parser.add_argument("--continue", dest="resume", action="store_true", help="断点续传重入")
    args = parser.parse_args()

    if args.check:
        missing = check_all_models()
        if missing:
            print(f"MISSING: {','.join(missing)}")
            return EXIT_DOWNLOAD_FAILED
        print("OK: all models ready")
        return EXIT_OK

    try:
        downloaded = ensure_all_models()
        print(f"OK: downloaded={downloaded or 'none (all cached)'}")
        return EXIT_OK
    except Exception as exc:  # noqa: BLE001
        log.exception("model download failed")
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_DOWNLOAD_FAILED


if __name__ == "__main__":
    sys.exit(main())
