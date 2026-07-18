from __future__ import annotations

import io
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from app import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE_OUTPUTS = PROJECT_ROOT / "outputs" / "manual_acceptance"
MODEL_PATH = PROJECT_ROOT / "models" / "yolo11n.pt"
NORMAL_VIDEO = PROJECT_ROOT / "tests" / "test_assets" / "gameplay_no_audio.mp4"
SPOOFED_VIDEO = PROJECT_ROOT / "tests" / "test_assets" / "fake_video.mp4"


def wait_for_terminal_state(client: Any, job_id: str, timeout: float = 180.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        if response.status_code != 200:
            raise RuntimeError(f"读取任务失败：HTTP {response.status_code}")
        job = response.get_json()["job"]
        if job["status"] in {"completed", "failed"}:
            return job
        time.sleep(0.5)
    raise TimeoutError(f"任务 {job_id} 在 {timeout:.0f} 秒内未结束")


def ffprobe(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def main() -> int:
    app = create_app(
        {
            "TESTING": True,
            "OUTPUTS_DIR": ACCEPTANCE_OUTPUTS,
            "MODELS_DIR": MODEL_PATH.parent,
            "MODEL_PATH": MODEL_PATH,
            "BACKGROUND_WORKERS": 1,
        }
    )
    client = app.test_client()
    records: list[dict[str, Any]] = []

    def record(case_id: str, name: str, check: Callable[[], str]) -> None:
        try:
            evidence = check()
            records.append({"id": case_id, "name": name, "status": "PASS", "evidence": evidence})
        except Exception as error:
            records.append({"id": case_id, "name": name, "status": "FAIL", "evidence": str(error)})

    normal_job: dict[str, Any] = {}
    normal_report: dict[str, Any] = {}
    normal_job_id = ""

    def n01() -> str:
        payload = client.get("/api/health").get_json()
        assert payload["ok"] and payload["model_ready"] and payload["ffmpeg_ready"]
        return "health=200, model_ready=true, ffmpeg_ready=true"

    def n02() -> str:
        page = client.get("/")
        favicon = client.get("/favicon.ico")
        assert page.status_code == 200 and "ReelFire" in page.get_data(as_text=True)
        assert favicon.status_code == 200
        return "首页与 favicon 均返回 200"

    def n03() -> str:
        nonlocal normal_job, normal_report, normal_job_id
        with NORMAL_VIDEO.open("rb") as video:
            response = client.post(
                "/api/jobs",
                data={
                    "file": (video, NORMAL_VIDEO.name),
                    "project_name": "无音频 9:16 本机验收",
                    "game_type": "valorant",
                    "sample_interval": "2",
                    "target_duration": "15",
                    "output_ratio": "9:16",
                },
                content_type="multipart/form-data",
            )
        assert response.status_code == 201, response.get_json()
        normal_job_id = response.get_json()["job_id"]
        queued = client.post(f"/api/jobs/{normal_job_id}/analyze", json={})
        assert queued.status_code == 202, queued.get_json()
        normal_job = wait_for_terminal_state(client, normal_job_id)
        assert normal_job["status"] == "completed", normal_job.get("error")
        normal_report = client.get(f"/api/jobs/{normal_job_id}/report").get_json()["report"]
        assert normal_report["keyframes"] and normal_report["segments"]
        return (
            f"job={normal_job_id}, sampled={normal_report['total_sampled_frames']}, "
            f"keyframes={len(normal_report['keyframes'])}"
        )

    def n04() -> str:
        keyframes = normal_report["keyframes"]
        keyframes[0]["decision"] = "skip"
        keyframes[0]["note"] = "本机验收写回"
        response = client.patch(
            f"/api/jobs/{normal_job_id}/review",
            json={"keyframes": keyframes, "segments": normal_report["segments"]},
        )
        assert response.status_code == 200, response.get_json()
        updated = response.get_json()["report"]
        assert updated["keyframes"][0]["decision"] == "skip"
        return "关键帧 decision/note 与片段边界成功写回 JSON"

    def n05() -> str:
        response = client.post(f"/api/jobs/{normal_job_id}/rough-cut", json={})
        assert response.status_code == 200, response.get_json()
        relative = response.get_json()["rough_cut_file"]
        output = ACCEPTANCE_OUTPUTS / normal_job_id / relative
        details = ffprobe(output)
        stream = details["streams"][0]
        assert output.is_file() and output.stat().st_size > 0
        assert int(stream["height"]) > int(stream["width"])
        return f"{relative}, {stream['width']}x{stream['height']}, {output.stat().st_size} bytes"

    def e01() -> str:
        response = client.post("/api/jobs", data={})
        assert response.status_code == 400 and not response.get_json()["ok"]
        return response.get_json()["error"]

    def e02() -> str:
        response = client.post(
            "/api/jobs",
            data={"file": (io.BytesIO(b"not video"), "demo.txt")},
            content_type="multipart/form-data",
        )
        assert response.status_code == 400
        return response.get_json()["error"]

    def e03() -> str:
        response = client.post(
            "/api/jobs",
            data={"file": (io.BytesIO(SPOOFED_VIDEO.read_bytes()), "spoofed.mp4")},
            content_type="multipart/form-data",
        )
        assert response.status_code == 400
        return response.get_json()["error"]

    def e04() -> str:
        segment = dict(normal_report["segments"][0])
        segment["start"] = 10
        segment["end"] = 5
        response = client.patch(
            f"/api/jobs/{normal_job_id}/review",
            json={"segments": [segment]},
        )
        assert response.status_code == 400
        return response.get_json()["error"]

    def e05() -> str:
        malformed = b"\x00\x00\x00\x1cftypisom" + b"\x00" * 84
        response = client.post(
            "/api/jobs",
            data={"file": (io.BytesIO(malformed), "corrupt.mp4")},
            content_type="multipart/form-data",
        )
        assert response.status_code == 201, response.get_json()
        job_id = response.get_json()["job_id"]
        assert client.post(f"/api/jobs/{job_id}/analyze", json={}).status_code == 202
        job = wait_for_terminal_state(client, job_id)
        assert job["status"] == "failed" and job.get("error")
        return f"job={job_id}, error={job['error']}"

    cases = [
        ("N-01", "健康检查与模型/FFmpeg 就绪", n01),
        ("N-02", "首页及静态资源加载", n02),
        ("N-03", "无音频视频真实 YOLO 分析", n03),
        ("N-04", "人工审核结果写回", n04),
        ("N-05", "无音频视频生成 9:16 粗剪", n05),
        ("E-01", "缺少上传文件", e01),
        ("E-02", "不支持的扩展名", e02),
        ("E-03", "伪装成 MP4 的 PNG", e03),
        ("E-04", "片段结束时间早于开始时间", e04),
        ("E-05", "容器签名合法但视频无法解码", e05),
    ]
    try:
        for case_id, name, check in cases:
            record(case_id, name, check)
    finally:
        app.extensions["analysis_service"].shutdown(wait=True)

    summary = {
        "ok": all(record["status"] == "PASS" for record in records),
        "passed": sum(record["status"] == "PASS" for record in records),
        "total": len(records),
        "records": records,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
