# core/utils/extract_file_metadata.py
from __future__ import annotations
import json, logging, mimetypes, os, shlex, subprocess, tempfile, time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.cache import cache

from pptx import Presentation
from docx import Document as DocxDocument
from PyPDF2 import PdfReader

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

DEFAULT_MIME = "application/octet-stream"
s3_client = boto3.client("s3")

ISO_A_SIZES_MM = {
    "A0": (841.0, 1189.0),
    "A1": (594.0, 841.0),
    "A2": (420.0, 594.0),
    "A3": (297.0, 420.0),
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "A6": (105.0, 148.0),
    "A7": (74.0, 105.0),
    "A8": (52.0, 74.0),
    "A9": (37.0, 52.0),
    "A10": (26.0, 37.0),
}

AUDIO_EXTS = {"mp3", "wav", "aac", "m4a", "flac", "ogg", "oga", "opus"}
VIDEO_EXTS = {"mp4", "mov", "m4v", "webm", "mkv", "avi"}


def _hr(n: int) -> str:
    if n < 1024:
        return f"{n} Bytes"
    for u in ["KB", "MB", "GB", "TB", "PB"]:
        n /= 1024.0
        if n < 1024.0:
            return f"{n:.2f} {u}"
    return f"{n:.2f} EB"


def _format_duration(seconds: float) -> str:
    try:
        s = float(seconds)
    except Exception:
        return ""
    if s < 60:
        return f"{s:.2f} s"
    m = int(s // 60)
    sec = int(round(s - m * 60))
    if m < 60:
        return f"{m}:{sec:02d}"
    h = int(m // 60)
    m2 = int(m % 60)
    return f"{h}h {m2}m"


def _find_closest_iso_size(width_mm: float, height_mm: float) -> str:
    w, h = round(width_mm, 2), round(height_mm, 2)
    best, diff = "A4", float("inf")
    for name, (iw, ih) in ISO_A_SIZES_MM.items():
        d = min(abs(w - iw) + abs(h - ih), abs(w - ih) + abs(h - iw))
        if d < diff:
            best, diff = name, d
    return best


def _parse_s3_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    p = urlparse(url)
    host, path = p.netloc, p.path.lstrip("/")
    if host.endswith(".amazonaws.com") and ("s3." in host or "s3-" in host):
        return host.split(".s3", 1)[0], path
    if host in ("s3.amazonaws.com",) or (
        host.startswith("s3-") and host.endswith(".amazonaws.com")
    ):
        parts = path.split("/", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
    return None, None


def _s3_head(url: str) -> Optional[dict]:
    b, k = _parse_s3_url(url)
    if not b or not k:
        return None
    try:
        h = s3_client.head_object(Bucket=b, Key=k)
        return {
            "size": int(h.get("ContentLength", 0)),
            "content_type": h.get("ContentType") or DEFAULT_MIME,
            "etag": (h.get("ETag") or "").strip('"'),
            "bucket": b,
            "key": k,
        }
    except ClientError as e:
        logger.debug("S3 head failed for %s: %s", url, e)
        return None


def _guess_type(url: str) -> str:
    return mimetypes.guess_type(urlparse(url).path)[0] or DEFAULT_MIME


def _download_s3_to_temp(bucket: str, key: str) -> Optional[Path]:
    try:
        fd, path = tempfile.mkstemp(suffix=Path(key).suffix or ".bin")
        os.close(fd)
        with open(path, "wb") as f:
            s3_client.download_fileobj(bucket, key, f)
        return Path(path)
    except Exception as e:
        logger.debug("Download failed s3://%s/%s: %s", bucket, key, e)
        return None


def _libreoffice_pdf(src: Path) -> Optional[Path]:
    if not bool(getattr(settings, "DOC_PAGECOUNT_VIA_LIBREOFFICE", False)):
        return None
    binpath = getattr(settings, "LIBREOFFICE_BIN", "/usr/bin/soffice")
    try:
        outdir = Path(tempfile.mkdtemp())
        cmd = f"{shlex.quote(binpath)} --headless --convert-to pdf --outdir {shlex.quote(str(outdir))} {shlex.quote(str(src))}"
        subprocess.run(
            shlex.split(cmd),
            timeout=int(getattr(settings, "LIBREOFFICE_TIMEOUT_SECS", 25)),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pdf = outdir / (src.stem + ".pdf")
        return pdf if pdf.exists() else None
    except Exception as e:
        logger.debug("LibreOffice conversion failed: %s", e)
        return None


def _pdf_meta(p: Path) -> Dict[str, Union[str, int]]:
    out: Dict[str, Union[str, int]] = {}
    try:
        r = PdfReader(str(p))
        out["number_of_pages"] = len(r.pages)
        pg = r.pages[0]
        w_pt = float(pg.mediabox.width)
        h_pt = float(pg.mediabox.height)
        w_mm = (w_pt / 72.0) * 25.4
        h_mm = (h_pt / 72.0) * 25.4
        out["page_size"] = _find_closest_iso_size(w_mm, h_mm)
    except Exception as e:
        logger.debug("PDF meta failed for %s: %s", p, e)
    return out


def _pptx_meta(p: Path) -> Dict[str, Union[str, int]]:
    out: Dict[str, Union[str, int]] = {}
    try:
        prs = Presentation(str(p))
        out["number_of_pages"] = len(prs.slides)
        emu_per_inch = 914400.0
        w_in = prs.slide_width / emu_per_inch
        h_in = prs.slide_height / emu_per_inch
        out["page_size"] = _find_closest_iso_size(w_in * 25.4, h_in * 25.4)
    except Exception as e:
        logger.debug("PPTX meta failed for %s: %s", p, e)
    return out


def _docx_meta(p: Path) -> Dict[str, Union[str, int]]:
    out: Dict[str, Union[str, int]] = {}
    try:
        doc = DocxDocument(str(p))
        if doc.sections:
            s0 = doc.sections[0]
            emu_per_inch = 914400.0
            w_in = float(s0.page_width) / emu_per_inch
            h_in = float(s0.page_height) / emu_per_inch
            out["page_size"] = _find_closest_iso_size(w_in * 25.4, h_in * 25.4)
    except Exception as e:
        logger.debug("DOCX meta failed for %s: %s", p, e)
    pdf = _libreoffice_pdf(p)
    if pdf:
        try:
            out.update(_pdf_meta(pdf))
        finally:
            try:
                pdf.unlink()
            except Exception:
                pass
    return out


def _odt_meta(p: Path) -> Dict[str, Union[str, int]]:
    out: Dict[str, Union[str, int]] = {}
    pdf = _libreoffice_pdf(p)
    if pdf:
        try:
            out.update(_pdf_meta(pdf))
        finally:
            try:
                pdf.unlink()
            except Exception:
                pass
    return out


def _legacy_ppt_doc_meta(p: Path) -> Dict[str, Union[str, int]]:
    out: Dict[str, Union[str, int]] = {}
    pdf = _libreoffice_pdf(p)
    if pdf:
        try:
            out.update(_pdf_meta(pdf))
        finally:
            try:
                pdf.unlink()
            except Exception:
                pass
    return out


def _deep_doc_meta(temp_path: Path, ext: str) -> Dict[str, Union[str, int]]:
    ext = ext.lower()
    if ext == ".pdf":
        return _pdf_meta(temp_path)
    if ext == ".pptx":
        return _pptx_meta(temp_path)
    if ext == ".docx":
        return _docx_meta(temp_path)
    if ext == ".odt":
        return _odt_meta(temp_path)
    if ext in (".ppt", ".doc"):
        return _legacy_ppt_doc_meta(temp_path)
    return {}


def _ffprobe_info(url: str) -> Dict[str, Union[str, tuple]]:
    """
    Probe audio/video against the remote (presigned) URL.
    Requires ffprobe in PATH and network http support.
    """
    out: Dict[str, Union[str, tuple]] = {}
    try:
        timeout = int(getattr(settings, "FFPROBE_TIMEOUT_SECS", 3))
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=width,height",
            "-print_format",
            "json",
            url,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            return out
        info = json.loads(proc.stdout or "{}")
        # duration
        dur = info.get("format", {}).get("duration")
        if dur:
            out["duration"] = _format_duration(float(dur))
        # dimensions (if video stream present)
        streams = info.get("streams", [])
        for s in streams:
            if "width" in s and "height" in s:
                try:
                    w = int(s["width"])
                    h = int(s["height"])
                    out["dimensions"] = (w, h)
                    break
                except Exception:
                    pass
    except Exception:
        pass
    return out


def _size_limit_bytes() -> Optional[int]:
    v = getattr(settings, "MAX_METADATA_BYTES", None)
    if v in (None, 0):  # 0/None => unlimited
        return None
    try:
        return int(v)
    except Exception:
        return None


def _ext_from_key(key: str) -> str:
    return Path(key).suffix.lower().lstrip(".")


def get_file_metadata(
    urls: List[str],
    *,
    deep_for_doc_types: bool = True,
) -> List[Dict[str, Union[str, int, float, tuple]]]:
    """
    Returns list of dicts:
      { URL, file_size, file_type, [page_size], [number_of_pages], [duration], [dimensions], ... }

    - Minimal (size/type) via S3 HeadObject
    - Deep doc probe (page count / size) only when enabled, within size cap & time budget
    - Audio/Video duration via ffprobe against the URL (no full download)
    - ETag-keyed cache (per bucket/key/etag)
    """
    out: List[Dict[str, Union[str, int, float, tuple]]] = []

    probe_exts = {e.lower() for e in getattr(settings, "DOC_DEEP_PROBE_EXTS", [])}
    ttl = int(getattr(settings, "FILE_METADATA_CACHE_TTL", 6 * 3600))
    size_cap = _size_limit_bytes()
    t_budget_ms = int(getattr(settings, "FILE_METADATA_TIME_BUDGET_MS", 300) or 0)
    started = time.monotonic()

    for url in urls:
        if not url:
            continue

        base: Dict[str, Union[str, int]] = {
            "URL": url,
            "file_size": "0 Bytes",
            "file_type": DEFAULT_MIME,
        }

        head = _s3_head(url)
        ext_from_head = None
        if head:
            base["file_size"] = _hr(head["size"])
            base["file_type"] = head["content_type"]
            ext_from_head = _ext_from_key(head["key"])
            cache_key = f'filemeta:{head["bucket"]}:{head["key"]}:{head["etag"]}'
            cached = cache.get(cache_key)
            if cached is not None:
                out.append({**base, **cached})
                continue

            # If time budget exceeded → store empty details (fast) and continue
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if t_budget_ms and elapsed_ms > t_budget_ms:
                cache.set(cache_key, {}, timeout=ttl)
                out.append(base)
                continue

            # Audio/Video via ffprobe (cheap compared to full download)
            ext = ext_from_head or ""
            is_audio = base["file_type"].startswith("audio/") or ext in AUDIO_EXTS
            is_video = base["file_type"].startswith("video/") or ext in VIDEO_EXTS
            details: Dict[str, Union[str, tuple]] = {}
            if is_audio or is_video:
                details.update(_ffprobe_info(url))

            # Deep doc probe if allowed and under size cap
            can_deep = deep_for_doc_types and ((ext or "").lower() in probe_exts)
            under_cap = (size_cap is None) or (head["size"] <= size_cap)
            if can_deep and under_cap:
                tmp = _download_s3_to_temp(head["bucket"], head["key"])
                try:
                    if tmp:
                        details.update(_deep_doc_meta(tmp, "." + (ext or "")))
                finally:
                    try:
                        tmp.unlink()
                    except Exception:
                        pass

            # cache and return
            cache.set(cache_key, details, timeout=ttl)
            out.append({**base, **details})
            continue

        # Non-S3 URL fallback
        base["file_type"] = _guess_type(url)
        # we can still try ffprobe for non-s3 remote media
        if base["file_type"].startswith(("audio/", "video/")):
            base.update(_ffprobe_info(url))
        out.append(base)

    return out
