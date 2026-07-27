"""视频目标检测模块（不含跟踪），用于快速测试自定义模型效果。

用法:
    # 检测单个视频
    python -m cv_engine.video_detector --video test_videos/test_01.mp4 --model runs/detect/custom_fps_v3/weights/best.pt

    # 批量检测文件夹内所有视频
    python -m cv_engine.video_detector --batch test_videos --model runs/detect/custom_fps_v3/weights/best.pt

    # 指定输出目录和置信度
    python -m cv_engine.video_detector --batch test_videos --model runs/detect/custom_fps_v3/weights/best.pt --output outputs/video_detect --conf 0.3
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

from cv_engine.yolo_detector import YoloDetector


# 类别对应的颜色 (BGR)
CLASS_COLORS = {
    "character_ct": (0, 0, 255),      # 红
    "character_t": (0, 255, 0),       # 绿
    "weapon_rifle": (255, 0, 0),      # 蓝
    "weapon_pistol": (0, 165, 255),   # 橙
    "prop": (255, 255, 0),            # 青
}
DEFAULT_COLOR = (128, 128, 128)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="视频目标检测（不含跟踪）")
    parser.add_argument("--video", type=Path, default=None, help="输入视频路径")
    parser.add_argument("--batch", type=Path, default=None, help="批量检测：指定文件夹路径")
    parser.add_argument("--model", type=Path, default=Path("models/yolo11n.pt"), help="YOLO 模型权重")
    parser.add_argument("--output", type=Path, default=Path("outputs/video_detect"), help="输出目录")
    parser.add_argument("--conf", type=float, default=0.35, help="置信度阈值 (default: 0.35)")
    parser.add_argument("--skip-frames", type=int, default=0, help="跳帧数，0=每帧都检测（default: 0）")
    parser.add_argument("--no-save-video", action="store_true", help="不保存带检测框的视频（只输出 JSON）")
    parser.add_argument("--track", action="store_true", help="启用 ByteTrack 目标跟踪，输出 track_id（用于 Agent 分析）")
    parser.add_argument("--trajectory-output", type=Path, default=None, help="轨迹 JSON 输出路径（仅 --track 模式有效）")
    return parser.parse_args()


def draw_detections(frame: np.ndarray, detections: list) -> np.ndarray:
    """在帧上绘制检测框和标签。"""
    annotated = frame.copy()
    for det in detections:
        x1, y1, x2, y2 = [int(v) for v in det["bbox"]]
        class_name = det["class"]
        conf = det["confidence"]
        color = CLASS_COLORS.get(class_name, DEFAULT_COLOR)

        # 画框
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

        # 标签（如有 track_id 则附加）
        track_id = det.get("track_id")
        if track_id is not None:
            label = f"#{track_id} {class_name} {conf:.2f}"
        else:
            label = f"{class_name} {conf:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(annotated, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(annotated, label, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return annotated


def detect_video(
    video_path: Path,
    model_path: Path,
    confidence_threshold: float = 0.35,
    output_dir: Path | None = None,
    skip_frames: int = 0,
    save_video: bool = True,
    track: bool = False,
    trajectory_output_path: Path | None = None,
) -> dict:
    """对单个视频进行检测，返回统计信息和逐帧结果。

    Args:
        track: 若为 True，启用 ByteTrack 跟踪，每条检测会带 track_id
        trajectory_output_path: 轨迹 JSON 输出路径（仅 track=True 时有效）
    """
    print(f"\n{'='*60}")
    print(f"检测视频: {video_path.name}")
    print(f"模型: {model_path.name}")
    print(f"置信度阈值: {confidence_threshold}")
    print(f"目标跟踪: {'开启 (ByteTrack)' if track else '关闭'}")
    print(f"{'='*60}")

    detector = YoloDetector(str(model_path), confidence_threshold)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"无法打开视频: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"分辨率: {width}x{height} | FPS: {fps:.1f} | 总帧数: {total_frames}")

    # 输出视频
    video_writer = None
    if save_video and output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_video_path = output_dir / f"{video_path.stem}_detected.mp4"
        # 尝试多个编码器，找到可用的
        for codec_name in ["mp4v", "XVID", "avc1", "H264"]:
            fourcc = cv2.VideoWriter_fourcc(*codec_name)
            video_writer = cv2.VideoWriter(str(output_video_path), fourcc, fps, (width, height))
            if video_writer.isOpened():
                print(f"  视频编码器: {codec_name}")
                break
            else:
                video_writer.release()
                video_writer = None
        if video_writer is None:
            print("  警告: 无法初始化视频编码器，将不生成检测视频")

    frame_results = []
    class_stats: dict[str, int] = {}
    conf_sum: dict[str, list[float]] = {}
    trajectory_data: dict[int, list[dict]] = {}  # track_id -> trajectory points
    start_time = time.time()
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 跳帧
        if skip_frames > 0 and frame_idx % (skip_frames + 1) != 0:
            frame_idx += 1
            continue

        # 根据是否启用跟踪选择调用方式
        if track:
            results = detector.model.track(
                source=frame,
                conf=confidence_threshold,
                tracker="bytetrack.yaml",
                verbose=False,
                persist=True,
            )
            detections = []
            for result in results:
                if result.boxes is None:
                    continue
                track_ids = result.boxes.id
                if track_ids is None:
                    continue
                for i in range(len(track_ids)):
                    x1, y1, x2, y2 = [float(v) for v in result.boxes.xyxy[i].tolist()]
                    confidence = float(result.boxes.conf[i])
                    class_id = int(result.boxes.cls[i])
                    class_name = str(detector.model.names[class_id])
                    track_id = int(track_ids[i])

                    detections.append({
                        "class": class_name,
                        "confidence": round(confidence, 4),
                        "bbox": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                        "class_id": class_id,
                        "track_id": track_id,
                    })

                    # 记录轨迹
                    cx = int((x1 + x2) / 2)
                    cy = int((y1 + y2) / 2)
                    if track_id not in trajectory_data:
                        trajectory_data[track_id] = []
                    trajectory_data[track_id].append({
                        "frame": frame_idx,
                        "timestamp": round(frame_idx / fps, 3) if fps > 0 else 0.0,
                        "center": [cx, cy],
                        "bbox": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                        "class": class_name,
                        "confidence": round(confidence, 4),
                    })
        else:
            detections = detector.detect(frame)

        # 记录结果
        frame_info = {
            "frame_id": frame_idx,
            "timestamp": round(frame_idx / fps, 3) if fps > 0 else 0,
            "detections": detections,
            "object_count": len(detections),
        }
        frame_results.append(frame_info)

        # 统计
        for det in detections:
            cls = det["class"]
            class_stats[cls] = class_stats.get(cls, 0) + 1
            conf_sum.setdefault(cls, []).append(det["confidence"])

        # 写入视频
        if video_writer:
            annotated = draw_detections(frame, detections)
            video_writer.write(annotated)

        # 进度
        if frame_idx % 30 == 0:
            progress = (frame_idx / total_frames * 100) if total_frames > 0 else 0
            elapsed = time.time() - start_time
            print(f"  帧 {frame_idx}/{total_frames} ({progress:.1f}%) | 已用 {elapsed:.1f}s | 本帧 {len(detections)} 目标")

        frame_idx += 1

    cap.release()
    if video_writer:
        video_writer.release()

    elapsed = time.time() - start_time
    processed_frames = len(frame_results)

    # 类别统计
    class_summary = []
    for cls, count in sorted(class_stats.items()):
        confs = conf_sum.get(cls, [])
        class_summary.append({
            "class": cls,
            "total_detections": count,
            "avg_confidence": round(sum(confs) / len(confs), 4) if confs else 0,
            "max_confidence": round(max(confs), 4) if confs else 0,
            "min_confidence": round(min(confs), 4) if confs else 0,
        })

    # 轨迹统计
    tracking_summary = None
    if track:
        tracking_summary = {
            "total_tracks": len(trajectory_data),
            "tracks_by_class": {},
            "trajectory_output": None,
        }
        for tid, pts in trajectory_data.items():
            if pts:
                cls = pts[0]["class"]
                tracking_summary["tracks_by_class"][cls] = tracking_summary["tracks_by_class"].get(cls, 0) + 1
        if trajectory_output_path:
            trajectory_output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(trajectory_output_path, "w", encoding="utf-8") as f:
                json.dump(trajectory_data, f, ensure_ascii=False, indent=2)
            tracking_summary["trajectory_output"] = str(trajectory_output_path)
            print(f"轨迹 JSON: {trajectory_output_path}")

    result = {
        "video": str(video_path),
        "model": model_path.name,
        "confidence_threshold": confidence_threshold,
        "tracking_enabled": track,
        "video_info": {
            "width": width,
            "height": height,
            "fps": round(fps, 2),
            "total_frames": total_frames,
            "processed_frames": processed_frames,
            "duration_seconds": round(total_frames / fps, 2) if fps > 0 else 0,
        },
        "detection_summary": {
            "total_objects_detected": sum(class_stats.values()),
            "frames_with_detections": sum(1 for f in frame_results if f["object_count"] > 0),
            "frames_without_detections": sum(1 for f in frame_results if f["object_count"] == 0),
            "detection_rate": round(
                sum(1 for f in frame_results if f["object_count"] > 0) / max(processed_frames, 1), 4
            ),
        },
        "class_stats": class_summary,
        "tracking_summary": tracking_summary,
        "processing_time_seconds": round(elapsed, 2),
        "avg_fps": round(processed_frames / elapsed, 2) if elapsed > 0 else 0,
        "frames": frame_results,
    }

    # 保存 JSON
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"{video_path.stem}_detection.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\nJSON 报告: {json_path}")
        if save_video:
            print(f"检测视频: {output_dir / (video_path.stem + '_detected.mp4')}")

    # 打印摘要
    print(f"\n--- 检测摘要 ---")
    print(f"处理帧数: {processed_frames}/{total_frames}")
    print(f"检测到目标总数: {result['detection_summary']['total_objects_detected']}")
    print(f"有目标的帧: {result['detection_summary']['frames_with_detections']} ({result['detection_summary']['detection_rate']*100:.1f}%)")
    print(f"处理时间: {elapsed:.2f}s ({result['avg_fps']} fps)")
    print(f"\n类别统计:")
    for cs in class_summary:
        print(f"  {cs['class']:20s}: {cs['total_detections']:4d} 次 | 平均置信度 {cs['avg_confidence']:.3f}")
    if track and tracking_summary:
        print(f"\n跟踪统计:")
        print(f"  总轨迹数: {tracking_summary['total_tracks']}")
        for cls, cnt in tracking_summary["tracks_by_class"].items():
            print(f"    {cls}: {cnt} 条轨迹")

    return result


def main():
    args = parse_args()

    if not args.video and not args.batch:
        print("错误: 必须指定 --video 或 --batch")
        return

    model_path = args.model.resolve()
    if not model_path.is_file():
        print(f"错误: 模型文件不存在: {model_path}")
        return

    # 批量检测
    if args.batch:
        batch_dir = args.batch.resolve()
        if not batch_dir.is_dir():
            print(f"错误: 文件夹不存在: {batch_dir}")
            return

        video_exts = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv"}
        videos = [f for f in batch_dir.iterdir() if f.suffix.lower() in video_exts]

        if not videos:
            print(f"错误: 文件夹内没有视频文件: {batch_dir}")
            return

        print(f"批量检测: 共 {len(videos)} 个视频")
        all_results = []
        for i, video in enumerate(sorted(videos), 1):
            print(f"\n[{i}/{len(videos)}]")
            try:
                result = detect_video(
                    video_path=video,
                    model_path=model_path,
                    confidence_threshold=args.conf,
                    output_dir=args.output,
                    skip_frames=args.skip_frames,
                    save_video=not args.no_save_video,
                )
                all_results.append({
                    "video": str(video),
                    "summary": result["detection_summary"],
                    "class_stats": result["class_stats"],
                })
            except Exception as e:
                print(f"失败: {e}")
                all_results.append({"video": str(video), "error": str(e)})

        # 保存批量汇总
        if args.output:
            args.output.mkdir(parents=True, exist_ok=True)
            summary_path = args.output / "batch_summary.json"
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(all_results, f, ensure_ascii=False, indent=2)
            print(f"\n\n批量汇总: {summary_path}")

    # 单个视频
    else:
        video_path = args.video.resolve()
        if not video_path.is_file():
            print(f"错误: 视频文件不存在: {video_path}")
            return

        trajectory_path = None
        if args.track and args.trajectory_output:
            trajectory_path = args.trajectory_output.resolve()
        elif args.track and args.output:
            trajectory_path = args.output / f"{video_path.stem}_trajectory.json"

        detect_video(
            video_path=video_path,
            model_path=model_path,
            confidence_threshold=args.conf,
            output_dir=args.output,
            skip_frames=args.skip_frames,
            save_video=not args.no_save_video,
            track=args.track,
            trajectory_output_path=trajectory_path,
        )


if __name__ == "__main__":
    main()
