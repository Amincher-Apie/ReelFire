from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from app import create_app
from services.agent_call_service import (
    fail_agent_call,
    get_agent_call,
    list_agent_calls,
    mark_agent_call_running,
    recover_interrupted_agent_calls,
)
from services.agent_execution_service import (
    AgentExecutionService,
    AgentExecutionUnavailableError,
)


class FakeAnalysisService:
    def shutdown(self, wait: bool = False) -> None:
        del wait


def fake_analysis_service_factory(*_args) -> FakeAnalysisService:
    return FakeAnalysisService()


class RecordingExecutionService:
    def __init__(self) -> None:
        self.enqueued = []

    def enqueue(self, agent_call_id, job_id, *, prompt_version):
        self.enqueued.append((agent_call_id, job_id, prompt_version))

    def shutdown(self, wait: bool = False) -> None:
        del wait


def recording_execution_factory(*_args) -> RecordingExecutionService:
    return RecordingExecutionService()


class RejectingExecutionService(RecordingExecutionService):
    def enqueue(self, *_args, **_kwargs):
        raise AgentExecutionUnavailableError("executor stopped")


class FakeWorkflow:
    def __init__(
        self,
        *,
        status: str = "completed",
        output_mode: str = "both",
        raises: Exception | None = None,
        marker: str = "new",
    ) -> None:
        self.status = status
        self.output_mode = output_mode
        self.raises = raises
        self.marker = marker
        self.inputs = []

    def run_analysis_report(
        self,
        analysis_report,
        *,
        provider,
        output_dir=None,
    ):
        if self.raises is not None:
            raise self.raises
        self.inputs.append(analysis_report)
        job_id = analysis_report["job_id"]
        segment_id = str(analysis_report["segments"][0]["id"])
        result_job_id = (
            "wrong-job"
            if self.output_mode == "wrong_job"
            else job_id
        )
        recommendation = (
            "needs_review"
            if self.status == "degraded"
            else "pass"
        )
        errors = (
            [{"code": "FAKE_FAILED", "message": "fake failure"}]
            if self.status == "failed"
            else []
        )
        result = {
            "schema_version": "1.0",
            "job_id": result_job_id,
            "status": self.status,
            "provider": {
                "type": provider["type"],
                "model": provider["model"],
            },
            "summary": self.marker,
            "tags": [],
            "suggestions": [],
            "segment_comments": [
                {
                    "segment_id": segment_id,
                    "comment": f"comment-{self.marker}",
                    "review_status": recommendation,
                    "evidence_refs": [f"segment:{segment_id}"],
                }
            ],
            "review": {
                "recommendation": recommendation,
                "confidence": 0.8,
                "reasons": [],
            },
            "knowledge_refs": [],
            "trace": {
                "duration_ms": 5,
                "tools": [],
            },
            "errors": errors,
        }
        if output_dir is None:
            return result
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        if self.output_mode == "invalid_json":
            (output_dir / "agent_report.json").write_text(
                "{",
                encoding="utf-8",
            )
        else:
            (output_dir / "agent_report.json").write_text(
                json.dumps(result),
                encoding="utf-8",
            )
        if self.output_mode not in {"missing_trace", "invalid_json"}:
            trace = {
                "job_id": result_job_id,
                "status": self.status,
                "provider": result["provider"],
                "trace": result["trace"],
                "errors": errors,
                "marker": self.marker,
            }
            (output_dir / "agent_trace.json").write_text(
                json.dumps(trace),
                encoding="utf-8",
            )
        return result


class AgentExecutionReliabilityTestCase(unittest.TestCase):
    MINIMAL_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = {
            "TESTING": True,
            "DATABASE": self.root / "test.db",
            "SECRET_KEY": "test-secret",
            "LEGACY_USERS_FILE": self.root / "legacy.db",
            "OUTPUTS_DIR": self.root / "outputs",
            "MODELS_DIR": self.root / "models",
            "MODEL_PATH": self.root / "models" / "missing.pt",
            "BACKGROUND_WORKERS": 1,
            "ANALYSIS_SERVICE_FACTORY": fake_analysis_service_factory,
            "AGENT_EXECUTION_SERVICE_FACTORY": (
                recording_execution_factory
            ),
        }
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        user = self.client.post(
            "/api/auth/register",
            json={"username": "runtime-owner", "password": "test-passphrase"},
        ).get_json()["user"]
        self.user_id = int(user["id"])
        project = self.client.post(
            "/api/projects",
            json={"name": "Runtime"},
        ).get_json()["project"]
        upload = self.client.post(
            "/api/jobs",
            data={
                "file": (io.BytesIO(self.MINIMAL_MP4), "demo.mp4"),
                "project_id": str(project["id"]),
            },
            content_type="multipart/form-data",
        )
        self.job_id = upload.get_json()["job_id"]
        self.jobs = self.app.extensions["job_service"]
        fixture = (
            Path(__file__).parent
            / "fixtures"
            / "cv_analysis_report_v1.json"
        )
        report = json.loads(fixture.read_text(encoding="utf-8"))
        report["job_id"] = self.job_id
        self.jobs.write_report(self.job_id, report)
        self.jobs.update_job(
            self.job_id,
            status="completed",
            completed_at="2026-07-26T00:00:00",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _new_call(self, prompt_version: str = "v2") -> dict:
        response = self.client.post(
            f"/api/jobs/{self.job_id}/agent-calls",
            json={"prompt_version": prompt_version, "force": False},
        )
        self.assertEqual(response.status_code, 202, response.get_json())
        return response.get_json()["agent_call"]

    def _run(self, workflow: FakeWorkflow, call: dict | None = None):
        call = call or self._new_call()
        service = AgentExecutionService(
            self.app,
            self.jobs,
            workflow_factory=lambda: (
                workflow,
                {"type": "rule_only", "model": "fake-model"},
            ),
        )
        future = service.enqueue(
            call["id"],
            self.job_id,
            prompt_version=call["prompt_version"],
        )
        future.result(timeout=3)
        service.shutdown()
        with self.app.app_context():
            return get_agent_call(call["id"])

    def _write_old_pair(self) -> tuple[bytes, bytes]:
        job_dir = self.jobs.job_dir(self.job_id)
        report = json.dumps(
            {"job_id": self.job_id, "marker": "old"}
        ).encode()
        trace = json.dumps(
            {"job_id": self.job_id, "marker": "old"}
        ).encode()
        (job_dir / "agent_report.json").write_bytes(report)
        (job_dir / "agent_trace.json").write_bytes(trace)
        return report, trace

    def _assert_no_temporary_agent_files(self) -> None:
        job_dir = self.jobs.job_dir(self.job_id)
        runs = job_dir / ".agent_runs"
        self.assertFalse(runs.exists())
        self.assertFalse(
            any(".previous-" in path.name for path in job_dir.rglob("*"))
        )

    def test_completed_publishes_pair_and_preserves_analysis_bytes(self) -> None:
        before = self.jobs.report_path(self.job_id).read_bytes()
        current = self._run(FakeWorkflow(marker="complete"))
        job_dir = self.jobs.job_dir(self.job_id)

        self.assertEqual(current["status"], "completed")
        self.assertEqual(
            json.loads(
                (job_dir / "agent_report.json").read_text(encoding="utf-8")
            )["summary"],
            "complete",
        )
        self.assertEqual(
            json.loads(
                (job_dir / "agent_trace.json").read_text(encoding="utf-8")
            )["marker"],
            "complete",
        )
        self.assertEqual(
            self.jobs.report_path(self.job_id).read_bytes(),
            before,
        )
        self._assert_no_temporary_agent_files()

    def test_degraded_maps_to_needs_review(self) -> None:
        current = self._run(FakeWorkflow(status="degraded"))
        self.assertEqual(current["status"], "needs_review")

    def test_failed_and_exception_keep_old_pair(self) -> None:
        for workflow in (
            FakeWorkflow(status="failed"),
            FakeWorkflow(
                raises=RuntimeError(
                    r"D:\Workspace\secret\report.json token=hidden"
                )
            ),
        ):
            with self.subTest(workflow=workflow.raises or workflow.status):
                old_report, old_trace = self._write_old_pair()
                current = self._run(workflow)
                job_dir = self.jobs.job_dir(self.job_id)
                self.assertEqual(current["status"], "failed")
                self.assertEqual(
                    (job_dir / "agent_report.json").read_bytes(),
                    old_report,
                )
                self.assertEqual(
                    (job_dir / "agent_trace.json").read_bytes(),
                    old_trace,
                )
                self.assertNotIn(
                    "Workspace",
                    current["error_message"],
                )
                self.assertNotIn("token", current["error_message"].lower())
                self._assert_no_temporary_agent_files()

    def test_corrupt_analysis_report_fails_without_rewriting_it(self) -> None:
        corrupted = b"{not-json"
        self.jobs.report_path(self.job_id).write_bytes(corrupted)
        current = self._run(FakeWorkflow())
        self.assertEqual(current["status"], "failed")
        self.assertEqual(current["error_code"], "AGENT_REPORT_INVALID")
        self.assertEqual(
            self.jobs.report_path(self.job_id).read_bytes(),
            corrupted,
        )

    def test_invalid_staging_outputs_never_replace_old_pair(self) -> None:
        for mode in ("missing_trace", "invalid_json", "wrong_job"):
            with self.subTest(mode=mode):
                old_report, old_trace = self._write_old_pair()
                current = self._run(FakeWorkflow(output_mode=mode))
                job_dir = self.jobs.job_dir(self.job_id)
                self.assertEqual(current["status"], "failed")
                self.assertEqual(
                    current["error_code"],
                    "AGENT_OUTPUT_INVALID",
                )
                self.assertEqual(
                    (job_dir / "agent_report.json").read_bytes(),
                    old_report,
                )
                self.assertEqual(
                    (job_dir / "agent_trace.json").read_bytes(),
                    old_trace,
                )
                self._assert_no_temporary_agent_files()

    def test_database_completion_failure_restores_old_pair(self) -> None:
        old_report, old_trace = self._write_old_pair()
        with patch(
            "services.agent_execution_service.complete_agent_call",
            side_effect=sqlite3.OperationalError("forced completion failure"),
        ):
            current = self._run(FakeWorkflow(marker="not-published"))
        job_dir = self.jobs.job_dir(self.job_id)
        self.assertEqual(current["status"], "failed")
        self.assertEqual(
            (job_dir / "agent_report.json").read_bytes(),
            old_report,
        )
        self.assertEqual(
            (job_dir / "agent_trace.json").read_bytes(),
            old_trace,
        )
        self._assert_no_temporary_agent_files()

    def test_database_completion_failure_removes_new_pair_without_old(self) -> None:
        job_dir = self.jobs.job_dir(self.job_id)
        with patch(
            "services.agent_execution_service.complete_agent_call",
            side_effect=sqlite3.OperationalError("forced completion failure"),
        ):
            current = self._run(FakeWorkflow())
        self.assertEqual(current["status"], "failed")
        self.assertFalse((job_dir / "agent_report.json").exists())
        self.assertFalse((job_dir / "agent_trace.json").exists())
        self._assert_no_temporary_agent_files()

    def test_second_publish_failure_restores_complete_old_pair(self) -> None:
        old_report, old_trace = self._write_old_pair()
        real_replace = os.replace

        def fail_staged_trace(source, destination):
            source_path = Path(source)
            destination_path = Path(destination)
            if (
                source_path.name == "agent_trace.json"
                and source_path.parent.parent.name == ".agent_runs"
                and destination_path.name == "agent_trace.json"
            ):
                raise OSError("forced second publish failure")
            return real_replace(source, destination)

        with patch(
            "services.agent_execution_service.os.replace",
            side_effect=fail_staged_trace,
        ):
            current = self._run(FakeWorkflow(marker="partial"))
        job_dir = self.jobs.job_dir(self.job_id)
        self.assertEqual(current["status"], "failed")
        self.assertEqual(
            (job_dir / "agent_report.json").read_bytes(),
            old_report,
        )
        self.assertEqual(
            (job_dir / "agent_trace.json").read_bytes(),
            old_trace,
        )
        self._assert_no_temporary_agent_files()

    def test_restore_failure_preserves_backups_and_reports_safe_failure(
        self,
    ) -> None:
        old_report, old_trace = self._write_old_pair()
        real_replace = os.replace

        def fail_publish_and_restore(source, destination):
            source_path = Path(source)
            destination_path = Path(destination)
            if source_path.name.startswith(".previous-"):
                raise OSError(
                    rf"forced restore failure at {destination_path}"
                )
            if (
                source_path.name == "agent_trace.json"
                and source_path.parent.parent.name == ".agent_runs"
                and destination_path.name == "agent_trace.json"
            ):
                raise OSError("forced second publish failure")
            return real_replace(source, destination)

        with patch(
            "services.agent_execution_service.os.replace",
            side_effect=fail_publish_and_restore,
        ):
            current = self._run(FakeWorkflow(marker="unrestored"))

        runs_dir = self.jobs.job_dir(self.job_id) / ".agent_runs"
        staging_dirs = list(runs_dir.iterdir())
        self.assertEqual(current["status"], "failed")
        self.assertEqual(
            current["error_code"],
            "AGENT_FILE_RECOVERY_FAILED",
        )
        self.assertNotIn(
            str(self.jobs.job_dir(self.job_id)),
            current["error_message"],
        )
        self.assertNotIn(
            "Workspace",
            current["error_message"],
        )
        self.assertEqual(len(staging_dirs), 1)
        self.assertEqual(
            (
                staging_dirs[0] / ".previous-agent_report.json"
            ).read_bytes(),
            old_report,
        )
        self.assertEqual(
            (
                staging_dirs[0] / ".previous-agent_trace.json"
            ).read_bytes(),
            old_trace,
        )

    def test_submit_failure_returns_503_and_fails_queued_row(self) -> None:
        self.app.extensions[
            "agent_execution_service"
        ] = RejectingExecutionService()
        response = self.client.post(
            f"/api/jobs/{self.job_id}/agent-calls",
            json={"prompt_version": "v2"},
        )
        self.assertEqual(response.status_code, 503, response.get_json())
        self.assertEqual(
            response.get_json()["error_code"],
            "AGENT_EXECUTION_UNAVAILABLE",
        )
        with self.app.app_context():
            row = list_agent_calls(self.job_id)[0]
        self.assertEqual(row["status"], "failed")
        self.assertEqual(
            row["error_code"],
            "AGENT_EXECUTION_UNAVAILABLE",
        )

    def test_shutdown_rejects_enqueue_and_is_idempotent(self) -> None:
        service = AgentExecutionService(self.app, self.jobs)
        service.shutdown(wait=False)
        service.shutdown(wait=False)
        with self.assertRaises(AgentExecutionUnavailableError):
            service.enqueue(999, self.job_id, prompt_version="v2")
        self.assertEqual(service._active, set())

    def test_error_sanitization_hides_windows_unix_and_credentials(self) -> None:
        fallback = "Agent 执行失败，请重新运行"
        messages = (
            r"failed at D:\Workspace\private\report.json",
            "failed at /srv/reelfire/private/report.json",
            "Authorization: Bearer abc",
            "DIFY_API_KEY=secret",
        )
        for message in messages:
            with self.subTest(message=message):
                self.assertEqual(
                    AgentExecutionService._safe_error(RuntimeError(message)),
                    fallback,
                )

    def test_recovery_fails_active_only_and_allows_new_call(self) -> None:
        first = self._new_call()
        with self.app.app_context():
            recovered = recover_interrupted_agent_calls()
            failed = get_agent_call(first["id"])
        self.assertEqual(recovered, 1)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(
            failed["error_code"],
            "AGENT_PROCESS_INTERRUPTED",
        )
        second = self._new_call()
        with self.app.app_context():
            mark_agent_call_running(second["id"])
            recovered = recover_interrupted_agent_calls()
            failed_running = get_agent_call(second["id"])
        self.assertEqual(recovered, 1)
        self.assertEqual(failed_running["status"], "failed")
        third = self._new_call()
        with self.app.app_context():
            fail_agent_call(
                third["id"],
                error_code="EXPECTED",
                error_message="terminal",
            )
            recovered = recover_interrupted_agent_calls()
            terminal = get_agent_call(third["id"])
        self.assertEqual(recovered, 0)
        self.assertEqual(terminal["error_code"], "EXPECTED")

    def test_recovery_rolls_back_on_database_failure(self) -> None:
        queued = self._new_call()
        with self.app.app_context():
            from database import get_db

            connection = get_db()
            connection.execute(
                """
                CREATE TRIGGER reject_agent_recovery
                BEFORE UPDATE ON agent_calls
                WHEN NEW.error_code = 'AGENT_PROCESS_INTERRUPTED'
                BEGIN
                    SELECT RAISE(ABORT, 'forced recovery failure');
                END
                """
            )
            connection.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                recover_interrupted_agent_calls()
            current = get_agent_call(queued["id"])
        self.assertEqual(current["status"], "queued")

    def test_application_startup_recovers_queued_call(self) -> None:
        queued = self._new_call()
        restarted = create_app(self.config)
        with restarted.app_context():
            recovered = get_agent_call(queued["id"])
        self.assertEqual(recovered["status"], "failed")
        self.assertEqual(
            recovered["error_code"],
            "AGENT_PROCESS_INTERRUPTED",
        )

    def test_rule_only_executes_without_provider_environment(self) -> None:
        call = self._new_call()
        service = AgentExecutionService(
            self.app,
            self.jobs,
            provider="rule_only",
        )
        with patch.dict(
            os.environ,
            {
                "OLLAMA_MODEL": "",
                "OLLAMA_EMBED_MODEL": "",
                "DIFY_API_KEY": "",
            },
        ):
            future = service.enqueue(
                call["id"],
                self.job_id,
                prompt_version="v2",
            )
            future.result(timeout=3)
        service.shutdown()
        with self.app.app_context():
            current = get_agent_call(call["id"])
        self.assertIn(current["status"], {"completed", "needs_review"})
        self.assertNotEqual(current["status"], "failed")

    def test_segment_queue_publishes_and_remaps_incremental_comment(self) -> None:
        report = self.jobs.read_report(self.job_id)
        segment = dict(report["segments"][0])
        segment["id"] = "seg_union_seg_c0001_01"
        segment["order"] = 1
        partial = {
            **report,
            "segments": [segment],
        }
        service = AgentExecutionService(
            self.app,
            self.jobs,
            provider="rule_only",
        )

        future = service.enqueue_segment(self.job_id, partial)
        self.assertIsNotNone(future)
        future.result(timeout=3)
        streamed = json.loads(
            self.jobs.agent_report_path(self.job_id).read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(streamed["streaming"])
        self.assertEqual(
            streamed["segment_comments"][0]["segment_id"],
            "seg_union_seg_c0001_01",
        )

        service.finalize_segments(
            self.job_id,
            [
                {
                    "id": "seg_001",
                    "agent_segment_id": "seg_union_seg_c0001_01",
                    "source_segment_ids": ["seg_c0001_01"],
                }
            ],
        )
        finalized = json.loads(
            self.jobs.agent_report_path(self.job_id).read_text(
                encoding="utf-8"
            )
        )
        service.shutdown()
        self.assertEqual(
            finalized["segment_comments"][0]["segment_id"],
            "seg_001",
        )

    def test_completed_report_retry_calls_agent_once_per_segment(self) -> None:
        report = self.jobs.read_report(self.job_id)
        second = deepcopy(report["segments"][0])
        second.update(
            {
                "id": "seg_002",
                "order": 2,
                "start": 12.0,
                "end": 18.0,
                "duration": 6.0,
                "source_keyframes": [],
            }
        )
        report["segments"].append(second)
        report["samples"].append(
            {
                "frame_index": 300,
                "timestamp": 12.5,
                "objects": [],
            }
        )
        self.jobs.write_report(self.job_id, report)
        workflow = FakeWorkflow(marker="segmented")

        current = self._run(workflow)

        self.assertEqual(current["status"], "completed")
        self.assertEqual(
            [
                [segment["id"] for segment in item["segments"]]
                for item in workflow.inputs
            ],
            [["seg_001"], ["seg_002"]],
        )
        self.assertTrue(
            all(len(item["segments"]) == 1 for item in workflow.inputs)
        )
        self.assertTrue(
            all(
                2.0 <= float(sample["timestamp"]) <= 10.0
                for sample in workflow.inputs[0]["samples"]
            )
        )
        self.assertEqual(
            [sample["timestamp"] for sample in workflow.inputs[1]["samples"]],
            [12.5],
        )
        published = self.jobs.read_agent_report(self.job_id)
        self.assertTrue(published["streaming"])
        self.assertEqual(published["completed_segment_count"], 2)
        self.assertEqual(
            {
                item["segment_id"]
                for item in published["segment_comments"]
            },
            {"seg_001", "seg_002"},
        )

    def test_unavailable_remote_providers_never_report_completed(self) -> None:
        cases = (
            (
                "ollama",
                {
                    "OLLAMA_MODEL": "",
                    "OLLAMA_EMBED_MODEL": "",
                },
            ),
            (
                "dify",
                {
                    "DIFY_API_KEY": "",
                    "OLLAMA_EMBED_MODEL": "",
                },
            ),
        )
        for provider, environment in cases:
            with self.subTest(provider=provider):
                call = self._new_call()
                service = AgentExecutionService(
                    self.app,
                    self.jobs,
                    provider=provider,
                )
                with patch.dict(os.environ, environment):
                    future = service.enqueue(
                        call["id"],
                        self.job_id,
                        prompt_version="v2",
                    )
                    future.result(timeout=3)
                service.shutdown()
                with self.app.app_context():
                    current = get_agent_call(call["id"])
                self.assertIn(
                    current["status"],
                    {"needs_review", "failed"},
                )


if __name__ == "__main__":
    unittest.main()
