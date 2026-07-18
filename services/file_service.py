"""Upload validation and persistence helpers."""

from __future__ import annotations

from pathlib import Path

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


class FileValidationError(ValueError):
    """Raised when an uploaded file does not meet the API contract."""


class FileService:
    def __init__(self, allowed_extensions: set[str] | frozenset[str]) -> None:
        self.allowed_extensions = {suffix.lower() for suffix in allowed_extensions}

    def validate_filename(self, upload: FileStorage) -> tuple[str, str]:
        original_name = (upload.filename or "").strip()
        if not original_name:
            raise FileValidationError("上传文件名不能为空")

        suffix = Path(original_name).suffix.lower()
        if suffix not in self.allowed_extensions:
            supported = "、".join(sorted(self.allowed_extensions))
            raise FileValidationError(f"不支持的文件格式，允许格式：{supported}")

        safe_name = secure_filename(original_name)
        if not safe_name or Path(safe_name).suffix.lower() != suffix:
            safe_name = f"video{suffix}"
        return original_name, safe_name

    def save_upload(self, upload: FileStorage, input_dir: Path) -> Path:
        """Save an upload and reject a zero-byte result."""

        _, safe_name = self.validate_filename(upload)
        input_dir.mkdir(parents=True, exist_ok=True)
        destination = input_dir / safe_name
        upload.save(destination)

        try:
            size = destination.stat().st_size
        except OSError as exc:
            raise FileValidationError("无法读取已上传文件") from exc
        if size <= 0:
            destination.unlink(missing_ok=True)
            raise FileValidationError("上传文件不能为空")
        return destination
