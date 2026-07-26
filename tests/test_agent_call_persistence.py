from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from database import get_db
from services.agent_call_service import (
    AgentCallStateConflictError,
    AgentCallValidationError,
    complete_agent_call,
    fail_agent_call,
    get_agent_call,
    mark_agent_call_running,
)
from services.agent_execution_service import AgentExecutionService


class FakeAnalysisService:
    def shutdown(self, wait: bool = False) -> None:
        del wait


def fake_analysis_service_factory(*_args) -> FakeAnalysisService:
    return FakeAnalysisService()


class FakeAgentExecutionService:
    def __init__(self) -> None:
        self.enqueued: list[tuple[int, str, str]] = []

    def enqueue(
        self,
        agent_call_id: int,
        job_id: str,
        *,
        prompt_version: str,
    ) -> None:
        self.enqueued.append((agent_call_id, job_id, prompt_version))

    def shutdown(self, wait: bool = False) -> None:
        del wait


def fake_agent_execution_service_factory(*_args) -> FakeAgentExecutionService:
    return FakeAgentExecutionService()


class AgentCallPersistenceTestCase(unittest.TestCase):
    MINIMAL_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.outputs_dir = self.root / "outputs"
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.root / "test.db",
                "SECRET_KEY": "test-secret-key",
                "LEGACY_USERS_FILE": self.root / "legacy-users.db",
                "OUTPUTS_DIR": self.outputs_dir,
                "MODELS_DIR": self.root / "models",
                "MODEL_PATH": self.root / "models" / "missing.pt",
                "BACKGROUND_WORKERS": 1,
                "ANALYSIS_SERVICE_FACTORY": fake_analysis_service_factory,
                "AGENT_EXECUTION_SERVICE_FACTORY": (
                    fake_agent_execution_service_factory
                ),
            }
        )
        self.owner = self.app.test_client()
        self.other = self.app.test_client()
        self.anonymous = self.app.test_client()
        self.owner_user = self._register(self.owner, "agent-owner")
        self._register(self.other, "agent-other")
        self.project = self._create_project()
        self.job_id = self._upload_project_job()
        self.jobs = self.app.extensions["job_service"]
        self._make_report_ready(self.job_id)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _register(self, client, username: str) -> dict:
        response = client.post(
            "/api/auth/register",
            json={"username": username, "password": "test-passphrase"},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["user"]

    def _create_project(self) -> dict:
        response = self.owner.post(
            "/api/projects",
            json={"name": "Agent Project"},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["project"]

    def _upload_project_job(self) -> str:
        response = self.owner.post(
            "/api/jobs",
            data={
                "file": (io.BytesIO(self.MINIMAL_MP4), "demo.mp4"),
                "project_id": str(self.project["id"]),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["job_id"]

    def _upload_legacy_job(self) -> str:
        response = self.owner.post(
            "/api/jobs",
            data={
                "file": (io.BytesIO(self.MINIMAL_MP4), "legacy.mp4"),
                "project_name": "Legacy",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["job_id"]

    def _make_report_ready(self, job_id: str) -> None:
        jobs = self.app.extensions["job_service"]
        jobs.write_report(
            job_id,
            {
                "duration": 10.0,
                "segments": [],
                "keyframes": [],
                "output": {},
            },
        )
        jobs.update_job(
            job_id,
            status="completed",
            completed_at="2026-07-25T12:00:00",
        )

    def _create_call(self, prompt_version: str = "v1") -> dict:
        response = self.owner.post(
            f"/api/jobs/{self.job_id}/agent-calls",
            json={"prompt_version": prompt_version, "force": False},
        )
        self.assertEqual(response.status_code, 202, response.get_json())
        return response.get_json()["agent_call"]

    def _call_count(self) -> int:
        with self.app.app_context():
            row = get_db().execute(
                "SELECT COUNT(*) AS count FROM agent_calls"
            ).fetchone()
            return int(row["count"])

    def test_owner_creates_real_queued_log_with_internal_relationship(self) -> None:
        report_before = self.jobs.report_path(self.job_id).read_bytes()
        created = self._create_call(" prompt-v1 ")

        self.assertEqual(created["job_id"], self.job_id)
        self.assertEqual(created["status"], "queued")
        self.assertEqual(created["prompt_version"], "prompt-v1")
        self.assertIsNone(created["completed_at"])
        self.assertNotIn("job_row_id", created)
        self.assertNotIn("public_job_id", created)
        self.assertEqual(
            self.app.extensions["agent_execution_service"].enqueued,
            [(created["id"], self.job_id, "prompt-v1")],
        )
        with self.app.app_context():
            row = get_db().execute(
                """
                SELECT
                    agent_calls.job_row_id,
                    agent_calls.requested_by,
                    jobs.id AS expected_job_row_id
                FROM agent_calls
                JOIN jobs ON jobs.id = agent_calls.job_row_id
                WHERE agent_calls.id = ?
                """,
                (created["id"],),
            ).fetchone()
        self.assertEqual(row["job_row_id"], row["expected_job_row_id"])
        self.assertEqual(row["requested_by"], self.owner_user["id"])
        self.assertEqual(
            self.jobs.report_path(self.job_id).read_bytes(),
            report_before,
        )

    def test_real_executor_runs_report_and_persists_editor_comment(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures" / "cv_analysis_report_v1.json"
        report = json.loads(fixture_path.read_text(encoding="utf-8"))
        report["job_id"] = self.job_id
        self.jobs.write_report(self.job_id, report)
        created = self._create_call("v2")
        executor = AgentExecutionService(
            self.app,
            self.jobs,
            max_workers=1,
            provider="rule_only",
        )
        try:
            with patch.dict(os.environ, {"OLLAMA_EMBED_MODEL": ""}):
                executor.enqueue(
                    created["id"],
                    self.job_id,
                    prompt_version="v2",
                )
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    with self.app.app_context():
                        current = get_agent_call(created["id"])
                    if current["status"] in {
                        "completed",
                        "needs_review",
                        "failed",
                    }:
                        break
                    time.sleep(0.01)
        finally:
            executor.shutdown()

        self.assertIn(current["status"], {"completed", "needs_review"})
        self.assertTrue(self.jobs.agent_report_path(self.job_id).is_file())
        editor = self.owner.get(f"/api/jobs/{self.job_id}/editor")
        self.assertEqual(editor.status_code, 200, editor.get_json())
        highlights = editor.get_json()["highlights"]
        self.assertEqual(highlights[0]["agent_comment_status"], "ready")
        self.assertIn(
            highlights[0]["agent_review_status"],
            {"pass", "needs_review", "reject"},
        )

    def test_create_input_validation_is_stable(self) -> None:
        invalid_payloads = (
            None,
            {},
            {"prompt_version": None},
            {"prompt_version": 1},
            {"prompt_version": ""},
            {"prompt_version": "x" * 101},
            {"prompt_version": "v1", "force": "false"},
            {"prompt_version": "v1", "unknown": True},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.owner.post(
                    f"/api/jobs/{self.job_id}/agent-calls",
                    json=payload,
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.get_json()["error_code"],
                    "AGENT_CALL_INPUT_INVALID",
                )
        self.assertEqual(self._call_count(), 0)

    def test_report_and_completed_state_are_required(self) -> None:
        missing_report_job = self._upload_project_job()
        self.jobs.update_job(
            missing_report_job,
            status="completed",
            completed_at="2026-07-25T12:00:00",
        )
        missing_report = self.owner.post(
            f"/api/jobs/{missing_report_job}/agent-calls",
            json={"prompt_version": "v1"},
        )

        not_completed_job = self._upload_project_job()
        self.jobs.write_report(
            not_completed_job,
            {"duration": 1.0, "segments": [], "keyframes": []},
        )
        not_completed = self.owner.post(
            f"/api/jobs/{not_completed_job}/agent-calls",
            json={"prompt_version": "v1"},
        )

        for response in (missing_report, not_completed):
            self.assertEqual(response.status_code, 409)
            self.assertEqual(
                response.get_json()["error_code"],
                "REPORT_NOT_READY",
            )
        self.assertEqual(self._call_count(), 0)

    def test_active_call_blocks_duplicate_even_when_force_is_true(self) -> None:
        created = self._create_call()
        queued_conflict = self.owner.post(
            f"/api/jobs/{self.job_id}/agent-calls",
            json={"prompt_version": "v2", "force": True},
        )
        with self.app.app_context():
            mark_agent_call_running(created["id"])
        running_conflict = self.owner.post(
            f"/api/jobs/{self.job_id}/agent-calls",
            json={"prompt_version": "v3", "force": False},
        )

        for response in (queued_conflict, running_conflict):
            self.assertEqual(response.status_code, 409)
            self.assertEqual(
                response.get_json()["error_code"],
                "AGENT_ALREADY_RUNNING",
            )
        self.assertEqual(self._call_count(), 1)

    def test_running_completes_with_structured_json_and_cannot_change_again(self) -> None:
        created = self._create_call()
        with self.app.app_context():
            running = mark_agent_call_running(
                created["id"],
                model_name="configured-model",
                input_summary="读取真实 CV 报告",
            )
            completed = complete_agent_call(
                created["id"],
                status="completed",
                model_name=None,
                output_summary="真实结构化结果",
                tool_trace=[{"tool": "report_parser", "ok": True}],
                references=[{"knowledge_id": "knowledge-001"}],
                result={"review_status": "approved", "comment": "人工仍需独立确认"},
                duration_ms=1200,
            )
            with self.assertRaises(AgentCallStateConflictError):
                mark_agent_call_running(created["id"])
            with self.assertRaises(AgentCallStateConflictError):
                fail_agent_call(
                    created["id"],
                    error_code="LATE_FAILURE",
                    error_message="不得覆盖终态",
                )

        self.assertEqual(running["status"], "running")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["model_name"], "configured-model")
        self.assertIsInstance(completed["tool_trace"], list)
        self.assertIsInstance(completed["references"], list)
        self.assertIsInstance(completed["result"], dict)
        self.assertEqual(completed["duration_ms"], 1200)
        self.assertIsNone(completed["error_code"])

    def test_completed_call_result_is_not_an_editor_comment_source(self) -> None:
        self.jobs.write_report(
            self.job_id,
            {
                "duration": 10.0,
                "segments": [
                    {
                        "id": "seg_001",
                        "start": 2.0,
                        "end": 7.5,
                        "score": 0.91,
                        "source_keyframes": [],
                        "order": 1,
                    }
                ],
                "keyframes": [],
                "recommended_clip": {
                    "start_time": 2.0,
                    "end_time": 7.5,
                    "output_ratio": "16:9",
                },
                "output": {
                    "video": None,
                    "contact_sheet": None,
                },
            },
        )
        agent_report_path = self.jobs.job_dir(self.job_id) / "agent_report.json"
        self.assertFalse(agent_report_path.exists())

        created = self._create_call()
        log_comment = "调用日志中的评论不得直接展示"
        with self.app.app_context():
            mark_agent_call_running(created["id"])
            complete_agent_call(
                created["id"],
                status="completed",
                model_name="configured-model",
                output_summary="调用已完成，但没有生成 Editor Agent 报告",
                tool_trace=[],
                references=[],
                result={
                    "segment_comments": [
                        {
                            "segment_id": "seg_001",
                            "comment": log_comment,
                        }
                    ]
                },
                duration_ms=10,
            )

        response = self.owner.get(f"/api/jobs/{self.job_id}/editor")

        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertEqual(payload["contract_version"], "1.0")
        self.assertEqual(
            payload["highlights"][0]["agent_comment_status"],
            "pending",
        )
        self.assertIsNone(payload["highlights"][0]["agent_comment"])
        self.assertNotIn(log_comment, response.get_data(as_text=True))
        self.assertFalse(agent_report_path.exists())

    def test_needs_review_and_failed_terminal_states_preserve_real_data(self) -> None:
        needs_review_id = self._create_call()["id"]
        with self.app.app_context():
            mark_agent_call_running(needs_review_id)
            needs_review = complete_agent_call(
                needs_review_id,
                status="needs_review",
                model_name="configured-model",
                output_summary="知识命中不足，需要人工确认",
                tool_trace=[],
                references=[{"knowledge_id": "knowledge-002"}],
                result={"review_status": "pending"},
                duration_ms=800,
            )

        queued_failed_id = self._create_call()["id"]
        with self.app.app_context():
            queued_failed = fail_agent_call(
                queued_failed_id,
                error_code="QUEUE_ABORTED",
                error_message="调用在执行前取消",
                duration_ms=0,
                tool_trace=[],
            )

        running_failed_id = self._create_call()["id"]
        with self.app.app_context():
            mark_agent_call_running(running_failed_id)
            running_failed = fail_agent_call(
                running_failed_id,
                error_code="MODEL_TIMEOUT",
                error_message="模型调用超时",
                duration_ms=1200,
                tool_trace=[{"tool": "retriever", "status": "completed"}],
            )

        self.assertEqual(needs_review["status"], "needs_review")
        self.assertEqual(needs_review["result"]["review_status"], "pending")
        self.assertEqual(queued_failed["status"], "failed")
        self.assertEqual(running_failed["status"], "failed")
        self.assertEqual(running_failed["error_code"], "MODEL_TIMEOUT")
        self.assertEqual(len(running_failed["tool_trace"]), 1)
        self.assertIsNone(running_failed["result"])

    def test_service_rejects_invalid_transition_payloads(self) -> None:
        created = self._create_call()
        with self.app.app_context():
            with self.assertRaises(AgentCallStateConflictError):
                complete_agent_call(
                    created["id"],
                    status="completed",
                    model_name=None,
                    output_summary=None,
                    tool_trace=[],
                    references=[],
                    result={},
                    duration_ms=1,
                )
            with self.assertRaises(AgentCallValidationError):
                mark_agent_call_running(
                    created["id"],
                    model_name="x" * 201,
                )
            mark_agent_call_running(created["id"])
            invalid_completions = (
                {"tool_trace": None},
                {"tool_trace": [None] * 101},
                {"references": None},
                {"result": []},
                {"duration_ms": True},
                {"duration_ms": -1},
                {"output_summary": "x" * 4001},
            )
            defaults = {
                "status": "completed",
                "model_name": None,
                "output_summary": None,
                "tool_trace": [],
                "references": [],
                "result": {},
                "duration_ms": 1,
            }
            for changes in invalid_completions:
                with self.subTest(changes=changes):
                    with self.assertRaises(AgentCallValidationError):
                        complete_agent_call(
                            created["id"],
                            **{**defaults, **changes},
                        )
            with self.assertRaises(AgentCallValidationError):
                fail_agent_call(
                    created["id"],
                    error_code="",
                    error_message="failure",
                )

    def test_history_detail_permissions_and_ordering(self) -> None:
        first_id = self._create_call()["id"]
        with self.app.app_context():
            fail_agent_call(
                first_id,
                error_code="FIRST_FAILURE",
                error_message="first",
            )
        second_id = self._create_call("v2")["id"]

        history = self.owner.get(
            f"/api/jobs/{self.job_id}/agent-calls"
        )
        detail = self.owner.get(f"/api/agent-calls/{first_id}")
        missing = self.owner.get("/api/agent-calls/999999")
        invalid = self.owner.get("/api/agent-calls/0")

        self.assertEqual(
            [item["id"] for item in history.get_json()["agent_calls"]],
            [second_id, first_id],
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.get_json()["agent_call"]["job_id"], self.job_id)
        self.assertNotIn("job_row_id", detail.get_json()["agent_call"])
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(
            missing.get_json()["error_code"],
            "AGENT_CALL_NOT_FOUND",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(
            invalid.get_json()["error_code"],
            "AGENT_CALL_INPUT_INVALID",
        )

        for client, expected_status, expected_code in (
            (self.other, 403, "JOB_ACCESS_DENIED"),
            (self.anonymous, 401, "AUTH_REQUIRED"),
        ):
            denied_history = client.get(
                f"/api/jobs/{self.job_id}/agent-calls"
            )
            denied_detail = client.get(f"/api/agent-calls/{first_id}")
            for response in (denied_history, denied_detail):
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(
                    response.get_json()["error_code"],
                    expected_code,
                )

    def test_anonymous_create_and_authenticated_legacy_behavior(self) -> None:
        anonymous_create = self.anonymous.post(
            f"/api/jobs/{self.job_id}/agent-calls",
            json={"prompt_version": "v1"},
        )
        other_create = self.other.post(
            f"/api/jobs/{self.job_id}/agent-calls",
            json={"prompt_version": "v1"},
        )
        legacy_id = self._upload_legacy_job()
        legacy_create = self.owner.post(
            f"/api/jobs/{legacy_id}/agent-calls",
            json={"prompt_version": "v1"},
        )
        legacy_history = self.owner.get(
            f"/api/jobs/{legacy_id}/agent-calls"
        )

        self.assertEqual(anonymous_create.status_code, 401)
        self.assertEqual(
            anonymous_create.get_json()["error_code"],
            "AUTH_REQUIRED",
        )
        self.assertEqual(other_create.status_code, 403)
        self.assertEqual(
            other_create.get_json()["error_code"],
            "JOB_ACCESS_DENIED",
        )
        self.assertEqual(legacy_create.status_code, 409)
        self.assertEqual(
            legacy_create.get_json()["error_code"],
            "AGENT_CALL_PERSISTENCE_UNAVAILABLE",
        )
        self.assertEqual(
            legacy_history.get_json(),
            {"ok": True, "agent_calls": []},
        )
        self.assertEqual(self._call_count(), 0)

    def test_database_failures_rollback_without_touching_reports_or_reviews(self) -> None:
        review_response = self.owner.patch(
            f"/api/jobs/{self.job_id}/review",
            json={"status": "approved", "note": "人工确认"},
        )
        self.assertEqual(review_response.status_code, 200)
        report_before = self.jobs.report_path(self.job_id).read_bytes()
        with self.app.app_context():
            review_before = [
                tuple(row)
                for row in get_db().execute(
                    "SELECT * FROM reviews ORDER BY id"
                ).fetchall()
            ]
            get_db().execute(
                """
                CREATE TRIGGER reject_agent_insert
                BEFORE INSERT ON agent_calls
                BEGIN
                    SELECT RAISE(ABORT, 'forced Agent insert failure');
                END
                """
            )
            get_db().commit()

        failed_create = self.owner.post(
            f"/api/jobs/{self.job_id}/agent-calls",
            json={"prompt_version": "v1"},
        )
        self.assertEqual(failed_create.status_code, 500)
        self.assertEqual(self._call_count(), 0)

        with self.app.app_context():
            get_db().execute("DROP TRIGGER reject_agent_insert")
            get_db().commit()
        created = self._create_call()
        with self.app.app_context():
            get_db().execute(
                """
                CREATE TRIGGER reject_agent_update
                BEFORE UPDATE ON agent_calls
                BEGIN
                    SELECT RAISE(ABORT, 'forced Agent update failure');
                END
                """
            )
            get_db().commit()
            with self.assertRaises(sqlite3.IntegrityError):
                mark_agent_call_running(created["id"])
            unchanged = get_agent_call(created["id"])
            review_after = [
                tuple(row)
                for row in get_db().execute(
                    "SELECT * FROM reviews ORDER BY id"
                ).fetchall()
            ]

        self.assertEqual(unchanged["status"], "queued")
        self.assertEqual(
            self.jobs.report_path(self.job_id).read_bytes(),
            report_before,
        )
        self.assertEqual(review_after, review_before)


if __name__ == "__main__":
    unittest.main()
