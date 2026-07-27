from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cv_engine.candidate_selector import (  # noqa: E402
    calculate_activity,
    select_candidate_windows,
)
from cv_engine.video_processor import VideoProcessor  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark ReelFire's two-stage video sampling pipeline."
    )
    parser.add_argument("video", type=Path)
    parser.add_argument("--coarse-interval", type=float, default=2.0)
    parser.add_argument("--sample-interval", type=float, default=0.5)
    parser.add_argument("--coverage-ratio", type=float, default=0.25)
    parser.add_argument("--window-duration", type=float, default=16.0)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.video.is_file():
        raise FileNotFoundError(args.video)

    processor = VideoProcessor()
    video = processor.get_video_info(args.video)
    duration = float(video["duration"])
    coarse_interval = max(args.coarse_interval, duration / 1800.0)

    started = time.perf_counter()
    coarse_samples = []
    previous = None
    for chunk in processor.iter_sample_chunks(
        args.video,
        interval=coarse_interval,
        chunk_duration=60.0,
        max_width=320,
    ):
        for frame, timestamp in zip(chunk["frames"], chunk["timestamps"]):
            coarse_samples.append(
                {
                    "timestamp": timestamp,
                    **calculate_activity(frame, previous),
                }
            )
            previous = frame
    screening_seconds = time.perf_counter() - started

    windows = select_candidate_windows(
        coarse_samples,
        duration,
        coverage_ratio=args.coverage_ratio,
        window_duration=args.window_duration,
    )
    candidate_duration = sum(
        float(window["end"]) - float(window["start"])
        for window in windows
    )

    decode_started = time.perf_counter()
    candidate_frame_count = 0
    for chunk in processor.iter_sample_windows(
        args.video,
        windows,
        interval=args.sample_interval,
        max_width=640,
    ):
        candidate_frame_count += len(chunk["frames"])
    candidate_decode_seconds = time.perf_counter() - decode_started

    payload = {
        "video_duration_seconds": round(duration, 3),
        "coarse_interval_seconds": round(coarse_interval, 3),
        "coarse_sample_count": len(coarse_samples),
        "screening_seconds": round(screening_seconds, 3),
        "candidate_window_count": len(windows),
        "candidate_duration_seconds": round(candidate_duration, 3),
        "candidate_coverage_ratio": round(candidate_duration / duration, 4),
        "candidate_sample_count": candidate_frame_count,
        "candidate_decode_seconds": round(candidate_decode_seconds, 3),
        "total_decode_seconds": round(
            screening_seconds + candidate_decode_seconds,
            3,
        ),
        "original_full_scan_samples": math.ceil(duration / args.sample_interval),
        "windows": windows,
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
