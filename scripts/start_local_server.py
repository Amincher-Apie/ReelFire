from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the ReelFire local server without a console window."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=7880, type=int)
    parser.add_argument("--startup-timeout", default=15.0, type=float)
    return parser.parse_args()


def wait_for_port(
    process: subprocess.Popen[bytes],
    host: str,
    port: int,
    timeout: float,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    instance_dir = root / "instance"
    instance_dir.mkdir(parents=True, exist_ok=True)
    log_path = instance_dir / f"server-{args.port}.log"

    environment = os.environ.copy()
    environment["YOLO_CONFIG_DIR"] = str(instance_dir / "ultralytics")
    creation_flags = 0
    if os.name == "nt":
        creation_flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )

    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                str(root / "app.py"),
                "--host",
                args.host,
                "--port",
                str(args.port),
            ],
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
            close_fds=True,
        )

    if not wait_for_port(
        process,
        args.host,
        args.port,
        max(1.0, args.startup_timeout),
    ):
        process.terminate()
        process.wait(timeout=5)
        print(f"Server failed to listen; inspect {log_path}", file=sys.stderr)
        return 1

    print(f"PROCESS_ID={process.pid}")
    print(f"URL=http://{args.host}:{args.port}")
    print(f"LOG={log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
