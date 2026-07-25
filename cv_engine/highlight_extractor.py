"""精彩片段提取器：基于敌人出现/消失事件提取粗剪片段。

核心思路：
    敌人出现 = 交火开始
    敌人消失 = 击杀完成/转移
    保留这段时间的视频片段（前后加缓冲）

用法:
    # 从已有检测结果提取片段
    python -m cv_engine.highlight_extractor \
        --json outputs/video_detect_valorant_v2/test_04_detection.json \
        --video test_videos/test_04.mp4 \
        --output outputs/highlights/test_04

    # 指定前后缓冲时间
    python -m cv_engine.highlight_extractor \
        --json detection.json --video test.mp4 \
        --pre-buffer 2.0 --post-buffer 2.0
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


# 视为"敌人"的类别（CS2 + Valorant）
DEFAULT_ENEMY_CLASSES = {"character_ct", "character_t", "enemy"}


class HighlightExtractor:
    """基于敌人出现/消失事件提取精彩片段。"""

    def __init__(
        self,
        enemy_classes: set[str] | None = None,
        pre_buffer: float = 1.5,
        post_buffer: float = 1.5,
        smooth_frames: int = 5,
        min_duration: float = 1.0,
        merge_gap: float = 1.0,
    ) -> None:
        self.enemy_classes = enemy_classes or DEFAULT_ENEMY_CLASSES
        self.pre_buffer = float(pre_buffer)
        self.post_buffer = float(post_buffer)
        self.smooth_frames = int(smooth_frames)
        self.min_duration = float(min_duration)
        self.merge_gap = float(merge_gap)

    def _frame_has_enemy(self, detections: list[dict[str, Any]]) -> bool:
        """判断一帧的检测结果中是否包含敌人。"""
        for det in detections:
            if str(det.get("class", "")) in self.enemy_classes:
                return True
        return False

    def _count_enemies(self, detections: list[dict[str, Any]]) -> int:
        """统计一帧中敌人的数量。"""
        return sum(
            1 for det in detections if str(det.get("class", "")) in self.enemy_classes
        )

    def _smooth_presence(
        self, presence: list[bool], fps: float
    ) -> list[bool]:
        """平滑敌人存在状态，消除短暂漏检导致的抖动。

        连续 smooth_frames 帧无敌人，才认为敌人真正消失。
        """
        if not presence or self.smooth_frames <= 0:
            return list(presence)
        n = len(presence)
        smoothed = list(presence)
        # 从后往前扫，如果当前帧无敌人，但前 smooth_frames 帧有敌人，则保持有敌人
        # 实际上更合理的做法：如果当前帧无敌人，但后续 smooth_frames 帧内又出现，则填补
        for i in range(n):
            if not smoothed[i]:
                # 检查后续 smooth_frames 帧是否有敌人
                look_ahead = min(i + self.smooth_frames + 1, n)
                if any(smoothed[j] for j in range(i + 1, look_ahead)):
                    smoothed[i] = True
        return smoothed

    def _detect_events(
        self, presence: list[bool], timestamps: list[float]
    ) -> list[tuple[float, float]]:
        """检测敌人出现/消失事件对，返回 [(appear_time, disappear_time), ...]。"""
        events: list[tuple[float, float]] = []
        in_segment = False
        appear_time = 0.0

        for i, (has_enemy, ts) in enumerate(zip(presence, timestamps)):
            if has_enemy and not in_segment:
                # 敌人出现
                appear_time = ts
                in_segment = True
            elif not has_enemy and in_segment:
                # 敌人消失
                events.append((appear_time, ts))
                in_segment = False

        # 如果视频结束时敌人仍在，闭合最后一个事件
        if in_segment and timestamps:
            events.append((appear_time, timestamps[-1]))

        return events

    def _build_segments(
        self,
        events: list[tuple[float, float]],
        duration: float,
    ) -> list[dict[str, Any]]:
        """根据事件生成片段，加前后缓冲，合并重叠。"""
        raw_segments: list[dict[str, Any]] = []
        for appear, disappear in events:
            start = max(0.0, appear - self.pre_buffer)
            end = min(duration, disappear + self.post_buffer)
            if end - start >= self.min_duration:
                raw_segments.append({
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "duration": round(end - start, 3),
                    "enemy_appear_at": round(appear, 3),
                    "enemy_disappear_at": round(disappear, 3),
                })

        if not raw_segments:
            return []

        # 合并重叠或相邻片段（间隔 < merge_gap 则合并）
        merged: list[dict[str, Any]] = [raw_segments[0].copy()]
        for seg in raw_segments[1:]:
            last = merged[-1]
            if seg["start"] - last["end"] <= self.merge_gap:
                # 合并
                last["end"] = seg["end"]
                last["duration"] = round(last["end"] - last["start"], 3)
                # 合并后的事件时间取最早出现和最晚消失
                last["enemy_appear_at"] = min(last["enemy_appear_at"], seg["enemy_appear_at"])
                last["enemy_disappear_at"] = max(last["enemy_disappear_at"], seg["enemy_disappear_at"])
            else:
                merged.append(seg.copy())

        return merged

    def extract(
        self,
        frame_results: list[dict[str, Any]],
        fps: float,
        duration: float,
    ) -> dict[str, Any]:
        """从逐帧检测结果提取精彩片段。

        Args:
            frame_results: 每帧检测结果，需含 timestamp 和 detections
            fps: 视频帧率
            duration: 视频总时长（秒）

        Returns:
            {segments, stats, config}
        """
        if not frame_results:
            return {
                "segments": [],
                "stats": {"total_segments": 0, "total_duration": 0.0, "highlight_ratio": 0.0},
                "config": self._config_dict(),
            }

        # 按时间排序
        sorted_frames = sorted(frame_results, key=lambda f: float(f.get("timestamp", 0)))
        timestamps = [float(f.get("timestamp", 0)) for f in sorted_frames]
        presence = [
            self._frame_has_enemy(f.get("detections", [])) for f in sorted_frames
        ]
        enemy_counts = [
            self._count_enemies(f.get("detections", [])) for f in sorted_frames
        ]

        # 平滑处理
        smoothed = self._smooth_presence(presence, fps)

        # 检测事件
        events = self._detect_events(smoothed, timestamps)

        # 生成片段
        segments = self._build_segments(events, duration)

        # 给每个片段补充检测详情（用于 Agent 后续分析）
        for seg in segments:
            seg["peak_enemy_count"] = 0
            seg["detected_classes"] = []
            seg["enemy_classes_in_segment"] = []
            seg["detections_summary"] = []
            seg["reason"] = "enemy_engagement"

            classes_set: set[str] = set()
            enemy_classes_set: set[str] = set()
            # 按 track_id（如果有）或 (class+bbox) 聚合检测
            track_map: dict[str, dict[str, Any]] = {}

            for f in sorted_frames:
                ts = float(f.get("timestamp", 0))
                if not (seg["start"] <= ts <= seg["end"]):
                    continue
                dets = f.get("detections", []) or []
                if not dets:
                    continue

                for det in dets:
                    cls_name = str(det.get("class", ""))
                    if not cls_name:
                        continue
                    classes_set.add(cls_name)
                    if cls_name in self.enemy_classes:
                        enemy_classes_set.add(cls_name)
                        seg["peak_enemy_count"] = max(
                            seg["peak_enemy_count"],
                            sum(1 for d in dets if str(d.get("class", "")) in self.enemy_classes),
                        )

                    # track_id 优先；否则用 class+bbox 近似
                    track_id = det.get("track_id")
                    if track_id is None:
                        # 用类别 + bbox 中心作为临时 key
                        bbox = det.get("bbox") or []
                        if len(bbox) == 4:
                            cx = round((bbox[0] + bbox[2]) / 2, 1)
                            cy = round((bbox[1] + bbox[3]) / 2, 1)
                            key = f"{cls_name}_{cx}_{cy}"
                        else:
                            key = f"{cls_name}_no_bbox"
                    else:
                        key = f"{cls_name}_tid{track_id}"

                    if key not in track_map:
                        track_map[key] = {
                            "track_id": track_id,
                            "class": cls_name,
                            "confidence_list": [],
                            "first_seen": ts,
                            "last_seen": ts,
                            "detection_count": 0,
                        }
                    entry = track_map[key]
                    entry["detection_count"] += 1
                    entry["first_seen"] = min(entry["first_seen"], ts)
                    entry["last_seen"] = max(entry["last_seen"], ts)
                    conf = det.get("confidence")
                    if isinstance(conf, (int, float)):
                        entry["confidence_list"].append(float(conf))

            # 聚合每个 track 的置信度统计
            for entry in track_map.values():
                confs = entry.pop("confidence_list", [])
                if confs:
                    entry["confidence"] = round(sum(confs) / len(confs), 4)
                    entry["confidence_max"] = round(max(confs), 4)
                    entry["confidence_min"] = round(min(confs), 4)
                else:
                    entry["confidence"] = 0.0
                entry["first_seen"] = round(entry["first_seen"], 3)
                entry["last_seen"] = round(entry["last_seen"], 3)
                seg["detections_summary"].append(entry)

            seg["detected_classes"] = sorted(classes_set)
            seg["enemy_classes_in_segment"] = sorted(enemy_classes_set)

        total_seg_duration = sum(s["duration"] for s in segments)
        stats = {
            "total_segments": len(segments),
            "total_duration": round(total_seg_duration, 3),
            "highlight_ratio": round(total_seg_duration / max(duration, 1e-6), 4),
            "video_duration": round(duration, 3),
            "frames_analyzed": len(frame_results),
            "frames_with_enemy": sum(1 for p in presence if p),
            "enemy_presence_ratio": round(
                sum(1 for p in presence if p) / max(len(presence), 1), 4
            ),
        }

        return {
            "segments": segments,
            "stats": stats,
            "config": self._config_dict(),
        }

    def _config_dict(self) -> dict[str, Any]:
        return {
            "enemy_classes": sorted(self.enemy_classes),
            "pre_buffer": self.pre_buffer,
            "post_buffer": self.post_buffer,
            "smooth_frames": self.smooth_frames,
            "min_duration": self.min_duration,
            "merge_gap": self.merge_gap,
        }


def _merge_segments_to_video(
    source_video: Path,
    segments: list[dict[str, Any]],
    output_path: Path,
) -> Path:
    """用 FFmpeg 把多个片段切片并合并成一个视频。

    Args:
        source_video: 原始视频路径
        segments: 片段列表 [{start, end, ...}]
        output_path: 输出视频路径

    Returns:
        输出视频路径
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg 不可用，无法生成粗剪视频")

    if not segments:
        raise ValueError("没有片段可合并")

    source = Path(source_video).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"输入视频不存在: {source}")

    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 方案：用 FFmpeg 的 concat filter 一次性合并多个片段
    # 每个片段作为一个输入，然后 concat
    inputs: list[str] = []
    filters: list[str] = []
    for i, seg in enumerate(segments):
        inputs.extend([
            "-ss", f"{float(seg['start']):.3f}",
            "-t", f"{float(seg['end']) - float(seg['start']):.3f}",
            "-i", str(source),
        ])
        filters.append(f"[{i}:v][{i}:a]")

    # concat filter
    concat_filter = "".join(filters) + f"concat=n={len(segments)}:v=1:a=1[v][a]"

    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        *inputs,
        "-filter_complex", concat_filter,
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "160k",
        "-movflags", "+faststart",
        str(output_path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="backslashreplace",
    )

    if result.returncode != 0:
        # 如果合并失败（可能是音频问题），尝试无音频版本
        detail = (result.stderr or result.stdout or "").strip()
        print(f"[WARN] 带音频合并失败，尝试无音频版本: {detail[-200:]}", file=sys.stderr)
        return _merge_segments_no_audio(source, segments, output_path)

    if not output_path.is_file() or output_path.stat().st_size <= 0:
        output_path.unlink(missing_ok=True)
        raise RuntimeError("FFmpeg 未生成有效输出文件")

    return output_path


def _merge_segments_no_audio(
    source: Path,
    segments: list[dict[str, Any]],
    output_path: Path,
) -> Path:
    """无音频版本的多片段合并（降级方案）。"""
    ffmpeg = shutil.which("ffmpeg")
    inputs: list[str] = []
    filters: list[str] = []
    for i, seg in enumerate(segments):
        inputs.extend([
            "-ss", f"{float(seg['start']):.3f}",
            "-t", f"{float(seg['end']) - float(seg['start']):.3f}",
            "-i", str(source),
        ])
        filters.append(f"[{i}:v]")

    concat_filter = "".join(filters) + f"concat=n={len(segments)}:v=1:a=0[v]"

    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        *inputs,
        "-filter_complex", concat_filter,
        "-map", "[v]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-movflags", "+faststart",
        str(output_path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="backslashreplace",
    )

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "未知错误").strip()
        raise RuntimeError(f"FFmpeg 合并失败：{detail[-1000:]}")

    if not output_path.is_file() or output_path.stat().st_size <= 0:
        output_path.unlink(missing_ok=True)
        raise RuntimeError("FFmpeg 未生成有效输出文件")

    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="精彩片段提取器")
    parser.add_argument(
        "--json",
        type=Path,
        required=True,
        help="video_detector 输出的 detection JSON 文件",
    )
    parser.add_argument(
        "--video",
        type=Path,
        required=True,
        help="原始视频路径（用于 FFmpeg 切片）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/highlights"),
        help="输出目录",
    )
    parser.add_argument(
        "--pre-buffer",
        type=float,
        default=1.5,
        help="敌人出现前保留的画面时长（秒）",
    )
    parser.add_argument(
        "--post-buffer",
        type=float,
        default=1.5,
        help="敌人消失后保留的画面时长（秒）",
    )
    parser.add_argument(
        "--smooth-frames",
        type=int,
        default=5,
        help="抖动平滑帧数（连续N帧无敌人才算消失）",
    )
    parser.add_argument(
        "--min-duration",
        type=float,
        default=1.0,
        help="片段最短时长（秒），过短则丢弃",
    )
    parser.add_argument(
        "--merge-gap",
        type=float,
        default=1.0,
        help="相邻片段间隔小于此值则合并（秒）",
    )
    parser.add_argument(
        "--no-cut",
        action="store_true",
        help="只提取片段信息，不生成粗剪视频",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    json_path = args.json.resolve()
    if not json_path.is_file():
        print(f"错误: 检测 JSON 不存在: {json_path}")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        detection = json.load(f)

    # 兼容 video_detector 的 JSON 结构
    frame_results = detection.get("frames", [])
    video_info = detection.get("video_info", {})
    fps = float(video_info.get("fps", 24.0))
    duration = float(video_info.get("duration_seconds", 0.0))

    if not frame_results:
        print("错误: JSON 中没有帧检测结果")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"精彩片段提取")
    print(f"视频: {args.video.name}")
    print(f"总时长: {duration:.2f}s | FPS: {fps:.1f} | 帧数: {len(frame_results)}")
    print(f"{'='*60}")

    extractor = HighlightExtractor(
        pre_buffer=args.pre_buffer,
        post_buffer=args.post_buffer,
        smooth_frames=args.smooth_frames,
        min_duration=args.min_duration,
        merge_gap=args.merge_gap,
    )

    result = extractor.extract(frame_results, fps, duration)

    segments = result["segments"]
    stats = result["stats"]

    print(f"\n--- 提取结果 ---")
    print(f"片段数: {stats['total_segments']}")
    print(f"精彩总时长: {stats['total_duration']:.2f}s / {duration:.2f}s ({stats['highlight_ratio']*100:.1f}%)")
    print(f"有敌人的帧: {stats['frames_with_enemy']} ({stats['enemy_presence_ratio']*100:.1f}%)")
    print(f"\n片段列表:")
    for i, seg in enumerate(segments, 1):
        print(
            f"  [{i}] {seg['start']:.2f}s - {seg['end']:.2f}s "
            f"(时长 {seg['duration']:.2f}s, 峰值敌人 {seg['peak_enemy_count']})"
        )

    # 保存片段 JSON
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    segments_json = output_dir / f"{args.video.stem}_highlights.json"
    with open(segments_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n片段 JSON: {segments_json}")

    # 生成粗剪视频
    if not args.no_cut and segments:
        video_path = args.video.resolve()
        if not video_path.is_file():
            print(f"错误: 原始视频不存在: {video_path}")
            sys.exit(1)

        print(f"\n正在生成粗剪视频...")
        output_video = output_dir / f"{args.video.stem}_highlights.mp4"
        try:
            _merge_segments_to_video(video_path, segments, output_video)
            print(f"粗剪视频: {output_video}")
            print(f"  片段数: {len(segments)} | 总时长: {stats['total_duration']:.2f}s")
        except Exception as e:
            print(f"生成粗剪视频失败: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
