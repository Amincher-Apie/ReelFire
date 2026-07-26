from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import setup_environment


class SetupEnvironmentModelTests(unittest.TestCase):
    def test_existing_verified_model_is_reused(self) -> None:
        payload = b"verified-model"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temporary_directory:
            model_path = Path(temporary_directory) / "models" / "yolo11n.pt"
            model_path.parent.mkdir()
            model_path.write_bytes(payload)

            with (
                patch.object(setup_environment, "MODEL_SHA256", digest),
                patch("setup_environment.urllib.request.urlopen") as urlopen,
            ):
                setup_environment.ensure_yolo_model(
                    dry_run=False,
                    model_path=model_path,
                )

            urlopen.assert_not_called()
            self.assertEqual(model_path.read_bytes(), payload)

    def test_missing_model_is_downloaded_and_verified(self) -> None:
        payload = b"downloaded-model"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temporary_directory:
            model_path = Path(temporary_directory) / "models" / "yolo11n.pt"

            with (
                patch.object(setup_environment, "MODEL_SHA256", digest),
                patch(
                    "setup_environment.urllib.request.urlopen",
                    return_value=io.BytesIO(payload),
                ),
            ):
                setup_environment.ensure_yolo_model(
                    dry_run=False,
                    model_path=model_path,
                )

            self.assertEqual(model_path.read_bytes(), payload)
            self.assertFalse(model_path.with_suffix(".pt.part").exists())

    def test_corrupt_download_is_rejected_and_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            model_path = Path(temporary_directory) / "models" / "yolo11n.pt"

            with (
                patch.object(setup_environment, "MODEL_SHA256", "0" * 64),
                patch(
                    "setup_environment.urllib.request.urlopen",
                    return_value=io.BytesIO(b"corrupt"),
                ),
            ):
                with self.assertRaises(setup_environment.SetupError):
                    setup_environment.ensure_yolo_model(
                        dry_run=False,
                        model_path=model_path,
                    )

            self.assertFalse(model_path.exists())
            self.assertFalse(model_path.with_suffix(".pt.part").exists())


if __name__ == "__main__":
    unittest.main()
