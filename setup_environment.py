#!/usr/bin/env python3
"""Create or adapt a Conda environment for ReelFire.

Typical usage after cloning the repository:

    python setup_environment.py

If a non-base Conda environment is already active, it is reused. Otherwise the
script creates (or reuses) a Conda environment named ``ReelFire`` and reruns
itself inside that environment.
"""

from __future__ import annotations

import argparse
import json
import locale
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parent
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"
DEFAULT_ENV_NAME = "ReelFire"
MIN_PYTHON = (3, 10)
MAX_PYTHON = (3, 13)


class SetupError(RuntimeError):
    """Raised when the local machine cannot be adapted safely."""


def command_text(command: Sequence[str]) -> str:
    """Return a readable command without invoking a platform shell."""
    return subprocess.list2cmdline([str(part) for part in command])


def run(
    command: Sequence[str],
    *,
    check: bool = True,
    capture: bool = False,
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [str(part) for part in command]
    print(f"\n> {command_text(command)}")
    if dry_run:
        return subprocess.CompletedProcess(command, 0, "", "")
    return subprocess.run(
        command,
        check=check,
        text=True,
        encoding=locale.getpreferredencoding(False) or "utf-8",
        errors="backslashreplace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def conda_executable() -> str | None:
    configured = os.environ.get("CONDA_EXE")
    if configured and Path(configured).exists():
        return configured
    return shutil.which("conda")


def active_conda_environment() -> str | None:
    return os.environ.get("CONDA_DEFAULT_ENV")


def conda_environment_exists(conda: str, env_name: str) -> bool:
    result = run([conda, "env", "list", "--json"], capture=True)
    try:
        prefixes = json.loads(result.stdout).get("envs", [])
    except json.JSONDecodeError as exc:
        raise SetupError("无法解析 `conda env list --json` 的输出。") from exc
    wanted = env_name.casefold()
    return any(Path(prefix).name.casefold() == wanted for prefix in prefixes)


def rerun_inside_project_environment(args: argparse.Namespace) -> int | None:
    """Create/reuse the project env when no non-base env is active."""
    if args.inside_env:
        return None

    active = active_conda_environment()
    if active and active.casefold() != "base":
        print(f"[环境] 复用当前 Conda 环境：{active}")
        return None

    conda = conda_executable()
    if not conda:
        raise SetupError(
            "没有检测到 Conda。请先安装 Miniconda/Anaconda，并在 Conda Prompt 中运行本脚本。"
        )

    env_exists = conda_environment_exists(conda, args.env_name)
    if not env_exists:
        run(
            [
                conda,
                "create",
                "--yes",
                "--name",
                args.env_name,
                "python=3.11",
                "pip",
            ],
            dry_run=args.dry_run,
        )
    else:
        print(f"[环境] 找到已有 Conda 环境：{args.env_name}")

    if args.dry_run:
        print(
            f"[试运行] 随后会在 {args.env_name} 中重新运行本脚本；当前未修改任何环境。"
        )
        return 0

    forwarded = [
        conda,
        "run",
        "--no-capture-output",
        "--name",
        args.env_name,
        "python",
        str(Path(__file__).resolve()),
        "--inside-env",
        "--env-name",
        args.env_name,
    ]
    if args.force_torch:
        forwarded.append("--force-torch")
    if args.skip_ffmpeg:
        forwarded.append("--skip-ffmpeg")
    result = run(forwarded, check=False)
    return result.returncode


def check_python_version() -> None:
    current = sys.version_info[:2]
    if not (MIN_PYTHON <= current < MAX_PYTHON):
        raise SetupError(
            f"当前 Python 为 {platform.python_version()}；ReelFire 要求 Python >=3.10,<3.13，"
            "推荐使用 3.11。"
        )
    print(f"[Python] {platform.python_version()} ({sys.executable})")


def query_nvidia_gpu() -> dict[str, str] | None:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return None
    result = run(
        [
            nvidia_smi,
            "--query-gpu=name,driver_version",
            "--format=csv,noheader",
        ],
        check=False,
        capture=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    first_gpu = result.stdout.strip().splitlines()[0]
    parts = [part.strip() for part in first_gpu.split(",", maxsplit=1)]
    return {
        "name": parts[0],
        "driver": parts[1] if len(parts) > 1 else "unknown",
    }


def driver_major(driver: str) -> int:
    match = re.match(r"(\d+)", driver)
    return int(match.group(1)) if match else 0


def cuda_channels_for_driver(driver: str) -> list[str]:
    """Choose official PyTorch wheel channels supported by the driver.

    The list is ordered from the newest compatible CUDA runtime to older
    fallbacks. PyTorch wheels bundle the CUDA runtime; a local CUDA Toolkit is
    not required, but the NVIDIA driver must be recent enough.
    """
    major = driver_major(driver)
    if major >= 570:
        return ["cu128", "cu126", "cu124"]
    if major >= 560:
        return ["cu126", "cu124", "cu121"]
    if major >= 550:
        return ["cu124", "cu121", "cu118"]
    if major >= 525:
        return ["cu121", "cu118"]
    if major >= 520:
        return ["cu118"]
    return []


def torch_status() -> dict[str, object]:
    probe = r"""
import json
try:
    import torch
except Exception as exc:
    print(json.dumps({"installed": False, "error": str(exc)}))
else:
    mps = bool(
        hasattr(torch.backends, "mps")
        and torch.backends.mps.is_available()
    )
    print(json.dumps({
        "installed": True,
        "version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda,
        "mps_available": mps,
    }))
"""
    result = run([sys.executable, "-c", probe], check=False, capture=True)
    if result.returncode != 0:
        return {"installed": False, "error": result.stderr.strip()}
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"installed": False, "error": result.stdout.strip()}


def pip_command(*arguments: str) -> list[str]:
    return [sys.executable, "-m", "pip", *arguments]


def install_torch_for_machine(
    gpu: dict[str, str] | None,
    *,
    force: bool,
    dry_run: bool,
) -> str:
    status = torch_status()
    system = platform.system()
    machine = platform.machine().lower()

    if status.get("installed"):
        print(
            "[PyTorch] 已安装 "
            f"{status.get('version')}；CUDA={status.get('cuda_available')}；"
            f"MPS={status.get('mps_available')}"
        )

    if gpu:
        print(f"[GPU] {gpu['name']}，驱动 {gpu['driver']}")
        if status.get("cuda_available") and not force:
            print("[PyTorch] 当前 CUDA 构建可用，保留现有安装。")
            return "cuda"

        channels = cuda_channels_for_driver(gpu["driver"])
        if not channels:
            print("[警告] NVIDIA 驱动过旧，无法安全匹配 CUDA wheel，将使用 CPU 版。")
        else:
            for channel in channels:
                print(f"[PyTorch] 尝试官方 {channel} 构建……")
                result = run(
                    pip_command(
                        "install",
                        "--upgrade",
                        "--force-reinstall",
                        "torch",
                        "torchvision",
                        "--index-url",
                        f"https://download.pytorch.org/whl/{channel}",
                    ),
                    check=False,
                    dry_run=dry_run,
                )
                if dry_run:
                    return "cuda"
                if result.returncode == 0 and torch_status().get("cuda_available"):
                    print(f"[PyTorch] {channel} CUDA 构建安装成功。")
                    return "cuda"
                print(f"[PyTorch] {channel} 不可用，尝试较旧的兼容构建。")
            print("[警告] CUDA 构建安装或验证失败，将回退到 CPU 版。")

    if system == "Darwin":
        run(
            pip_command("install", "--upgrade", "torch", "torchvision"),
            dry_run=dry_run,
        )
        backend = "mps" if machine in {"arm64", "aarch64"} else "cpu"
        print(f"[PyTorch] macOS 使用 {backend.upper()} 后端（可用性将在末尾验证）。")
        return backend

    if status.get("installed") and not force and not gpu:
        print("[PyTorch] 未检测到 NVIDIA GPU，保留现有 PyTorch 安装。")
        return "cpu"

    run(
        pip_command(
            "install",
            "--upgrade",
            "--force-reinstall" if force or status.get("installed") else "--prefer-binary",
            "torch",
            "torchvision",
            "--index-url",
            "https://download.pytorch.org/whl/cpu",
        ),
        dry_run=dry_run,
    )
    print("[PyTorch] 使用 CPU 构建。")
    return "cpu"


def install_application_dependencies(*, dry_run: bool) -> None:
    if not REQUIREMENTS.is_file():
        raise SetupError(f"找不到依赖文件：{REQUIREMENTS}")
    run(
        pip_command("install", "--upgrade", "pip", "setuptools", "wheel"),
        dry_run=dry_run,
    )
    run(
        pip_command("install", "--requirement", str(REQUIREMENTS)),
        dry_run=dry_run,
    )


def ensure_ffmpeg(*, skip: bool, dry_run: bool) -> None:
    if skip:
        print("[FFmpeg] 已按参数跳过检查。")
        return
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        print("[FFmpeg] ffmpeg 和 ffprobe 已在 PATH 中。")
        return

    conda = conda_executable()
    conda_prefix = os.environ.get("CONDA_PREFIX")
    if not conda or not conda_prefix:
        raise SetupError(
            "未检测到 FFmpeg，且当前不是可写入的 Conda 环境。"
            "请安装 FFmpeg 并将 ffmpeg/ffprobe 加入 PATH。"
        )

    print("[FFmpeg] 未检测到完整工具，使用 conda-forge 安装到当前环境。")
    run(
        [
            conda,
            "install",
            "--yes",
            "--prefix",
            conda_prefix,
            "--channel",
            "conda-forge",
            "ffmpeg",
        ],
        dry_run=dry_run,
    )


def verify_installation(expected_backend: str, *, skip_ffmpeg: bool) -> None:
    probe = r"""
import json
import cv2
import flask
import numpy
import torch
import torchvision
import ultralytics
print(json.dumps({
    "flask": flask.__version__,
    "opencv": cv2.__version__,
    "numpy": numpy.__version__,
    "torch": torch.__version__,
    "torchvision": torchvision.__version__,
    "ultralytics": ultralytics.__version__,
    "cuda": torch.cuda.is_available(),
    "mps": bool(hasattr(torch.backends, "mps") and torch.backends.mps.is_available()),
}))
"""
    result = run([sys.executable, "-c", probe], capture=True)
    details = json.loads(result.stdout.strip().splitlines()[-1])
    print("\n[验证] Python 依赖：")
    for key, value in details.items():
        print(f"  - {key}: {value}")

    if expected_backend == "cuda" and not details["cuda"]:
        raise SetupError("安装结束后 CUDA 仍不可用，请检查 NVIDIA 驱动并重新运行。")
    if not skip_ffmpeg and (not shutil.which("ffmpeg") or not shutil.which("ffprobe")):
        raise SetupError("FFmpeg 安装后仍未出现在 PATH 中，请重新激活 Conda 环境。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一键配置 ReelFire Conda/Python 环境")
    parser.add_argument(
        "--env-name",
        default=DEFAULT_ENV_NAME,
        help=f"无可复用环境时创建的 Conda 环境名（默认：{DEFAULT_ENV_NAME}）",
    )
    parser.add_argument(
        "--force-torch",
        action="store_true",
        help="即使当前 PyTorch 可用，也重新选择并安装对应构建",
    )
    parser.add_argument(
        "--skip-ffmpeg",
        action="store_true",
        help="跳过 FFmpeg 检查和 Conda 安装",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只显示将执行的安装操作，不修改环境",
    )
    parser.add_argument("--inside-env", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        delegated_result = rerun_inside_project_environment(args)
        if delegated_result is not None:
            return delegated_result

        active = active_conda_environment()
        if not active:
            raise SetupError("脚本没有运行在 Conda 环境中。")
        print(f"[Conda] 当前环境：{active}")
        check_python_version()

        gpu = query_nvidia_gpu()
        backend = install_torch_for_machine(
            gpu,
            force=args.force_torch,
            dry_run=args.dry_run,
        )
        install_application_dependencies(dry_run=args.dry_run)
        ensure_ffmpeg(skip=args.skip_ffmpeg, dry_run=args.dry_run)

        if args.dry_run:
            print("\n[试运行完成] 未修改 Conda 环境或安装任何软件包。")
            return 0

        verify_installation(backend, skip_ffmpeg=args.skip_ffmpeg)
        print("\n[完成] ReelFire 环境已经配置并验证。")
        print(f"下次开发前运行：conda activate {active}")
        return 0
    except (SetupError, subprocess.CalledProcessError, OSError) as exc:
        print(f"\n[失败] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
