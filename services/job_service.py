"""Filesystem-backed job persistence with strict path validation."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import threading
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from services.job_index_service import JobIndexRepository


logger = logging.getLogger(__name__)


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


class JobPersistenceConsistencyError(RuntimeError):
    """Raised when file and SQLite task persistence cannot stay consistent."""


class JobCleanupPendingError(JobPersistenceConsistencyError):
    """Raised after database deletion succeeds but tombstone cleanup fails."""


def iso_now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


class JobService:
    TOMBSTONE_PATTERN = re.compile(
        r"^\.delete-(\d{8}_\d{6}_[0-9a-f]{8})-([0-9a-f]{32})$"
    )

    def __init__(
        self,
        outputs_dir: Path,
        index_repository: JobIndexRepository | None = None,
    ) -> None:
        self.outputs_dir = Path(outputs_dir)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.index_repository = index_repository
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
        *,
        project_id: int | None = None,
        game_type: str | None = None,
        original_asset_name: str | None = None,
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
            "error_code": None,
        }
        if project_id is not None:
            job["project_id"] = project_id
        if game_type is not None:
            job["game_type"] = game_type
        if original_asset_name is not None:
            job["original_asset_name"] = original_asset_name
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

    def _restore_bytes(self, destination: Path, content: bytes | None) -> None:
        if content is None:
            destination.unlink(missing_ok=True)
            return
        temporary = destination.with_name(
            f".{destination.name}.{uuid4().hex}.restore"
        )
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _rough_cut_path(
        self,
        job_id: str,
        job: Mapping[str, Any],
    ) -> Path | None:
        value = job.get("rough_cut_file")
        if not isinstance(value, str) or not value.strip():
            return None
        root = self.job_dir(job_id).resolve()
        candidate = (root / value).resolve()
        if root not in candidate.parents or not candidate.is_file():
            return None
        return candidate

    def _sync_index(
        self,
        job_id: str,
        job: dict[str, Any],
    ) -> bool:
        project_id = job.get("project_id")
        is_project_job = (
            isinstance(project_id, int)
            and not isinstance(project_id, bool)
            and project_id > 0
        )
        if not is_project_job:
            return False
        if self.index_repository is None:
            raise JobPersistenceConsistencyError(
                "项目型任务缺少 SQLite 索引仓库"
            )
        report_path = self.report_path(job_id)
        synchronized = self.index_repository.sync_job(
            job_id,
            job,
            job_json_path=self.job_dir(job_id) / "job.json",
            report_json_path=report_path if report_path.is_file() else None,
            rough_cut_path=self._rough_cut_path(job_id, job),
        )
        if not synchronized:
            raise JobPersistenceConsistencyError(
                "项目型任务对应的 SQLite jobs 索引不存在"
            )
        return True

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
        job["progress"] = self.read_progress(job_id)
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
            previous = self.get_job(job_id)
            updated = dict(previous)
            updated.update(changes)
            updated["updated_at"] = iso_now()
            destination = self.job_dir(job_id) / "job.json"
            self._write_json(destination, updated)
            try:
                self._sync_index(job_id, updated)
            except Exception as exc:
                try:
                    self._write_json(destination, previous)
                except Exception as restore_exc:
                    raise JobPersistenceConsistencyError(
                        "任务文件与 SQLite 索引同步失败，且任务文件恢复失败"
                    ) from restore_exc
                raise JobPersistenceConsistencyError(
                    "SQLite 任务索引同步失败，任务文件已恢复"
                ) from exc
            return updated

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
                error_code=None,
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
                error_code=None,
            )

    def mark_completed(self, job_id: str, result_file: str) -> dict[str, Any]:
        return self.update_job(
            job_id,
            status="completed",
            completed_at=iso_now(),
            result_file=result_file,
            error=None,
            error_code=None,
        )

    def mark_failed(
        self,
        job_id: str,
        error: str,
        error_code: str = "ANALYSIS_FAILED",
    ) -> dict[str, Any]:
        return self.update_job(
            job_id,
            status="failed",
            completed_at=iso_now(),
            error=error,
            error_code=error_code,
        )

    def get_input_video(self, job_id: str) -> Path:
        job = self.get_job(job_id)
        candidate = self.job_dir(job_id) / "input" / str(job.get("asset_name", ""))
        if not candidate.is_file():
            raise JobNotFoundError("任务输入视频不存在")
        return candidate

    def report_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "analysis_report.json"

    def progress_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "analysis_progress.json"

    def read_progress(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        path = self.progress_path(job_id)
        if path.is_file():
            with self._lock:
                return self._read_json(path, "analysis_progress.json")
        status = str(job.get("status", "created"))
        return {
            "stage": status,
            "message": "等待分析" if status == "created" else "",
            "percent": 100.0 if status == "completed" else 0.0,
            "total_chunks": 0,
            "completed_chunks": 0,
            "processed_frames": 0,
            "total_frames": 0,
            "current_chunk": None,
            "chunks": [],
            "updated_at": job.get("updated_at"),
        }

    def write_progress(
        self,
        job_id: str,
        progress: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.get_job(job_id)
        value = dict(progress)
        value["updated_at"] = iso_now()
        self._write_json(self.progress_path(job_id), value)
        return value

    def read_report(self, job_id: str) -> dict[str, Any]:
        self.get_job(job_id)
        path = self.report_path(job_id)
        if not path.is_file():
            raise JobNotFoundError("分析报告不存在")
        with self._lock:
            return self._read_json(path, "analysis_report.json")

    def write_report(self, job_id: str, report: Mapping[str, Any]) -> None:
        job = self.get_job(job_id)
        destination = self.report_path(job_id)
        previous = destination.read_bytes() if destination.is_file() else None
        self._write_json(destination, report)
        try:
            self._sync_index(job_id, job)
        except Exception as exc:
            try:
                self._restore_bytes(destination, previous)
            except Exception as restore_exc:
                raise JobPersistenceConsistencyError(
                    "报告与 SQLite 索引同步失败，且报告文件恢复失败"
                ) from restore_exc
            raise JobPersistenceConsistencyError(
                "SQLite 报告索引同步失败，报告文件已恢复"
            ) from exc

    def agent_report_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "agent_report.json"

    def read_agent_report(self, job_id: str) -> dict[str, Any]:
        self.get_job(job_id)
        path = self.agent_report_path(job_id)
        if not path.is_file():
            raise JobNotFoundError("Agent 报告不存在")
        with self._lock:
            return self._read_json(path, "agent_report.json")

    def write_agent_report(self, job_id: str, report: Mapping[str, Any]) -> None:
        self.get_job(job_id)
        self._write_json(self.agent_report_path(job_id), report)

    def update_report(
        self,
        job_id: str,
        updater: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        with self._lock:
            report = self.read_report(job_id)
            updated = updater(report)
            updated["updated_at"] = iso_now()
            self.write_report(job_id, updated)
            return updated

    def delete_job(self, job_id: str) -> None:
        with self._lock:
            job = self.get_job(job_id)
            if job.get("status") in BUSY_STATUSES:
                raise JobStateConflictError("queued 或 running 任务不能删除")
            target = self.job_dir(job_id)
            if target.parent != self.outputs_dir.resolve():
                raise InvalidJobIdError("任务路径不安全")
            tombstone = self.outputs_dir / (
                f".delete-{job_id}-{uuid4().hex}"
            )
            if not self.TOMBSTONE_PATTERN.fullmatch(tombstone.name):
                raise InvalidJobIdError("任务删除暂存路径不安全")
            os.replace(target, tombstone)
            try:
                if self.index_repository is not None:
                    deleted = self.index_repository.delete_job_index(job_id)
                    project_id = job.get("project_id")
                    is_project_job = (
                        isinstance(project_id, int)
                        and not isinstance(project_id, bool)
                        and project_id > 0
                    )
                    if is_project_job and not deleted:
                        raise JobPersistenceConsistencyError(
                            "项目型任务对应的 SQLite jobs 索引不存在，"
                            "已取消文件删除"
                        )
                elif (
                    isinstance(job.get("project_id"), int)
                    and not isinstance(job.get("project_id"), bool)
                    and int(job["project_id"]) > 0
                ):
                    raise JobPersistenceConsistencyError(
                        "项目型任务缺少 SQLite 索引仓库，已取消文件删除"
                    )
            except Exception as exc:
                try:
                    os.replace(tombstone, target)
                except OSError as restore_exc:
                    raise JobPersistenceConsistencyError(
                        "SQLite 删除失败，且任务目录恢复失败"
                    ) from restore_exc
                raise JobPersistenceConsistencyError(
                    "SQLite 删除失败，任务目录已恢复"
                ) from exc
            try:
                shutil.rmtree(tombstone)
            except OSError as exc:
                raise JobCleanupPendingError(
                    "任务索引已删除，目录清理待应用启动时重试"
                ) from exc

    def cleanup_delete_tombstones(self) -> int:
        cleaned = 0
        with self._lock:
            for candidate in self.outputs_dir.iterdir():
                match = self.TOMBSTONE_PATTERN.fullmatch(candidate.name)
                if not candidate.is_dir() or match is None:
                    continue
                job_id = match.group(1)
                normal_directory = self.job_dir(job_id)
                if self.index_repository is None:
                    logger.warning(
                        "无法判断删除暂存目录 %s 的数据库状态，已保留",
                        candidate.name,
                    )
                    continue
                try:
                    indexed = self.index_repository.has_job_index(job_id)
                except Exception:
                    logger.warning(
                        "读取任务 %s 的 SQLite 索引失败，删除暂存目录已保留",
                        job_id,
                        exc_info=True,
                    )
                    continue

                normal_exists = normal_directory.exists()
                if indexed and not normal_exists:
                    try:
                        os.replace(candidate, normal_directory)
                    except OSError:
                        logger.warning(
                            "任务 %s 的删除暂存目录恢复失败，已保留待处理",
                            job_id,
                            exc_info=True,
                        )
                        continue
                    logger.warning(
                        "任务 %s 的 SQLite 索引仍存在，已从删除暂存目录"
                        "恢复正常工作目录",
                        job_id,
                    )
                    cleaned += 1
                    continue

                if not indexed and not normal_exists:
                    try:
                        shutil.rmtree(candidate)
                    except OSError:
                        logger.warning(
                            "任务 %s 的已提交删除暂存目录清理失败，"
                            "保留供后续启动重试",
                            job_id,
                            exc_info=True,
                        )
                        continue
                    cleaned += 1
                    continue

                logger.warning(
                    "任务 %s 的删除暂存状态不明确"
                    "（SQLite 索引=%s，正常目录=%s），"
                    "为避免数据丢失已保留暂存目录",
                    job_id,
                    indexed,
                    normal_exists,
                )
        return cleaned

    def reconcile_job_indexes(self) -> int:
        """Repair SQLite mirrors for already-indexed project jobs only."""

        if self.index_repository is None:
            return 0
        repaired = 0
        for row in self.index_repository.list_indexed_jobs():
            job_id = str(row["public_job_id"])
            try:
                target = self.job_dir(job_id)
                job_file = target / "job.json"
                if not target.is_dir() or not job_file.is_file():
                    raise JobNotFoundError("任务工作目录或 job.json 不存在")
                job = self.get_job(job_id)
                self._sync_index(job_id, job)
            except (InvalidJobIdError, JobNotFoundError, CorruptDataError):
                self.index_repository.mark_missing_workspace_failed(
                    job_id,
                    "任务工作目录或 job.json 缺失，索引已标记为 failed",
                )
            repaired += 1
        return repaired

    def recover_interrupted_jobs(self) -> int:
        """Mark jobs left busy by a previous process as failed."""

        recovered = 0
        for job in self.list_jobs():
            if job.get("status") in BUSY_STATUSES:
                self.mark_failed(
                    str(job["job_id"]),
                    "服务重启导致后台分析任务中断，请重新发起分析",
                    "INTERRUPTED_BY_RESTART",
                )
                recovered += 1
        return recovered
