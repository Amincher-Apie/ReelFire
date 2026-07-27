from __future__ import annotations

import copy
import io
import json
import math
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app import create_app
from database import get_db
from services.editor_input_validation import (
    EDITOR_SEGMENT_SCHEMA_VERSION,
    EditorSegmentValidationError,
    adapt_legacy_segments,
    merge_editor_segments,
    normalize_stored_editor_segments,
    validate_editor_segments,
)
from services.job_index_service import resolve_job_row_id


class FakeAnalysisService:
    def shutdown(self, wait: bool = False) -> None:
        del wait


def fake_analysis_service_factory(*_args) -> FakeAnalysisService:
    return FakeAnalysisService()


class FakeAgentExecutionService:
    def enqueue(self, *_args, **_kwargs) -> None:
        return None

    def shutdown(self, wait: bool = False) -> None:
        del wait


def fake_agent_execution_service_factory(
    *_args,
) -> FakeAgentExecutionService:
    return FakeAgentExecutionService()


def cv_segment(**changes) -> dict:
    segment = {
        "id": "seg_cv",
        "order": 1,
        "start": 1.0,
        "end": 4.0,
        "score": 0.8,
        "source_keyframes": ["kf_001"],
    }
    segment.update(changes)
    return segment


class EditorSegmentSchemaValidationTestCase(unittest.TestCase):
    def test_review_values_and_notes_normalize_as_frontend_contract(
        self,
    ) -> None:
        segments = [
            cv_segment(
                id=f"seg_{index}",
                order=index + 1,
                review=review,
                review_note=note,
            )
            for index, (review, note) in enumerate(
                (
                    ("", ""),
                    ("pass", " approved "),
                    ("needs_review", None),
                    ("reject", r" mentions C:\capture\clip.mp4 "),
                )
            )
        ]

        result = validate_editor_segments(segments, 10.0)

        self.assertEqual(
            [segment["review"] for segment in result],
            ["", "pass", "needs_review", "reject"],
        )
        self.assertEqual(
            [segment["review_note"] for segment in result],
            ["", "approved", "", r"mentions C:\capture\clip.mp4"],
        )

    def test_defaults_duration_order_and_input_immutability(self) -> None:
        source = [
            cv_segment(
                id="second",
                order=9,
                start=12.5,
                end=20.0,
                duration=999,
            ),
            cv_segment(
                id="first",
                order=2,
                source_keyframes=None,
            ),
        ]
        del source[1]["source_keyframes"]
        original = copy.deepcopy(source)

        result = validate_editor_segments(source, 20.0)

        self.assertEqual(source, original)
        self.assertEqual(
            [segment["id"] for segment in result],
            ["first", "second"],
        )
        self.assertEqual(
            [segment["order"] for segment in result],
            [1, 2],
        )
        self.assertEqual(result[0]["source_keyframes"], [])
        self.assertEqual(result[0]["source"], "cv")
        self.assertEqual(result[0]["source_segment_ids"], [])
        self.assertEqual(result[0]["review"], "")
        self.assertEqual(result[0]["review_note"], "")
        self.assertEqual(result[1]["duration"], 7.5)

    def test_sources_and_nullable_non_cv_scores(self) -> None:
        source = [
            cv_segment(id="cv", order=1, source="cv"),
            cv_segment(
                id="manual",
                order=2,
                source="manual",
                score=None,
            ),
            cv_segment(
                id="merged",
                order=3,
                source="merged",
                source_segment_ids=[" a ", "b"],
                score=None,
            ),
            cv_segment(
                id="split",
                order=4,
                source="split",
                source_segment_ids=["a"],
                score=None,
            ),
        ]

        result = validate_editor_segments(source, 10.0)

        self.assertEqual(
            [segment["source"] for segment in result],
            ["cv", "manual", "merged", "split"],
        )
        self.assertEqual(result[2]["source_segment_ids"], ["a", "b"])
        self.assertTrue(
            all(segment["score"] is None for segment in result[1:])
        )

    def test_unknown_client_fields_are_ignored(self) -> None:
        source = cv_segment(
            owner_id=1,
            reviewer_id=2,
            private_path=r"C:\private\report.json",
            api_key="secret",
            token="secret",
            arbitrary={"nested": True},
            detected_classes=["client-injected"],
            reason="client-injected",
        )
        original = copy.deepcopy(source)

        result = validate_editor_segments([source], 10.0)[0]

        self.assertEqual(source, original)
        for field in (
            "owner_id",
            "reviewer_id",
            "private_path",
            "api_key",
            "token",
            "arbitrary",
            "detected_classes",
            "reason",
        ):
            self.assertNotIn(field, result)

    def test_merge_preserves_all_server_extensions_and_blocks_forgery(
        self,
    ) -> None:
        existing = cv_segment(
            source="cv",
            source_segment_ids=[],
            review="reject",
            review_note="server decision",
            thumbnail="server-thumb.jpg",
            frame_count=24,
            max_confidence=0.97,
            avg_confidence=0.81,
            trigger_rule="server-rule",
            chunk_id="chunk-server",
            future_cv_field={"version": 2},
            detected_classes=["vehicle"],
            reason="server evidence",
        )
        patch_segment = cv_segment(
            review_note="",
            thumbnail="client-thumb.jpg",
            frame_count=999,
            max_confidence=0.01,
            avg_confidence=0.02,
            trigger_rule="client-rule",
            chunk_id="chunk-client",
            future_cv_field="client-value",
            reason="client injection",
            private_path=r"C:\private\client.json",
            owner_id=7,
            token="client-secret",
        )
        original_patch = copy.deepcopy(patch_segment)

        result = merge_editor_segments(
            [patch_segment],
            [existing],
            10.0,
        )[0]

        self.assertEqual(patch_segment, original_patch)
        self.assertEqual(result["review"], "reject")
        self.assertEqual(result["review_note"], "")
        self.assertEqual(result["source"], "cv")
        self.assertEqual(result["detected_classes"], ["vehicle"])
        self.assertEqual(result["reason"], "server evidence")
        expected_extensions = {
            "thumbnail": "server-thumb.jpg",
            "frame_count": 24,
            "max_confidence": 0.97,
            "avg_confidence": 0.81,
            "trigger_rule": "server-rule",
            "chunk_id": "chunk-server",
            "future_cv_field": {"version": 2},
        }
        for field, expected in expected_extensions.items():
            self.assertEqual(result[field], expected)
        for field in ("owner_id", "private_path", "token"):
            self.assertNotIn(field, result)

    def test_new_manual_segment_defaults_to_unreviewed(self) -> None:
        manual = cv_segment(
            id="seg_manual_new",
            source="manual",
            score=None,
            source_keyframes=[],
        )

        validated = validate_editor_segments([manual], 10.0)[0]
        merged = merge_editor_segments([manual], [], 10.0)[0]

        self.assertEqual(validated["review"], "")
        self.assertEqual(validated["review_note"], "")
        self.assertEqual(merged["review"], "")
        self.assertEqual(merged["review_note"], "")

    def test_invalid_reviews_and_frozen_fields_are_rejected(self) -> None:
        cases = {
            "old accepted": cv_segment(review="accepted"),
            "old ignored": cv_segment(review="ignored"),
            "old pending": cv_segment(review="pending"),
            "unknown review": cv_segment(review="approved"),
            "note object": cv_segment(review_note={"text": "bad"}),
            "note too long": cv_segment(review_note="x" * 501),
            "invalid source": cv_segment(source="generated"),
            "merged too few": cv_segment(
                source="merged",
                source_segment_ids=["old"],
            ),
            "split too many": cv_segment(
                source="split",
                source_segment_ids=["a", "b"],
            ),
            "cv source ids": cv_segment(
                source_segment_ids=["old"],
            ),
            "duplicate source ids": cv_segment(
                source="merged",
                source_segment_ids=["a", "a"],
            ),
            "self source id": cv_segment(
                id="self",
                source="split",
                source_segment_ids=["self"],
            ),
            "cv null score": cv_segment(score=None),
            "score above one": cv_segment(score=1.1),
            "score non-finite": cv_segment(score=math.inf),
            "bool start": cv_segment(start=True),
            "negative start": cv_segment(start=-1),
            "equal bounds": cv_segment(start=2, end=2),
            "end after duration": cv_segment(end=11),
        }
        for label, segment in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(EditorSegmentValidationError):
                    validate_editor_segments([segment], 10.0)

    def test_legacy_defaults_are_pass_and_empty_note(self) -> None:
        legacy = [
            {
                "id": "old",
                "order": 5,
                "start": 1.0,
                "end": 2.0,
                "score": 0.6,
                "source_keyframes": [],
            }
        ]

        result = adapt_legacy_segments(legacy, 10.0)[0]

        self.assertEqual(result["source"], "cv")
        self.assertEqual(result["source_segment_ids"], [])
        self.assertEqual(result["review"], "pass")
        self.assertEqual(result["review_note"], "")
        self.assertEqual(result["duration"], 1.0)
        self.assertEqual(result["order"], 1)

    def test_stored_nonlegacy_segment_missing_review_defaults_to_pass(
        self,
    ) -> None:
        stored = cv_segment(id="stored")

        result = normalize_stored_editor_segments(
            [stored],
            10.0,
        )[0]

        self.assertEqual(result["review"], "pass")
        self.assertEqual(result["review_note"], "")


class EditorSegmentSchemaApiTestCase(unittest.TestCase):
    MINIMAL_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.root / "test.db",
                "SECRET_KEY": "schema-secret",
                "LEGACY_USERS_FILE": self.root / "legacy.db",
                "OUTPUTS_DIR": self.root / "outputs",
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
        self.owner_user = self._register(self.owner, "schema-owner")
        self._register(self.other, "schema-other")
        project = self.owner.post(
            "/api/projects",
            json={"name": "Schema Project"},
        ).get_json()["project"]
        upload = self.owner.post(
            "/api/jobs",
            data={
                "file": (io.BytesIO(self.MINIMAL_MP4), "schema.mp4"),
                "project_id": str(project["id"]),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(upload.status_code, 201, upload.get_json())
        self.job_id = upload.get_json()["job_id"]
        self.jobs = self.app.extensions["job_service"]
        self._write_old_report()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _register(self, client, username: str) -> dict:
        response = client.post(
            "/api/auth/register",
            json={"username": username, "password": "test-passphrase"},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["user"]

    def _write_old_report(self) -> None:
        self.jobs.write_report(
            self.job_id,
            {
                "duration": 30.0,
                "samples": [],
                "keyframes": [],
                "segments": [
                    cv_segment(
                        id="seg_a",
                        detected_classes=["vehicle"],
                        reason="server evidence",
                        thumbnail="server-thumb.jpg",
                        frame_count=24,
                        max_confidence=0.97,
                        avg_confidence=0.81,
                        trigger_rule="server-rule",
                        chunk_id="chunk-server",
                        future_cv_field={"version": 2},
                    )
                ],
                "recommended_clip": {
                    "start_time": 1.0,
                    "end_time": 4.0,
                    "output_ratio": "16:9",
                },
                "output": {},
            },
        )
        self.jobs.update_job(
            self.job_id,
            status="completed",
            completed_at="2026-07-27T00:00:00",
        )

    def _review_count(self) -> int:
        with self.app.app_context():
            row = get_db().execute(
                "SELECT COUNT(*) AS count FROM reviews"
            ).fetchone()
            return int(row["count"])

    def _get_editor(self):
        with patch(
            "routes.api_routes.ensure_browser_preview",
            side_effect=lambda source, *_args: Path(source).resolve(),
        ):
            return self.owner.get(f"/api/jobs/{self.job_id}/editor")

    @staticmethod
    def _export(_input, output, *_args):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"schema-export")
        return output.resolve()

    def test_old_report_editor_response_has_frontend_defaults(self) -> None:
        response = self._get_editor()

        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertEqual(
            payload["segment_schema_version"],
            EDITOR_SEGMENT_SCHEMA_VERSION,
        )
        segment = payload["highlights"][0]
        self.assertEqual(segment["review"], "pass")
        self.assertEqual(segment["review_note"], "")
        self.assertEqual(segment["source"], "cv")
        self.assertEqual(segment["source_segment_ids"], [])

    def test_long_video_editor_skips_synchronous_preview_transcode(self) -> None:
        report = self.jobs.read_report(self.job_id)
        report["duration"] = 1800.0
        self.jobs.write_report(self.job_id, report)

        with patch(
            "routes.api_routes.ensure_browser_preview",
        ) as preview:
            response = self.owner.get(f"/api/jobs/{self.job_id}/editor")

        self.assertEqual(response.status_code, 200, response.get_json())
        preview.assert_not_called()
        self.assertEqual(
            response.get_json()["video"]["preview_status"],
            "source_unverified",
        )

    def test_patch_inherits_reject_and_evidence_without_unknown_injection(
        self,
    ) -> None:
        first = cv_segment(
            id="seg_a",
            review="reject",
            review_note="duplicate candidate",
            owner_id=1,
            reviewer_id=2,
            private_path=r"C:\private\client.json",
            api_key="secret",
            token="secret",
            arbitrary="client",
            detected_classes=["client injection"],
            reason="client injection",
            thumbnail="client-thumb.jpg",
            frame_count=999,
            max_confidence=0.01,
            avg_confidence=0.02,
            trigger_rule="client-rule",
            chunk_id="chunk-client",
            future_cv_field="client-value",
        )
        first_response = self.owner.patch(
            f"/api/jobs/{self.job_id}/review",
            json={"segments": [first]},
        )
        self.assertEqual(
            first_response.status_code,
            200,
            first_response.get_json(),
        )

        frontend_approved = cv_segment(id="seg_a")
        approved_response = self.owner.patch(
            f"/api/jobs/{self.job_id}/review",
            json={
                "status": "approved",
                "segments": [frontend_approved],
            },
        )
        self.assertEqual(
            approved_response.status_code,
            200,
            approved_response.get_json(),
        )

        persisted = self.jobs.read_report(self.job_id)["segments"][0]
        latest = self.owner.get(
            f"/api/jobs/{self.job_id}/review/latest"
        ).get_json()["review"]["segments"][0]
        for segment in (persisted, latest):
            self.assertEqual(segment["review"], "reject")
            self.assertEqual(
                segment["review_note"],
                "duplicate candidate",
            )
            self.assertEqual(segment["detected_classes"], ["vehicle"])
            self.assertEqual(segment["reason"], "server evidence")
            expected_extensions = {
                "thumbnail": "server-thumb.jpg",
                "frame_count": 24,
                "max_confidence": 0.97,
                "avg_confidence": 0.81,
                "trigger_rule": "server-rule",
                "chunk_id": "chunk-server",
                "future_cv_field": {"version": 2},
            }
            for field, expected in expected_extensions.items():
                self.assertEqual(segment[field], expected)
            for field in (
                "owner_id",
                "reviewer_id",
                "private_path",
                "api_key",
                "token",
                "arbitrary",
            ):
                self.assertNotIn(field, segment)

        with (
            patch(
                "routes.api_routes.is_ffmpeg_available",
                return_value=True,
            ),
            patch(
                "routes.api_routes.create_multi_segment_rough_cut"
            ) as exporter,
        ):
            export_response = self.owner.post(
                f"/api/jobs/{self.job_id}/rough-cut",
                json={},
            )
        self.assertEqual(
            export_response.status_code,
            409,
            export_response.get_json(),
        )
        self.assertIn(
            (
                "\u6ca1\u6709\u5df2\u901a\u8fc7\u7684\u7247\u6bb5"
                "\u53ef\u4ee5\u5bfc\u51fa"
            ),
            export_response.get_json()["error"],
        )
        exporter.assert_not_called()

    def test_explicit_empty_review_and_note_clear_existing_values(
        self,
    ) -> None:
        first = self.owner.patch(
            f"/api/jobs/{self.job_id}/review",
            json={
                "segments": [
                    cv_segment(
                        id="seg_a",
                        review="pass",
                        review_note="keep this",
                    )
                ]
            },
        )
        self.assertEqual(first.status_code, 200, first.get_json())
        second = self.owner.patch(
            f"/api/jobs/{self.job_id}/review",
            json={
                "segments": [
                    cv_segment(
                        id="seg_a",
                        review="",
                        review_note="",
                    )
                ]
            },
        )

        self.assertEqual(second.status_code, 200, second.get_json())
        segment = self.jobs.read_report(self.job_id)["segments"][0]
        self.assertEqual(segment["review"], "")
        self.assertEqual(segment["review_note"], "")

    def test_export_uses_only_pass_segments_and_metadata(self) -> None:
        segments = [
            cv_segment(id="passed", order=1, review="pass"),
            cv_segment(
                id="manual_unreviewed",
                order=2,
                source="manual",
                score=None,
                source_keyframes=[],
            ),
            cv_segment(
                id="needs_review",
                order=3,
                review="needs_review",
            ),
            cv_segment(id="rejected", order=4, review="reject"),
        ]
        review = self.owner.patch(
            f"/api/jobs/{self.job_id}/review",
            json={"status": "approved", "segments": segments},
        )
        self.assertEqual(review.status_code, 200, review.get_json())
        captured: dict[str, object] = {}

        def export(input_path, output, selected, ratio):
            captured["segments"] = selected
            captured["ratio"] = ratio
            return self._export(input_path, output)

        with (
            patch(
                "routes.api_routes.is_ffmpeg_available",
                return_value=True,
            ),
            patch(
                "routes.api_routes.create_multi_segment_rough_cut",
                side_effect=export,
            ),
        ):
            response = self.owner.post(
                f"/api/jobs/{self.job_id}/rough-cut",
                json={},
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        selected = captured["segments"]
        self.assertEqual(
            [segment["id"] for segment in selected],  # type: ignore[union-attr]
            ["passed"],
        )
        self.assertEqual(response.get_json()["segment_count"], 1)
        self.assertEqual(response.get_json()["segment_ids"], ["passed"])
        persisted = self.jobs.read_report(self.job_id)["segments"]
        manual = next(
            segment
            for segment in persisted
            if segment["id"] == "manual_unreviewed"
        )
        self.assertEqual(manual["review"], "")
        output = self.jobs.read_report(self.job_id)["output"]
        self.assertEqual(output["segment_count"], 1)
        self.assertEqual(output["segment_ids"], ["passed"])

    def test_no_pass_is_saved_without_replacing_recommended_clip(
        self,
    ) -> None:
        recommended_before = copy.deepcopy(
            self.jobs.read_report(self.job_id)["recommended_clip"]
        )
        saved = self.owner.patch(
            f"/api/jobs/{self.job_id}/review",
            json={
                "status": "approved",
                "segments": [
                    cv_segment(id="empty", order=1, review=""),
                    cv_segment(
                        id="review",
                        order=2,
                        review="needs_review",
                    ),
                    cv_segment(id="reject", order=3, review="reject"),
                ],
            },
        )
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.assertEqual(
            self.jobs.read_report(self.job_id)["recommended_clip"],
            recommended_before,
        )

        with (
            patch(
                "routes.api_routes.is_ffmpeg_available",
                return_value=True,
            ),
            patch(
                "routes.api_routes.create_multi_segment_rough_cut"
            ) as exporter,
        ):
            response = self.owner.post(
                f"/api/jobs/{self.job_id}/rough-cut",
                json={},
            )
        self.assertEqual(response.status_code, 409, response.get_json())
        exporter.assert_not_called()

    def test_old_review_snapshot_defaults_to_pass_for_export(self) -> None:
        old_segment = cv_segment(id="old_snapshot", order=7)
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.app.app_context():
            job_row_id = resolve_job_row_id(self.job_id)
            get_db().execute(
                """
                INSERT INTO reviews (
                    job_row_id,
                    reviewer_id,
                    status,
                    labels_json,
                    note,
                    segments_json,
                    keyframes_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_row_id,
                    self.owner_user["id"],
                    "approved",
                    "[]",
                    None,
                    json.dumps([old_segment]),
                    None,
                    timestamp,
                    timestamp,
                ),
            )
            get_db().commit()
        captured: dict[str, object] = {}

        def export(input_path, output, selected, _ratio):
            captured["segments"] = selected
            return self._export(input_path, output)

        with (
            patch(
                "routes.api_routes.is_ffmpeg_available",
                return_value=True,
            ),
            patch(
                "routes.api_routes.create_multi_segment_rough_cut",
                side_effect=export,
            ),
        ):
            response = self.owner.post(
                f"/api/jobs/{self.job_id}/rough-cut",
                json={},
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        selected = captured["segments"][0]  # type: ignore[index]
        self.assertEqual(selected["review"], "pass")
        self.assertEqual(selected["review_note"], "")

    def test_report_data_allows_note_path_but_not_private_fields(
        self,
    ) -> None:
        response = self.owner.patch(
            f"/api/jobs/{self.job_id}/review",
            json={
                "status": "approved",
                "segments": [
                    cv_segment(
                        id="seg_a",
                        review="pass",
                        review_note=r"checked C:\capture\clip.mp4",
                        private_path=r"C:\private\secret.json",
                        owner_id=7,
                    )
                ],
            },
        )
        self.assertEqual(response.status_code, 200, response.get_json())

        report_data_response = self.owner.get(
            f"/api/jobs/{self.job_id}/report-data"
        )
        self.assertEqual(
            report_data_response.status_code,
            200,
            report_data_response.get_json(),
        )
        report_data = report_data_response.get_json()["report_data"]
        self.assertEqual(
            report_data["review"]["latest"]["segments"][0]["review_note"],
            r"checked C:\capture\clip.mp4",
        )
        serialized = json.dumps(report_data, ensure_ascii=False)
        self.assertNotIn("private_path", serialized)
        self.assertNotIn("owner_id", serialized)
        self.assertNotIn("secret.json", serialized)
        private_extensions = (
            "thumbnail",
            "frame_count",
            "max_confidence",
            "avg_confidence",
            "trigger_rule",
            "chunk_id",
            "future_cv_field",
        )
        public_segments = (
            report_data["cv"]["segments"][0],
            report_data["review"]["latest"]["segments"][0],
        )
        for segment in public_segments:
            for field in private_extensions:
                self.assertNotIn(field, segment)

    def test_permissions_and_invalid_schema_do_not_write(self) -> None:
        report_before = self.jobs.report_path(self.job_id).read_bytes()
        responses = [
            self.anonymous.patch(
                f"/api/jobs/{self.job_id}/review",
                json={"segments": [cv_segment()]},
            ),
            self.other.patch(
                f"/api/jobs/{self.job_id}/review",
                json={"segments": [cv_segment()]},
            ),
        ]
        self.assertEqual(
            [response.status_code for response in responses],
            [401, 403],
        )
        invalid = self.owner.patch(
            f"/api/jobs/{self.job_id}/review",
            json={
                "status": "approved",
                "segments": [cv_segment(review="accepted")],
            },
        )
        self.assertEqual(invalid.status_code, 400, invalid.get_json())
        self.assertEqual(
            invalid.get_json()["error_code"],
            "REVIEW_INPUT_INVALID",
        )
        self.assertEqual(self._review_count(), 0)
        self.assertEqual(
            self.jobs.report_path(self.job_id).read_bytes(),
            report_before,
        )


    def test_segment_crud_split_and_merge_preserve_schema(self) -> None:
        added = self.owner.post(
            f"/api/jobs/{self.job_id}/segments",
            json={"start": 6.0, "end": 10.0},
        )
        self.assertEqual(added.status_code, 201, added.get_json())
        manual = added.get_json()["segment"]
        self.assertEqual(manual["source"], "manual")
        self.assertEqual(manual["review"], "")

        updated = self.owner.patch(
            f"/api/jobs/{self.job_id}/segments/{manual['id']}",
            json={"start": 5.5, "order": 1},
        )
        self.assertEqual(updated.status_code, 200, updated.get_json())
        self.assertEqual(updated.get_json()["segment"]["start"], 5.5)
        self.assertEqual(updated.get_json()["segment"]["order"], 1)

        split = self.owner.post(
            f"/api/jobs/{self.job_id}/segments/{manual['id']}/split",
            json={"split_time": 8.0},
        )
        self.assertEqual(split.status_code, 200, split.get_json())
        split_segments = split.get_json()["segments"]
        self.assertEqual(len(split_segments), 2)
        self.assertEqual(
            {segment["source"] for segment in split_segments},
            {"split"},
        )

        merged = self.owner.post(
            f"/api/jobs/{self.job_id}/segments/merge",
            json={
                "seg_id_1": split_segments[0]["id"],
                "seg_id_2": split_segments[1]["id"],
            },
        )
        self.assertEqual(merged.status_code, 200, merged.get_json())
        merged_segment = merged.get_json()["segment"]
        self.assertEqual(merged_segment["source"], "merged")
        self.assertEqual(
            set(merged_segment["source_segment_ids"]),
            {segment["id"] for segment in split_segments},
        )

        deleted = self.owner.delete(
            f"/api/jobs/{self.job_id}/segments/{merged_segment['id']}"
        )
        self.assertEqual(deleted.status_code, 200, deleted.get_json())
        remaining = self.jobs.read_report(self.job_id)["segments"]
        self.assertEqual([segment["id"] for segment in remaining], ["seg_a"])


if __name__ == "__main__":
    unittest.main()
