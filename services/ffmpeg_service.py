"""FFmpeg readiness check and future rough-cut integration point."""

from __future__ import annotations

import shutil
from pathlib import Path


def is_ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def create_rough_cut(
    input_path: Path,
    output_path: Path,
    start_time: float,
    end_time: float,
    output_ratio: str,
) -> Path:
    """Create a real rough-cut video and return its path when implemented."""

    del input_path, output_path, start_time, end_time, output_ratio
    raise NotImplementedError(
        "FFmpeg 粗剪逻辑尚未实现，请在 create_rough_cut 中接入真实命令"
    )
