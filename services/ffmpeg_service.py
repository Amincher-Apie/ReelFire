"""FFmpeg readiness checks and safe rough-cut generation."""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path


OUTPUT_SIZES = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}


def is_ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def create_rough_cut(
    input_path: Path,
    output_path: Path,
    start_time: float,
    end_time: float,
    output_ratio: str,
) -> Path:
    """Create a padded MP4 clip while preserving optional source audio."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg 不可用，无法生成粗剪视频")
    source = Path(input_path).resolve()
    destination = Path(output_path).resolve()
    if not source.is_file():
        raise FileNotFoundError("粗剪输入视频不存在")
    if output_ratio not in OUTPUT_SIZES:
        raise ValueError("output_ratio 仅支持 16:9、9:16 或 1:1")
    start, end = float(start_time), float(end_time)
    if not all(math.isfinite(value) for value in (start, end)) or start < 0 or start >= end:
        raise ValueError("粗剪边界必须满足 0 <= start_time < end_time")

    width, height = OUTPUT_SIZES[output_ratio]
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(source),
        "-t",
        f"{end - start:.3f}",
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        video_filter,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(destination),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="backslashreplace",
    )
    if result.returncode != 0:
        destination.unlink(missing_ok=True)
        detail = (result.stderr or result.stdout or "未知 FFmpeg 错误").strip()
        raise RuntimeError(f"FFmpeg 粗剪失败：{detail[-1000:]}")
    if not destination.is_file() or destination.stat().st_size <= 0:
        destination.unlink(missing_ok=True)
        raise RuntimeError("FFmpeg 未生成有效输出文件")
    return destination
