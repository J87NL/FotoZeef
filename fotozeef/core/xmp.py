from __future__ import annotations

import re
from pathlib import Path

_MARKER = "fotozeef"
_RATING_PATTERN = re.compile(r"xmp:Rating\s*=\s*[\"'](\d)[\"']")
_RATING_ELEMENT_PATTERN = re.compile(r"<xmp:Rating>\s*(\d)\s*</xmp:Rating>")

_TEMPLATE = """<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="{marker}">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmp:Rating="{rating}"/>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>
"""


def sidecar_path(photo_path: Path) -> Path:
    return photo_path.with_suffix(photo_path.suffix + ".xmp")


def legacy_sidecar_path(photo_path: Path) -> Path:
    return photo_path.with_suffix(".xmp")


def write_sidecar(photo_path: Path, rating: int = 5) -> Path:
    target = sidecar_path(photo_path)
    target.write_text(_TEMPLATE.format(marker=_MARKER, rating=rating), encoding="utf-8")
    return target


def remove_sidecar(photo_path: Path) -> bool:
    target = sidecar_path(photo_path)
    if not target.is_file() or not was_written_by_app(target):
        return False
    target.unlink()
    return True


def was_written_by_app(sidecar: Path) -> bool:
    try:
        return _MARKER in sidecar.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def read_rating(photo_path: Path) -> int | None:
    for candidate in (sidecar_path(photo_path), legacy_sidecar_path(photo_path)):
        if not candidate.is_file():
            continue
        try:
            content = candidate.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        match = _RATING_PATTERN.search(content) or _RATING_ELEMENT_PATTERN.search(content)
        if match is not None:
            return int(match.group(1))
    return None
