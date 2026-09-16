from __future__ import annotations

import threading

_registered = threading.Event()


def register_codecs() -> None:
    if _registered.is_set():
        return
    try:
        import pillow_heif
    except ImportError:
        _registered.set()
        return
    pillow_heif.register_heif_opener()
    _registered.set()
