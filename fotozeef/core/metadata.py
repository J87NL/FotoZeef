from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fotozeef.core.imaging import register_codecs
from fotozeef.core.models import CaptureSource, PhotoMetadata

_DATETIME_ORIGINAL = 36867
_DATETIME_DIGITIZED = 36868
_DATETIME = 306
_ORIENTATION = 274
_MAKE = 271
_MODEL = 272

_EXIF_TIME_FORMATS = ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S")


def read_metadata(path: Path, mtime: float | None = None) -> PhotoMetadata:
    """EXIF capture time, camera and orientation; falls back to file mtime."""
    captured_at, orientation, camera = _read_with_pillow(path)
    if captured_at is None:
        fallback_time, fallback_orientation, fallback_camera = _read_with_exifread(path)
        captured_at = fallback_time
        camera = camera or fallback_camera
        if orientation == 1 and fallback_orientation != 1:
            orientation = fallback_orientation

    if captured_at is not None:
        return PhotoMetadata(
            captured_at=captured_at,
            capture_source=CaptureSource.EXIF,
            orientation=orientation,
            camera=camera,
        )

    timestamp = mtime if mtime is not None else _safe_mtime(path)
    return PhotoMetadata(
        captured_at=datetime.fromtimestamp(timestamp),
        capture_source=CaptureSource.MTIME,
        orientation=orientation,
        camera=camera,
    )


def _read_with_pillow(path: Path) -> tuple[datetime | None, int, str | None]:
    register_codecs()
    try:
        from PIL import Image

        with Image.open(path) as image:
            exif = image.getexif()
    except Exception:
        return None, 1, None

    if not exif:
        return None, 1, None

    captured_at = None
    for tag in (_DATETIME_ORIGINAL, _DATETIME_DIGITIZED, _DATETIME):
        captured_at = _parse_exif_datetime(exif.get(tag))
        if captured_at is not None:
            break
    if captured_at is None:
        ifd = exif.get_ifd(0x8769)
        for tag in (_DATETIME_ORIGINAL, _DATETIME_DIGITIZED):
            captured_at = _parse_exif_datetime(ifd.get(tag))
            if captured_at is not None:
                break

    orientation = _coerce_orientation(exif.get(_ORIENTATION))
    camera = _format_camera(exif.get(_MAKE), exif.get(_MODEL))
    return captured_at, orientation, camera


def _read_with_exifread(path: Path) -> tuple[datetime | None, int, str | None]:
    try:
        import exifread

        with path.open("rb") as handle:
            tags = exifread.process_file(handle, details=False, stop_tag="Image Model")
    except Exception:
        return None, 1, None

    captured_at = None
    for name in ("EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime"):
        captured_at = _parse_exif_datetime(tags.get(name))
        if captured_at is not None:
            break

    orientation = 1
    raw_orientation = tags.get("Image Orientation")
    if raw_orientation is not None and getattr(raw_orientation, "values", None):
        orientation = _coerce_orientation(raw_orientation.values[0])

    camera = _format_camera(tags.get("Image Make"), tags.get("Image Model"))
    return captured_at, orientation, camera


def _parse_exif_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip().strip("\x00")
    if not text or text.startswith("0000"):
        return None
    for fmt in _EXIF_TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _coerce_orientation(value: object) -> int:
    try:
        orientation = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1
    if orientation < 1 or orientation > 8:
        return 1
    return orientation


def _format_camera(make: object, model: object) -> str | None:
    make_text = _clean(make)
    model_text = _clean(model)
    if model_text and make_text and not model_text.casefold().startswith(make_text.casefold()):
        return f"{make_text} {model_text}"
    return model_text or make_text


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().strip("\x00").strip()


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
