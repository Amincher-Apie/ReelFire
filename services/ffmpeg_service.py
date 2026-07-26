"""FFmpeg readiness checks and safe rough-cut generation."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4


OUTPUT_SIZES = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}


def is_ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _temporary_output(destination: Path) -> Path:
    return destination.with_name(
        f".{destination.stem}.{uuid4().hex}.tmp{destination.suffix}"
    )


def _process_detail(
    result: subprocess.CompletedProcess[str],
    sensitive_paths: tuple[Path, ...],
) -> str:
    detail = (result.stderr or result.stdout or "未知错误").strip()
    for path in sensitive_paths:
        resolved = str(path.resolve())
        detail = detail.replace(resolved, path.name)
        detail = detail.replace(resolved.replace("\\", "/"), path.name)
    return detail[-1000:]


def _run_ffmpeg_atomically(
    command: list[str],
    temporary: Path,
    destination: Path,
    source: Path,
    error_label: str,
) -> Path:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="backslashreplace",
            shell=False,
        )
        if result.returncode != 0:
            detail = _process_detail(result, (source, temporary, destination))
            raise RuntimeError(
                f"{error_label}（退出码 {result.returncode}）：{detail}"
            )
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise RuntimeError("FFmpeg 未生成有效输出文件")
        os.replace(temporary, destination)
        return destination
    except OSError as exc:
        raise RuntimeError(f"{error_label}：无法启动或写入输出") from exc
    finally:
        temporary.unlink(missing_ok=True)


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
    temporary = _temporary_output(destination)
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
        str(temporary),
    ]
    return _run_ffmpeg_atomically(
        command,
        temporary,
        destination,
        source,
        "FFmpeg 粗剪失败",
    )


def _normalized_segment_bounds(
    segments: object,
) -> list[tuple[int, float, float]]:
    if not isinstance(segments, list) or not segments:
        raise ValueError("segments 必须是非空数组")
    normalized: list[tuple[int, float, float]] = []
    seen_orders: set[int] = set()
    for index, item in enumerate(segments):
        if not isinstance(item, dict):
            raise ValueError(f"segments[{index}] 必须是对象")
        order = item.get("order")
        if isinstance(order, bool) or not isinstance(order, int) or order <= 0:
            raise ValueError(f"segments[{index}].order 必须是正整数")
        if order in seen_orders:
            raise ValueError(f"segments[{index}].order 不能重复")
        seen_orders.add(order)
        start_value = item.get("start")
        end_value = item.get("end")
        if (
            isinstance(start_value, bool)
            or isinstance(end_value, bool)
            or not isinstance(start_value, (int, float))
            or not isinstance(end_value, (int, float))
        ):
            raise ValueError(f"segments[{index}] 的 start/end 必须是有限数字")
        start = float(start_value)
        end = float(end_value)
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or start >= end
        ):
            raise ValueError(
                f"segments[{index}] 必须满足 0 <= start < end"
            )
        normalized.append((order, start, end))
    return sorted(normalized, key=lambda item: item[0])


def _source_has_audio(ffprobe: str, source: Path) -> bool:
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        str(source),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="backslashreplace",
            shell=False,
        )
    except OSError as exc:
        raise RuntimeError("FFprobe 检查音频流失败：无法启动 FFprobe") from exc
    if result.returncode != 0:
        detail = _process_detail(result, (source,))
        raise RuntimeError(
            f"FFprobe 检查音频流失败（退出码 {result.returncode}）：{detail}"
        )
    return bool(result.stdout.strip())


def create_multi_segment_rough_cut(
    input_path: Path,
    output_path: Path,
    segments: list[dict[str, Any]],
    output_ratio: str,
) -> Path:
    """Concatenate normalized segments in ``order`` order into one MP4."""

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg 或 FFprobe 不可用，无法生成多片段粗剪视频")
    source = Path(input_path).resolve()
    destination = Path(output_path).resolve()
    if not source.is_file():
        raise FileNotFoundError("粗剪输入视频不存在")
    if output_ratio not in OUTPUT_SIZES:
        raise ValueError("output_ratio 仅支持 16:9、9:16 或 1:1")
    ordered = _normalized_segment_bounds(segments)
    has_audio = _source_has_audio(ffprobe, source)

    width, height = OUTPUT_SIZES[output_ratio]
    filters: list[str] = []
    concat_inputs: list[str] = []
    for index, (_, start, end) in enumerate(ordered):
        video_label = f"v{index}"
        filters.append(
            f"[0:v:0]trim=start={start:.6f}:end={end:.6f},"
            "setpts=PTS-STARTPTS,"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1[{video_label}]"
        )
        concat_inputs.append(f"[{video_label}]")
        if has_audio:
            audio_label = f"a{index}"
            filters.append(
                f"[0:a:0]atrim=start={start:.6f}:end={end:.6f},"
                f"asetpts=PTS-STARTPTS[{audio_label}]"
            )
            concat_inputs.append(f"[{audio_label}]")
    filters.append(
        "".join(concat_inputs)
        + f"concat=n={len(ordered)}:v=1:a={1 if has_audio else 0}"
        + ("[vout][aout]" if has_audio else "[vout]")
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_output(destination)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[vout]",
    ]
    if has_audio:
        command.extend(["-map", "[aout]"])
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
        ]
    )
    if has_audio:
        command.extend(["-c:a", "aac", "-b:a", "160k"])
    command.extend(["-movflags", "+faststart", str(temporary)])
    return _run_ffmpeg_atomically(
        command,
        temporary,
        destination,
        source,
        "FFmpeg 多片段粗剪失败",
    )
