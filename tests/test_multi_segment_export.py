from __future__ import annotations

import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from services.ffmpeg_service import (
    create_multi_segment_rough_cut,
    create_rough_cut,
)


class FakeAnalysisService:
    def shutdown(self, wait: bool = False) -> None:
        del wait


def fake_analysis_service_factory(*_args) -> FakeAnalysisService:
    return FakeAnalysisService()


def cv_segments() -> list[dict]:
    return [
        {
            "id": "seg_002",
            "order": 2,
            "start": 2.0,
            "end": 3.0,
            "score": 0.7,
            "source_keyframes": [],
        },
        {
            "id": "seg_001",
            "order": 1,
            "start": 8.0,
            "end": 9.0,
            "score": 0.9,
            "source_keyframes": ["kf_001"],
        },
        {
            "id": "seg_003",
            "order": 3,
            "start": 5.0,
            "end": 6.5,
            "score": 0.5,
            "source_keyframes": [],
        },
    ]


class MultiSegmentFfmpegServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"source")
        self.output = self.root / "rough.mp4"
        self.commands: list[list[str]] = []

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _which(name: str) -> str:
        return name

    def _successful_run(self, audio: bool):
        def run(command, **kwargs):
            self.assertFalse(kwargs["shell"])
            self.commands.append(command)
            if command[0] == "ffprobe":
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="0\n" if audio else "",
                    stderr="",
                )
            Path(command[-1]).write_bytes(b"encoded")
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="",
                stderr="",
            )

        return run

    def test_three_segments_use_order_and_audio_concat(self) -> None:
        source_segments = cv_segments()
        with (
            patch("services.ffmpeg_service.shutil.which", side_effect=self._which),
            patch(
                "services.ffmpeg_service.subprocess.run",
                side_effect=self._successful_run(audio=True),
            ),
        ):
            result = create_multi_segment_rough_cut(
                self.source,
                self.output,
                source_segments,
                "9:16",
            )

        self.assertEqual(result, self.output.resolve())
        self.assertEqual(self.output.read_bytes(), b"encoded")
        self.assertEqual([item["id"] for item in source_segments], [
            "seg_002",
            "seg_001",
            "seg_003",
        ])
        ffmpeg_command = self.commands[1]
        filter_graph = ffmpeg_command[ffmpeg_command.index("-filter_complex") + 1]
        self.assertLess(
            filter_graph.index("trim=start=8.000000:end=9.000000"),
            filter_graph.index("trim=start=2.000000:end=3.000000"),
        )
        self.assertLess(
            filter_graph.index("trim=start=2.000000:end=3.000000"),
            filter_graph.index("trim=start=5.000000:end=6.500000"),
        )
        self.assertIn("concat=n=3:v=1:a=1[vout][aout]", filter_graph)
        self.assertIn("[aout]", ffmpeg_command)
        self.assertIn("scale=1080:1920", filter_graph)

    def test_no_audio_uses_video_only_concat(self) -> None:
        with (
            patch("services.ffmpeg_service.shutil.which", side_effect=self._which),
            patch(
                "services.ffmpeg_service.subprocess.run",
                side_effect=self._successful_run(audio=False),
            ),
        ):
            create_multi_segment_rough_cut(
                self.source,
                self.output,
                cv_segments(),
                "1:1",
            )

        ffmpeg_command = self.commands[1]
        filter_graph = ffmpeg_command[ffmpeg_command.index("-filter_complex") + 1]
        self.assertIn("concat=n=3:v=1:a=0[vout]", filter_graph)
        self.assertNotIn("[aout]", ffmpeg_command)
        self.assertNotIn("-c:a", ffmpeg_command)
        self.assertIn("scale=1080:1080", filter_graph)

    def test_single_segment_compatibility_export_still_works(self) -> None:
        with (
            patch("services.ffmpeg_service.shutil.which", return_value="ffmpeg"),
            patch(
                "services.ffmpeg_service.subprocess.run",
                side_effect=self._successful_run(audio=False),
            ),
        ):
            result = create_rough_cut(
                self.source,
                self.output,
                1.0,
                2.0,
                "16:9",
            )

        self.assertEqual(result, self.output.resolve())
        self.assertEqual(self.output.read_bytes(), b"encoded")

    def test_invalid_ratio_and_segments_are_rejected(self) -> None:
        with patch(
            "services.ffmpeg_service.shutil.which",
            side_effect=self._which,
        ):
            with self.assertRaisesRegex(ValueError, "output_ratio"):
                create_multi_segment_rough_cut(
                    self.source,
                    self.output,
                    cv_segments(),
                    "4:3",
                )
            with self.assertRaisesRegex(ValueError, "非空数组"):
                create_multi_segment_rough_cut(
                    self.source,
                    self.output,
                    [],
                    "16:9",
                )
            with self.assertRaisesRegex(ValueError, "必须是对象"):
                create_multi_segment_rough_cut(
                    self.source,
                    self.output,
                    ["bad"],  # type: ignore[list-item]
                    "16:9",
                )

    def test_ffmpeg_failure_cleans_temporary_and_preserves_old_output(self) -> None:
        self.output.write_bytes(b"old")

        def failed_run(command, **_kwargs):
            if command[0] == "ffprobe":
                return subprocess.CompletedProcess(
                    command, 0, stdout="", stderr=""
                )
            return subprocess.CompletedProcess(
                command, 2, stdout="", stderr=f"failed {self.source}"
            )

        with (
            patch("services.ffmpeg_service.shutil.which", side_effect=self._which),
            patch("services.ffmpeg_service.subprocess.run", side_effect=failed_run),
        ):
            with self.assertRaisesRegex(RuntimeError, "退出码 2") as raised:
                create_multi_segment_rough_cut(
                    self.source,
                    self.output,
                    cv_segments(),
                    "16:9",
                )

        self.assertNotIn(str(self.source.resolve()), str(raised.exception))
        self.assertEqual(self.output.read_bytes(), b"old")
        self.assertEqual(list(self.root.glob(".*.tmp.mp4")), [])

    def test_empty_ffmpeg_output_is_failure_and_preserves_old_output(self) -> None:
        self.output.write_bytes(b"old")

        def empty_run(command, **_kwargs):
            if command[0] == "ffprobe":
                return subprocess.CompletedProcess(
                    command, 0, stdout="", stderr=""
                )
            Path(command[-1]).write_bytes(b"")
            return subprocess.CompletedProcess(
                command, 0, stdout="", stderr=""
            )

        with (
            patch("services.ffmpeg_service.shutil.which", side_effect=self._which),
            patch("services.ffmpeg_service.subprocess.run", side_effect=empty_run),
        ):
            with self.assertRaisesRegex(RuntimeError, "未生成有效输出"):
                create_multi_segment_rough_cut(
                    self.source,
                    self.output,
                    cv_segments(),
                    "16:9",
                )

        self.assertEqual(self.output.read_bytes(), b"old")
        self.assertEqual(list(self.root.glob(".*.tmp.mp4")), [])


class MultiSegmentRoughCutApiTestCase(unittest.TestCase):
    MINIMAL_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.root / "test.db",
                "SECRET_KEY": "test-secret-key",
                "LEGACY_USERS_FILE": self.root / "legacy-users.db",
                "OUTPUTS_DIR": self.root / "outputs",
                "MODELS_DIR": self.root / "models",
                "MODEL_PATH": self.root / "models" / "missing.pt",
                "BACKGROUND_WORKERS": 1,
                "ANALYSIS_SERVICE_FACTORY": fake_analysis_service_factory,
            }
        )
        self.client = self.app.test_client()
        registered = self.client.post(
            "/api/auth/register",
            json={"username": "export-owner", "password": "test-passphrase"},
        )
        self.assertEqual(registered.status_code, 201, registered.get_json())
        project = self.client.post(
            "/api/projects",
            json={"name": "Export Project"},
        )
        self.assertEqual(project.status_code, 201, project.get_json())
        self.project_id = project.get_json()["project"]["id"]
        self.job_id = self._upload_job(project_id=self.project_id)
        self.jobs = self.app.extensions["job_service"]
        self._write_report(self.job_id, cv_segments())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _upload_job(self, *, project_id: int | None = None) -> str:
        data = {"file": (io.BytesIO(self.MINIMAL_MP4), "demo.mp4")}
        if project_id is None:
            data["project_name"] = "Legacy"
        else:
            data["project_id"] = str(project_id)
        response = self.client.post(
            "/api/jobs",
            data=data,
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["job_id"]

    def _write_report(self, job_id: str, segments: object) -> None:
        self.jobs.write_report(
            job_id,
            {
                "duration": 20.0,
                "segments": segments,
                "recommended_clip": {
                    "start_time": 1.0,
                    "end_time": 4.0,
                    "output_ratio": "16:9",
                },
                "output": {},
            },
        )
        self.jobs.update_job(
            job_id,
            status="completed",
            completed_at="2026-07-26T14:00:00",
        )

    @staticmethod
    def _successful_export(_input, output, *_args):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"new export")
        return output

    def _review(self, status: str, segments: list[dict] | None = None):
        payload: dict[str, object] = {"status": status}
        if segments is not None:
            payload["segments"] = segments
        return self.client.patch(
            f"/api/jobs/{self.job_id}/review",
            json=payload,
        )

    def test_project_export_requires_latest_approved_review(self) -> None:
        unsafe = self.client.post(
            f"/api/jobs/{self.job_id}/rough-cut",
            json={"output_path": "C:\\unsafe.mp4"},
        )
        self.assertEqual(unsafe.status_code, 400, unsafe.get_json())

        no_review = self.client.post(f"/api/jobs/{self.job_id}/rough-cut", json={})
        self.assertEqual(no_review.status_code, 409, no_review.get_json())

        for status in ("pending", "rejected"):
            review = self._review(status)
            self.assertEqual(review.status_code, 200, review.get_json())
            response = self.client.post(
                f"/api/jobs/{self.job_id}/rough-cut",
                json={},
            )
            self.assertEqual(response.status_code, 409, response.get_json())

        approved_empty = self._review("approved", [])
        self.assertEqual(
            approved_empty.status_code,
            200,
            approved_empty.get_json(),
        )
        empty_response = self.client.post(
            f"/api/jobs/{self.job_id}/rough-cut",
            json={},
        )
        self.assertEqual(
            empty_response.status_code,
            409,
            empty_response.get_json(),
        )

    def test_approved_review_snapshot_drives_export_and_metadata(self) -> None:
        approved_segments = cv_segments()
        approved = self._review("approved", approved_segments)
        self.assertEqual(approved.status_code, 200, approved.get_json())
        review = self.client.get(
            f"/api/jobs/{self.job_id}/review/latest"
        ).get_json()["review"]
        captured: dict[str, object] = {}

        def export(_input, output, segments, ratio):
            captured["segments"] = segments
            captured["ratio"] = ratio
            return self._successful_export(_input, output)

        with (
            patch("routes.api_routes.is_ffmpeg_available", return_value=True),
            patch(
                "routes.api_routes.create_multi_segment_rough_cut",
                side_effect=export,
            ),
        ):
            response = self.client.post(
                f"/api/jobs/{self.job_id}/rough-cut",
                json={
                    "start_time": 0,
                    "end_time": 20,
                    "output_ratio": "1:1",
                },
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertEqual(
            [item["id"] for item in captured["segments"]],  # type: ignore[index]
            ["seg_001", "seg_002", "seg_003"],
        )
        self.assertEqual(captured["ratio"], "1:1")
        self.assertEqual(payload["segment_count"], 3)
        self.assertEqual(
            payload["segment_ids"],
            ["seg_001", "seg_002", "seg_003"],
        )
        self.assertEqual(payload["review_id"], review["id"])
        report = self.jobs.read_report(self.job_id)
        output = report["output"]
        self.assertEqual(output["segment_count"], 3)
        self.assertEqual(output["segment_ids"], payload["segment_ids"])
        self.assertEqual(output["review_id"], review["id"])
        self.assertEqual(output["ratio"], "1:1")
        self.assertEqual(
            self.jobs.get_job(self.job_id)["rough_cut_file"],
            payload["rough_cut_file"],
        )
        self.assertTrue(
            (self.jobs.job_dir(self.job_id) / payload["rough_cut_file"]).is_file()
        )

    def test_legacy_multi_segment_and_single_clip_paths_remain_available(self) -> None:
        legacy_multi = self._upload_job()
        self._write_report(
            legacy_multi,
            [
                {"start": 5.0, "end": 7.0},
                {"start": 1.0, "end": 2.0},
            ],
        )
        captured: dict[str, object] = {}

        def multi(_input, output, segments, ratio):
            captured["segments"] = segments
            captured["ratio"] = ratio
            return self._successful_export(_input, output)

        with (
            patch("routes.api_routes.is_ffmpeg_available", return_value=True),
            patch(
                "routes.api_routes.create_multi_segment_rough_cut",
                side_effect=multi,
            ),
        ):
            multi_response = self.client.post(
                f"/api/jobs/{legacy_multi}/rough-cut",
                json={},
            )
        self.assertEqual(multi_response.status_code, 200, multi_response.get_json())
        self.assertEqual(multi_response.get_json()["segment_count"], 2)
        self.assertEqual(multi_response.get_json()["review_id"], None)
        self.assertEqual(
            [item["id"] for item in captured["segments"]],  # type: ignore[index]
            ["seg_001", "seg_002"],
        )

        legacy_single = self._upload_job()
        self._write_report(legacy_single, [])
        with (
            patch("routes.api_routes.is_ffmpeg_available", return_value=True),
            patch(
                "routes.api_routes.create_rough_cut",
                side_effect=self._successful_export,
            ) as single,
        ):
            single_response = self.client.post(
                f"/api/jobs/{legacy_single}/rough-cut",
                json={"start_time": 2.0, "end_time": 3.0},
            )
        self.assertEqual(single_response.status_code, 200, single_response.get_json())
        self.assertEqual(single_response.get_json()["segment_count"], 1)
        self.assertEqual(single_response.get_json()["review_id"], None)
        self.assertEqual(single.call_args.args[2:4], (2.0, 3.0))

    def test_export_failure_preserves_job_report_and_previous_output(self) -> None:
        approved = self._review("approved")
        self.assertEqual(approved.status_code, 200, approved.get_json())
        job_before = self.jobs.get_job(self.job_id)
        report_before = self.jobs.report_path(self.job_id).read_bytes()
        previous = self.jobs.job_dir(self.job_id) / "result" / "rough_cut_16x9.mp4"
        previous.write_bytes(b"old export")

        def failed_export(_input, output, *_args):
            output.write_bytes(b"partial staging")
            raise RuntimeError("forced ffmpeg failure")

        with (
            patch("routes.api_routes.is_ffmpeg_available", return_value=True),
            patch(
                "routes.api_routes.create_multi_segment_rough_cut",
                side_effect=failed_export,
            ),
        ):
            response = self.client.post(
                f"/api/jobs/{self.job_id}/rough-cut",
                json={},
            )

        self.assertEqual(response.status_code, 500, response.get_json())
        self.assertEqual(previous.read_bytes(), b"old export")
        self.assertEqual(
            self.jobs.get_job(self.job_id)["rough_cut_file"],
            job_before["rough_cut_file"],
        )
        self.assertEqual(self.jobs.report_path(self.job_id).read_bytes(), report_before)
        self.assertEqual(list(previous.parent.glob(".*.staged.mp4")), [])

    def test_final_replace_failure_restores_metadata_and_preserves_old_export(
        self,
    ) -> None:
        approved = self._review("approved")
        self.assertEqual(approved.status_code, 200, approved.get_json())
        report_before = self.jobs.report_path(self.job_id).read_bytes()
        job_before = self.jobs.get_job(self.job_id)
        previous = self.jobs.job_dir(self.job_id) / "result" / "rough_cut_16x9.mp4"
        previous.write_bytes(b"old export")
        real_replace = os.replace

        def fail_final_replace(source, destination):
            if Path(source).name.endswith(".staged.mp4"):
                raise OSError("forced replace failure")
            return real_replace(source, destination)

        with (
            patch("routes.api_routes.is_ffmpeg_available", return_value=True),
            patch(
                "routes.api_routes.create_multi_segment_rough_cut",
                side_effect=self._successful_export,
            ),
            patch(
                "routes.api_routes.os.replace",
                side_effect=fail_final_replace,
            ),
        ):
            response = self.client.post(
                f"/api/jobs/{self.job_id}/rough-cut",
                json={},
            )

        self.assertEqual(response.status_code, 500, response.get_json())
        self.assertEqual(previous.read_bytes(), b"old export")
        self.assertEqual(
            self.jobs.get_job(self.job_id)["rough_cut_file"],
            job_before["rough_cut_file"],
        )
        self.assertEqual(self.jobs.report_path(self.job_id).read_bytes(), report_before)
        self.assertEqual(list(previous.parent.glob(".*.staged.mp4")), [])

    def test_report_update_failure_leaves_no_partial_export(self) -> None:
        approved = self._review("approved")
        self.assertEqual(approved.status_code, 200, approved.get_json())
        report_before = self.jobs.report_path(self.job_id).read_bytes()
        job_before = self.jobs.get_job(self.job_id)
        previous = self.jobs.job_dir(self.job_id) / "result" / "rough_cut_16x9.mp4"
        previous.write_bytes(b"old export")

        with (
            patch("routes.api_routes.is_ffmpeg_available", return_value=True),
            patch(
                "routes.api_routes.create_multi_segment_rough_cut",
                side_effect=self._successful_export,
            ),
            patch.object(
                self.jobs,
                "update_report",
                side_effect=OSError("forced report failure"),
            ),
        ):
            response = self.client.post(
                f"/api/jobs/{self.job_id}/rough-cut",
                json={},
            )

        self.assertEqual(response.status_code, 500, response.get_json())
        self.assertEqual(previous.read_bytes(), b"old export")
        self.assertEqual(self.jobs.report_path(self.job_id).read_bytes(), report_before)
        self.assertEqual(
            self.jobs.get_job(self.job_id)["rough_cut_file"],
            job_before["rough_cut_file"],
        )
        self.assertEqual(list(previous.parent.glob(".*.staged.mp4")), [])

    def test_job_update_failure_restores_report_and_preserves_old_export(self) -> None:
        approved = self._review("approved")
        self.assertEqual(approved.status_code, 200, approved.get_json())
        report_before = self.jobs.report_path(self.job_id).read_bytes()
        job_before = self.jobs.get_job(self.job_id)
        previous = self.jobs.job_dir(self.job_id) / "result" / "rough_cut_16x9.mp4"
        previous.write_bytes(b"old export")

        with (
            patch("routes.api_routes.is_ffmpeg_available", return_value=True),
            patch(
                "routes.api_routes.create_multi_segment_rough_cut",
                side_effect=self._successful_export,
            ),
            patch.object(
                self.jobs,
                "update_job",
                side_effect=OSError("forced job failure"),
            ),
        ):
            response = self.client.post(
                f"/api/jobs/{self.job_id}/rough-cut",
                json={},
            )

        self.assertEqual(response.status_code, 500, response.get_json())
        self.assertEqual(previous.read_bytes(), b"old export")
        self.assertEqual(self.jobs.report_path(self.job_id).read_bytes(), report_before)
        self.assertEqual(
            self.jobs.get_job(self.job_id)["rough_cut_file"],
            job_before["rough_cut_file"],
        )
        self.assertEqual(list(previous.parent.glob(".*.staged.mp4")), [])


if __name__ == "__main__":
    unittest.main()
