"""Controlled background execution and the future CV integration point."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from services.job_service import JobService, JobStateConflictError, iso_now


LOGGER = logging.getLogger(__name__)


def analyze_video(
    video_path: Path,
    job_dir: Path,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Analyze one video and return a JSON-serializable report.

    The CV engineer should replace this body with real OpenCV sampling, YOLO
    inference and explainable highlight scoring. No synthetic report is emitted.
    """

    del video_path, job_dir, settings
    raise NotImplementedError(
        "CV 分析模块尚未接入，请由算法工程师实现 analyze_video"
    )


class AnalysisService:
    def __init__(self, jobs: JobService, max_workers: int = 2) -> None:
        self.jobs = jobs
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)),
            thread_name_prefix="day08-analysis",
        )
        self._active: set[str] = set()
        self._active_lock = threading.Lock()

    def enqueue(self, job_id: str) -> None:
        with self._active_lock:
            if job_id in self._active:
                raise JobStateConflictError("任务已在排队或分析中")
            self.jobs.queue_for_analysis(job_id)
            self._active.add(job_id)
        try:
            self._executor.submit(self._run, job_id)
        except RuntimeError as exc:
            with self._active_lock:
                self._active.discard(job_id)
            self.jobs.mark_failed(job_id, "后台任务调度器不可用")
            raise RuntimeError("后台任务调度器不可用") from exc

    def _run(self, job_id: str) -> None:
        try:
            job = self.jobs.mark_running(job_id)
            video_path = self.jobs.get_input_video(job_id)
            job_dir = self.jobs.job_dir(job_id)
            report = analyze_video(video_path, job_dir, dict(job["settings"]))
            if not isinstance(report, dict):
                raise TypeError("analyze_video 必须返回 JSON 对象")
            report.setdefault("job_id", job_id)
            report["updated_at"] = iso_now()
            self.jobs.write_report(job_id, report)
            self.jobs.mark_completed(job_id, "analysis_report.json")
        except Exception as exc:  # Background boundary: persist every expected failure.
            message = str(exc).strip() or exc.__class__.__name__
            try:
                self.jobs.mark_failed(job_id, message)
            except Exception:
                # Preserve process availability, but never hide persistence failures.
                LOGGER.exception("无法把后台分析失败状态写回任务 %s", job_id)
        finally:
            with self._active_lock:
                self._active.discard(job_id)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)
