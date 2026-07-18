"""Filesystem-backed job persistence with strict path validation."""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


JOB_ID_PATTERN = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{8}$")
VALID_STATUSES = frozenset({"created", "queued", "running", "completed", "failed"})
BUSY_STATUSES = frozenset({"queued", "running"})


class InvalidJobIdError(ValueError):
    """Raised when a job id does not match the public format."""


class JobNotFoundError(FileNotFoundError):
    """Raised when a job directory or metadata file does not exist."""


class JobStateConflictError(RuntimeError):
    """Raised when a job state forbids an operation."""


class CorruptDataError(RuntimeError):
    """Raised when persisted JSON cannot be read safely."""


def iso_now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


class JobService:
    def __init__(self, outputs_dir: Path) -> None:
        self.outputs_dir = Path(outputs_dir)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def is_valid_job_id(job_id: str) -> bool:
        return bool(JOB_ID_PATTERN.fullmatch(job_id))

    def validate_job_id(self, job_id: str) -> None:
        if not self.is_valid_job_id(job_id):
            raise InvalidJobIdError("job_id 格式不合法")

    def job_dir(self, job_id: str) -> Path:
        self.validate_job_id(job_id)
        root = self.outputs_dir.resolve()
        target = (root / job_id).resolve()
        if target.parent != root:
            raise InvalidJobIdError("job_id 对应路径不安全")
        return target

    def reserve_workspace(self) -> tuple[str, Path]:
        with self._lock:
            for _ in range(20):
                job_id = (
                    f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
                    f"{secrets.token_hex(4)}"
                )
                target = self.job_dir(job_id)
                try:
                    target.mkdir(parents=False, exist_ok=False)
                except FileExistsError:
                    continue
                (target / "input").mkdir()
                (target / "keyframes").mkdir()
                (target / "result").mkdir()
                return job_id, target
        raise RuntimeError("无法生成唯一任务编号")

    def discard_workspace(self, job_id: str) -> None:
        """Remove a just-created incomplete workspace after upload failure."""

        with self._lock:
            target = self.job_dir(job_id)
            if target.exists():
                shutil.rmtree(target)

    def create_job_record(
        self,
        job_id: str,
        project_name: str,
        asset_name: str,
        settings: Mapping[str, Any],
    ) -> dict[str, Any]:
        target = self.job_dir(job_id)
        if not target.is_dir():
            raise JobNotFoundError("任务工作目录不存在")
        now = iso_now()
        job = {
            "job_id": job_id,
            "project_name": project_name,
            "asset_name": asset_name,
            "status": "created",
            "created_at": now,
            "started_at": None,
            "completed_at": None,
            "updated_at": now,
            "settings": dict(settings),
            "result_file": None,
            "rough_cut_file": None,
            "error": None,
        }
        self._write_json(target / "job.json", job)
        return job

    def _write_json(self, destination: Path, data: Mapping[str, Any]) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        with self._lock:
            try:
                with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                    json.dump(data, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)

    def _read_json(self, source: Path, label: str) -> dict[str, Any]:
        try:
            with source.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except FileNotFoundError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CorruptDataError(f"{label} 已损坏，无法读取") from exc
        if not isinstance(value, dict):
            raise CorruptDataError(f"{label} 顶层结构必须是 JSON 对象")
        return value

    def get_job(self, job_id: str) -> dict[str, Any]:
        job_file = self.job_dir(job_id) / "job.json"
        if not job_file.is_file():
            raise JobNotFoundError("任务不存在")
        with self._lock:
            return self._read_json(job_file, "job.json")

    def get_job_detail(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        target = self.job_dir(job_id)
        job["report_available"] = (target / "analysis_report.json").is_file()
        result_dir = target / "result"
        job["result_files"] = [
            path.relative_to(target).as_posix()
            for path in sorted(result_dir.iterdir())
            if path.is_file()
        ]
        return job

    def list_jobs(self) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        for target in self.outputs_dir.iterdir():
            if not target.is_dir() or not self.is_valid_job_id(target.name):
                continue
            try:
                jobs.append(self.get_job(target.name))
            except (JobNotFoundError, CorruptDataError):
                continue
        jobs.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return jobs

    def update_job(self, job_id: str, **changes: Any) -> dict[str, Any]:
        if "status" in changes and changes["status"] not in VALID_STATUSES:
            raise ValueError("任务状态不合法")
        with self._lock:
            job = self.get_job(job_id)
            job.update(changes)
            job["updated_at"] = iso_now()
            self._write_json(self.job_dir(job_id) / "job.json", job)
            return job

    def queue_for_analysis(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self.get_job(job_id)
            status = job.get("status")
            if status in BUSY_STATUSES:
                raise JobStateConflictError("任务已在排队或分析中")
            if status == "completed":
                raise JobStateConflictError("已完成任务暂不支持重复分析")
            return self.update_job(
                job_id,
                status="queued",
                started_at=None,
                completed_at=None,
                result_file=None,
                error=None,
            )

    def mark_running(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self.get_job(job_id)
            if job.get("status") != "queued":
                raise JobStateConflictError("只有 queued 任务可以开始运行")
            return self.update_job(
                job_id,
                status="running",
                started_at=iso_now(),
                completed_at=None,
                error=None,
            )

    def mark_completed(self, job_id: str, result_file: str) -> dict[str, Any]:
        return self.update_job(
            job_id,
            status="completed",
            completed_at=iso_now(),
            result_file=result_file,
            error=None,
        )

    def mark_failed(self, job_id: str, error: str) -> dict[str, Any]:
        return self.update_job(
            job_id,
            status="failed",
            completed_at=iso_now(),
            error=error,
        )

    def get_input_video(self, job_id: str) -> Path:
        job = self.get_job(job_id)
        candidate = self.job_dir(job_id) / "input" / str(job.get("asset_name", ""))
        if not candidate.is_file():
            raise JobNotFoundError("任务输入视频不存在")
        return candidate

    def report_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "analysis_report.json"

    def read_report(self, job_id: str) -> dict[str, Any]:
        self.get_job(job_id)
        path = self.report_path(job_id)
        if not path.is_file():
            raise JobNotFoundError("分析报告不存在")
        with self._lock:
            return self._read_json(path, "analysis_report.json")

    def write_report(self, job_id: str, report: Mapping[str, Any]) -> None:
        self.get_job(job_id)
        self._write_json(self.report_path(job_id), report)

    def update_report(
        self,
        job_id: str,
        updater: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        with self._lock:
            report = self.read_report(job_id)
            updated = updater(report)
            updated["updated_at"] = iso_now()
            self._write_json(self.report_path(job_id), updated)
            return updated

    def delete_job(self, job_id: str) -> None:
        with self._lock:
            job = self.get_job(job_id)
            if job.get("status") in BUSY_STATUSES:
                raise JobStateConflictError("queued 或 running 任务不能删除")
            target = self.job_dir(job_id)
            if target.parent != self.outputs_dir.resolve():
                raise InvalidJobIdError("任务路径不安全")
            shutil.rmtree(target)

    def recover_interrupted_jobs(self) -> int:
        """Mark jobs left busy by a previous process as failed."""

        recovered = 0
        for job in self.list_jobs():
            if job.get("status") in BUSY_STATUSES:
                self.mark_failed(
                    str(job["job_id"]),
                    "服务重启导致后台分析任务中断，请重新发起分析",
                )
                recovered += 1
        return recovered
