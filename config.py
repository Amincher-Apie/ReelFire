"""Day08 Flask service configuration."""

from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


class Config:
    """Default configuration for the first backend release."""

    BASE_DIR = BASE_DIR
    OUTPUTS_DIR = BASE_DIR / "outputs"
    MODELS_DIR = BASE_DIR / "models"
    MODEL_PATH = Path(
        os.environ.get("DAY08_MODEL_PATH", str(MODELS_DIR / "yolo11n.pt"))
    )
    ALLOWED_VIDEO_EXTENSIONS = frozenset({".mp4", ".avi", ".mov", ".mkv"})
    ALLOWED_OUTPUT_RATIOS = frozenset({"16:9", "9:16", "1:1"})
    MAX_CONTENT_LENGTH = 512 * 1024 * 1024
    HOST = "127.0.0.1"
    PORT = 7880
    BACKGROUND_WORKERS = 2
    DEFAULT_PROJECT_NAME = "智能视频精彩片段提取"
    DEFAULT_JOB_SETTINGS = {
        "sample_interval": 1.0,
        "target_duration": 15.0,
        "max_keyframes": 5,
        "min_keyframe_gap": 3.0,
        "object_weight": 0.45,
        "scene_change_weight": 0.35,
        "motion_weight": 0.20,
        "output_ratio": "16:9",
    }
    JSON_SORT_KEYS = False
