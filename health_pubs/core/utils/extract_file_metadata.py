import json
import logging
import mimetypes
import subprocess
import shlex
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Dict, List, Tuple, Union, Optional
from urllib.parse import urlparse, urlsplit, parse_qs, quote

import magic
import openpyxl
import PyPDF2
import requests
from docx import Document as DocxDocument
from mutagen.mp3 import MP3
from odf.opendocument import load as load_odt
from odf.text import P
from PIL import Image
from pptx import Presentation

# Configure logging
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

# Default MIME type when unknown
DEFAULT_MIME = "application/octet-stream"

# MIME prefixes
VIDEO_MIME_PREFIX = "video/"

# ISO A‐series sizes (in millimeters)
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


def _hr(size_bytes: int) -> str:
    """
    Convert a number of bytes into a human-readable string
    (e.g. 2,560,000 → "2.44 MB").
    """
    if size_bytes < 1024:
        return f"{size_bytes} Bytes"
    for unit in ["KB", "MB", "GB", "TB", "PB"]:
        size_bytes /= 1024.0
        if size_bytes < 1024.0 or unit == "PB":
            return f"{size_bytes:.2f} {unit}"
    return f"{size_bytes:.2f} EB"


def _format_duration(seconds: float) -> str:
    """
    Given a duration in seconds, return a readable string.
    E.g. 45.5 → "45.50 s", 125 → "2.08 min", 3675 → "1 h 1 min".
    """
    if seconds < 60:
        return f"{seconds:.2f} s"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"{minutes:.2f} min"
    hours = int(minutes // 60)
    rem_minutes = int(minutes % 60)
    return f"{hours} h {rem_minutes} min"


def _find_closest_iso_size(width_mm: float, height_mm: float) -> str:
    """
    Given width_mm and height_mm (in millimeters), return the closest ISO A‐series
    size name (A0…A10) based on minimal total absolute difference, accounting for rotation.
    """
    w_r = round(width_mm, 2)
    h_r = round(height_mm, 2)

    best_name = None
    best_diff = float("inf")
    for name, (iso_w, iso_h) in ISO_A_SIZES_MM.items():
        diff_direct = abs(w_r - iso_w) + abs(h_r - iso_h)
        diff_rotated = abs(w_r - iso_h) + abs(h_r - iso_w)

        if diff_direct < best_diff:
            best_diff = diff_direct
            best_name = name
        if diff_rotated < best_diff:
            best_diff = diff_rotated
            best_name = name

    return best_name or "A4"


def _is_presigned_s3(url: str) -> bool:
    """
    Check if the URL is a pre-signed Amazon S3 URL by looking for any query key
    that starts with "X-Amz-".
    """
    qs = parse_qs(urlsplit(url).query)
    return any(k.startswith("X-Amz-") for k in qs)


def _parse_s3_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse an S3 URL into (bucket_name, object_key). Supports:
      - https://{bucket}.s3.amazonaws.com/{key}
      - https://{bucket}.s3-{region}.amazonaws.com/{key}
      - https://s3.amazonaws.com/{bucket}/{key}
    Returns (None, None) if parsing fails.
    """
    parsed = urlparse(url)
    host = parsed.netloc
    path = parsed.path.lstrip("/")

    bucket_name: Optional[str] = None
    object_key: Optional[str] = None

    # Case: bucket in hostname: bucket.s3.amazonaws.com or bucket.s3-region.amazonaws.com
    if host.endswith(".s3.amazonaws.com") or (
        ".s3-" in host and host.endswith(".amazonaws.com")
    ):
        bucket_name = host.split(".")[0]
        object_key = path
    # Case: s3.amazonaws.com/bucket/key
    elif host == "s3.amazonaws.com":
        parts = path.split("/", 1)
        if len(parts) == 2:
            bucket_name, object_key = parts[0], parts[1]

    if not bucket_name or not object_key:
        return None, None
    return bucket_name, object_key


def _normalize_url(url: str) -> str:
    """
    Percent-encode the path component of a URL (so '+' becomes '%2B', spaces to '%20', etc.).
    Leaves the query string untouched.
    """
    try:
        parts = urlsplit(url)
        safe_path = quote(parts.path, safe="/%")
        return parts._replace(path=safe_path).geturl()
    except Exception:
        return url


def _fetch_via_head(url: str, session: requests.Session) -> Tuple[int, str]:
    """
    Attempt to retrieve size and content type using a HEAD request.
    Returns (size_in_bytes, content_type_or_empty).
    """
    size = 0
    content_type = ""
    try:
        resp = session.head(_normalize_url(url), allow_redirects=True, timeout=15)
        resp.raise_for_status()
        head_cl = resp.headers.get("Content-Length")
        if head_cl:
            try:
                size = int(head_cl)
                logger.info(f"HEAD → size={_hr(size)} for {url}")
            except ValueError as e:
                logger.warning(f"Error parsing Content-Length from HEAD: {e}")
        ct = resp.headers.get("Content-Type", "")
        if ct:
            content_type = ct
            logger.debug(f"HEAD → type={content_type} for {url}")
    except requests.RequestException as e:
        logger.warning(f"HEAD request failed for {url}: {e}")
    return size, content_type


def _fetch_via_range(
    url: str, session: requests.Session, current_type: str
) -> Tuple[int, str]:
    """
    Attempt to retrieve size (and possibly content type) using a Range request.
    Returns (size_in_bytes, updated_content_type).
    """
    size = 0
    content_type = current_type
    try:
        headers = {"Range": "bytes=0-0"}
        resp = session.get(
            _normalize_url(url),
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=15,
        )
        resp.raise_for_status()
        content_range = resp.headers.get("Content-Range", "")
        if content_range and "/" in content_range:
            total_str = content_range.split("/")[-1]
            try:
                size = int(total_str)
                logger.info(f"Range → size={_hr(size)} for {url}")
            except ValueError as e:
                logger.warning(f"Cannot parse Content-Range '{content_range}': {e}")
        elif resp.status_code == 200:
            # Some servers ignore Range and send the full response
            cl = resp.headers.get("Content-Length")
            if cl:
                try:
                    size = int(cl)
                    logger.info(f"Range (200) → size={_hr(size)} for {url}")
                except ValueError:
                    pass
        if not content_type:
            ct = resp.headers.get("Content-Type", "")
            if ct:
                content_type = ct
                logger.debug(f"Range → type={content_type} for {url}")
    except requests.RequestException as e:
        logger.warning(f"Range request failed for {url}: {e}")
    return size, content_type


def _fetch_via_stream(
    url: str, session: requests.Session, current_type: str
) -> Tuple[int, str]:
    """
    Stream the entire file to measure size manually.
    Returns (size_in_bytes, updated_content_type).
    """
    size = 0
    content_type = current_type
    try:
        resp = session.get(
            _normalize_url(url), stream=True, allow_redirects=True, timeout=120
        )
        resp.raise_for_status()
        bytes_accum = 0
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                bytes_accum += len(chunk)
        size = bytes_accum
        logger.info(f"Streamed full file → size={_hr(size)} for {url}")
        if not content_type:
            ct = resp.headers.get("Content-Type", "")
            if ct:
                content_type = ct
                logger.debug(f"Streamed → type={content_type} for {url}")
        # Fallback: if server sent a length but stream yielded 0 (rare but possible)
        if size == 0:
            cl = resp.headers.get("Content-Length")
            if cl:
                try:
                    size = int(cl)
                except ValueError:
                    pass
    except requests.RequestException as e:
        logger.error(f"Failed to stream {url}: {e}")
    except Exception as e:
        logger.critical(f"Unexpected streaming error for {url}: {e}")
    return size, content_type


def _fetch_remote_file_size_and_type(url: str) -> Dict[str, Union[int, str]]:
    """
    Attempt to retrieve Content-Length and Content-Type for a remote URL via:
      1) HEAD request
      2) If HEAD fails or has no Content-Length, a Range request (bytes=0-0)
      3) If still unknown, a full GET streaming to measure size manually

    After fetching, if content_type is missing or generic, guess based on the URL extension.
    Returns a dict: {"size": <int bytes>, "content_type": "<mime/type>"}
    """
    session = requests.Session()
    size, content_type = _fetch_via_head(url, session)

    if size <= 0:
        size_range, content_type = _fetch_via_range(url, session, content_type)
        if size_range > 0:
            size = size_range

    if size <= 0:
        size_stream, content_type = _fetch_via_stream(url, session, content_type)
        if size_stream > 0:
            size = size_stream

    # If content_type is still empty or generic, guess from extension
    if not content_type or content_type in (
        "application/octet-stream",
        "binary/octet-stream",
        "",
    ):
        guessed = mimetypes.guess_type(urlsplit(_normalize_url(url)).path)[0]
        if guessed:
            content_type = guessed
            logger.debug(f"Guessed MIME type '{content_type}' from extension for {url}")
        else:
            content_type = DEFAULT_MIME
            logger.debug(
                f"No guessable extension for {url}; defaulting to {DEFAULT_MIME}"
            )

    return {"size": size, "content_type": content_type}


def _get_local_file_info(local_path: Path) -> Tuple[int, str, Path]:
    """
    Get size and MIME for a local file.
    Returns (size_in_bytes, mime_type, path_for_probe).
    """
    try:
        size = local_path.stat().st_size
        mime = (
            magic.Magic(mime=True).from_file(str(local_path))
            or mimetypes.guess_type(str(local_path))[0]
            or ""
        )
        logger.info(f"Local file → size={_hr(size)}, type={mime} for {local_path}")
    except Exception as e:
        logger.error(f"Error reading local file {local_path}: {e}")
        size = 0
        mime = DEFAULT_MIME
    return size, mime, local_path


def _needs_deep_probe(mime: str) -> bool:
    """
    Decide if a remote file should be downloaded for deeper probing.

    - Always probe PDFs, images, audio, and office‐type documents to get full metadata.
    - Skip any 'video/' to avoid large downloads.
    """
    if mime.startswith(VIDEO_MIME_PREFIX):
        return False
    deep_types = (
        "application/pdf",
        "audio/",
        "image/",
        "application/vnd.openxmlformats-officedocument",
        "application/vnd.oasis",
    )
    return any(mime.startswith(t) for t in deep_types)


def _download_to_temp(url: str) -> Optional[Path]:
    """
    Download remote file to a temporary file for deep probing.
    Returns Path to temp file or None on failure.
    """
    norm = _normalize_url(url)
    logger.info(f"Downloading {norm} for deep probing")
    try:
        resp = requests.get(norm, stream=True, timeout=60)
        resp.raise_for_status()
        with NamedTemporaryFile(delete=False, suffix=".tmp") as tmpf:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    tmpf.write(chunk)
            temp_path = Path(tmpf.name)
        logger.info(f"Downloaded to temp file: {temp_path}")
        return temp_path
    except requests.RequestException as e:
        logger.warning(f"Download failed for {norm}: {e}")
    except Exception as e:
        logger.critical(f"Temp file write error for {norm}: {e}")
    return None


def _reprobe_file(
    temp_path: Path, current_size: int, current_mime: str
) -> Tuple[int, str]:
    """
    Re-check size and MIME based on the temporary file.
    """
    size = current_size
    mime = current_mime
    try:
        actual_size = temp_path.stat().st_size
        if actual_size > size:
            size = actual_size
            logger.debug(f"Updated size from temp file: {_hr(size)}")
        new_mime = magic.Magic(mime=True).from_file(str(temp_path))
        if new_mime:
            mime = new_mime
            logger.info(f"Updated MIME from temp file: {mime}")
    except Exception as e:
        logger.warning(f"Error re‐probing {temp_path}: {e}")
    return size, mime


def _extract_image_metadata(temp_path: Path) -> Dict[str, tuple]:
    """
    Extract image dimensions.
    """
    result: Dict[str, tuple] = {}
    try:
        with Image.open(temp_path) as img:
            w_px, h_px = img.width, img.height
            result["dimensions"] = (w_px, h_px)
            logger.debug(f"Image dims: {w_px}×{h_px} px for {temp_path}")
    except Exception as e:
        logger.warning(f"Failed to read image dimensions for {temp_path}: {e}")
    return result


def _extract_pdf_metadata(temp_path: Path) -> Dict[str, Union[int, str]]:
    """
    Extract PDF page count and ISO A-series page size (A0–A10).
    Always returns 'number_of_pages' and 'page_size' as ISO name.
    """
    result: Dict[str, Union[int, str]] = {}
    try:
        with open(temp_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            page_count = len(reader.pages)
            result["number_of_pages"] = page_count
            logger.debug(f"PDF pages: {page_count} for {temp_path}")

            first_page = reader.pages[0]
            media_box = first_page.mediabox
            llx = float(media_box.lower_left[0])
            lly = float(media_box.lower_left[1])
            urx = float(media_box.upper_right[0])
            ury = float(media_box.upper_right[1])
            width_pt = urx - llx
            height_pt = ury - lly

            width_in = width_pt / 72.0
            height_in = height_pt / 72.0
            width_mm = width_in * 25.4
            height_mm = height_in * 25.4

            iso_name = _find_closest_iso_size(width_mm, height_mm)
            result["page_size"] = iso_name
            logger.debug(f"PDF size → {iso_name} for {temp_path}")
    except Exception as e:
        logger.warning(f"Could not extract PDF metadata for {temp_path}: {e}")
    return result


def _extract_audio_metadata(temp_path: Path) -> Dict[str, str]:
    """
    Extract audio duration for MP3.
    """
    result: Dict[str, str] = {}
    try:
        audio = MP3(str(temp_path))
        duration = audio.info.length
        result["duration"] = _format_duration(duration)
        logger.debug(f"Audio duration: {result['duration']} for {temp_path}")
    except Exception as e:
        logger.warning(f"Failed to read audio duration for {temp_path}: {e}")
    return result


def _extract_video_metadata(source: Union[Path, str]) -> Dict[str, Union[tuple, str]]:
    """
    Extract video dimensions and duration via ffprobe.
    Can accept either a local Path or a URL string as `source`.
    """
    result: Dict[str, Union[tuple, str]] = {}
    try:
        cmd = (
            f"ffprobe -v quiet -print_format json -show_format -show_streams "
            f"{shlex.quote(str(source))}"
        )
        completed = subprocess.run(
            shlex.split(cmd), capture_output=True, text=True, timeout=30
        )
        if completed.returncode == 0 and completed.stdout:
            info = json.loads(completed.stdout)
            video_stream = next(
                (s for s in info.get("streams", []) if s.get("codec_type") == "video"),
                None,
            )
            if video_stream:
                w = video_stream.get("width")
                h = video_stream.get("height")
                if w and h:
                    result["dimensions"] = (int(w), int(h))
                    logger.debug(f"Video dims: {w}×{h} for {source}")
            fmt = info.get("format", {})
            dur_str = fmt.get("duration")
            if dur_str:
                dur = float(dur_str)
                result["duration"] = _format_duration(dur)
                logger.debug(f"Video duration: {result['duration']} for {source}")
        else:
            logger.warning(f"ffprobe error for {source}: {completed.stderr}")
    except Exception as e:
        logger.warning(f"Error running ffprobe on {source}: {e}")
    return result


def _extract_docx_metadata(temp_path: Path) -> Dict[str, int]:
    """
    Extract DOCX paragraph and word counts.
    """
    result: Dict[str, int] = {}
    try:
        doc = DocxDocument(str(temp_path))
        paras = [p.text for p in doc.paragraphs if p.text]
        para_count = len(paras)
        word_count = sum(len(p.split()) for p in paras)
        result["number_of_paragraphs"] = para_count
        result["number_of_words"] = word_count
        logger.debug(f"DOCX paras={para_count}, words={word_count} for {temp_path}")
    except Exception as e:
        logger.warning(f"Failed to read DOCX metadata for {temp_path}: {e}")
    return result


def _extract_pptx_metadata(temp_path: Path) -> Dict[str, Union[int, str]]:
    """
    Extract PPTX slide count and ISO A-series slide size.
    Always returns 'number_of_slides' and 'slide_size' as ISO name.
    """
    result: Dict[str, Union[int, str]] = {}
    try:
        prs = Presentation(str(temp_path))
        slide_count = len(prs.slides)
        result["number_of_slides"] = slide_count
        logger.debug(f"PPTX slides: {slide_count} for {temp_path}")

        emu_per_inch = 914400.0
        w_emu = prs.slide_width
        h_emu = prs.slide_height
        w_in = w_emu / emu_per_inch
        h_in = h_emu / emu_per_inch
        w_mm = w_in * 25.4
        h_mm = h_in * 25.4

        iso_slide = _find_closest_iso_size(w_mm, h_mm)
        result["slide_size"] = iso_slide
        logger.debug(f"PPTX size → {iso_slide} for {temp_path}")
    except Exception as e:
        logger.warning(f"Failed to read PPTX metadata for {temp_path}: {e}")
    return result


def _extract_xlsx_metadata(temp_path: Path) -> Dict[str, int]:
    """
    Extract XLSX sheet count.
    """
    result: Dict[str, int] = {}
    try:
        wb = openpyxl.load_workbook(str(temp_path), read_only=True, data_only=True)
        sheet_count = len(wb.sheetnames)
        result["number_of_sheets"] = sheet_count
        logger.debug(f"XLSX sheets: {sheet_count} for {temp_path}")
    except Exception as e:
        logger.warning(f"Failed to read XLSX metadata for {temp_path}: {e}")
    return result


def _extract_odt_metadata(temp_path: Path) -> Dict[str, int]:
    """
    Extract ODT paragraph count.
    """
    result: Dict[str, int] = {}
    try:
        odt = load_odt(str(temp_path))
        paras = odt.getElementsByType(P)
        result["number_of_paragraphs_odt"] = len(paras)
        logger.debug(f"ODT paras: {len(paras)} for {temp_path}")
    except Exception as e:
        logger.warning(f"Failed to read ODT metadata for {temp_path}: {e}")
    return result


def _extract_additional_metadata(
    mime: str, temp_path: Path
) -> Dict[str, Union[str, int, tuple]]:
    """
    Dispatch to appropriate extractor based on MIME type.
    (Used only when we have a local file downloaded or local path.)
    """
    if mime.startswith("image/"):
        return _extract_image_metadata(temp_path)
    if mime == "application/pdf":
        return _extract_pdf_metadata(temp_path)
    if mime.startswith("audio/"):
        return _extract_audio_metadata(temp_path)
    if mime.startswith(VIDEO_MIME_PREFIX):
        return _extract_video_metadata(temp_path)
    if mime in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ):
        return _extract_docx_metadata(temp_path)
    if (
        mime
        == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ):
        return _extract_pptx_metadata(temp_path)
    if mime in (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    ):
        return _extract_xlsx_metadata(temp_path)
    if mime == "application/vnd.oasis.opendocument.text":
        return _extract_odt_metadata(temp_path)
    return {}


def _process_local_file(local_path: Path) -> Tuple[int, str, Path]:
    """
    Handle a local file: get its size, MIME, and return the path for further probing.
    """
    return _get_local_file_info(local_path)


def _process_remote_file(url: str) -> Tuple[int, str, Optional[Path]]:
    """
    Handle a remote file: fetch size and MIME (with guessing), then download if deep probe is needed.
    Returns (size, mime, temp_probe_file_or_None).
    """
    size = 0
    mime = ""
    temp_probe_file: Optional[Path] = None

    # 1) fetch approximate size & content-type
    remote_info = _fetch_remote_file_size_and_type(url)
    size = remote_info["size"]
    mime = remote_info["content_type"]
    logger.debug(f"Remote fetch → size={_hr(size)}, type={mime} for {url}")

    # 2) If this is a type that needs deep probing (PDF/images/audio/office), download it
    if _needs_deep_probe(mime):
        temp_probe_file = _download_to_temp(url)

    return size, mime, temp_probe_file


def _is_local_file(url: str) -> Optional[Path]:
    """
    Determine if the given URL corresponds to an existing local file.
    Returns the Path if local, otherwise None.
    """
    parsed = urlparse(url)
    if parsed.scheme in ("", "file"):
        try:
            candidate = Path(parsed.path)
            if candidate.exists() and candidate.is_file():
                return candidate
        except Exception as e:
            logger.debug(f"Cannot interpret '{url}' as local file: {e}")
    return None


def _get_basic_info(source: Union[str, Path]) -> Tuple[int, str, Optional[Path], bool]:
    """
    For a local Path, return (size, mime, temp_probe_file, is_local=True).
    For a URL (string), return (size, mime, temp_probe_file, is_local=False).
    """
    if isinstance(source, Path):
        size, mime, temp_file = _process_local_file(source)
        return size, mime, temp_file, True

    size, mime, temp_file = _process_remote_file(source)
    return size, mime, temp_file, False


def _finalize_size_mime(
    size: int, mime: str, temp_file: Optional[Path], url: str
) -> Tuple[int, str]:
    """
    If a temp file exists, re‐probe to update size and mime. Otherwise,
    if size and mime are still missing, default to DEFAULT_MIME.
    """
    if temp_file and temp_file.exists():
        return _reprobe_file(temp_file, size, mime)

    if size == 0 and not mime:
        logger.warning(
            f"Unable to determine size/type for {url}; defaulting to {DEFAULT_MIME}"
        )
        mime = DEFAULT_MIME

    return size, mime


def _extract_all_metadata(
    mime: str, temp_file: Optional[Path], url: str
) -> Dict[str, Union[str, int, float, tuple]]:
    """
    Based on mime and presence of a temp file, extract additional metadata:
      - For video, run ffprobe on temp file or URL.
      - For other types, run the appropriate extractor on temp file.
    """
    extra: Dict[str, Union[str, int, float, tuple]] = {}
    if mime.startswith(VIDEO_MIME_PREFIX):
        source = temp_file if (temp_file and temp_file.exists()) else url
        extra = _extract_video_metadata(source)
    elif temp_file and temp_file.exists():
        extra = _extract_additional_metadata(mime, temp_file)
    return extra


def _cleanup_temp_file(temp_file: Optional[Path], is_local: bool, url: str) -> None:
    """
    Remove the temporary file if it was downloaded for a remote URL.
    """
    if temp_file and not is_local and temp_file.exists():
        try:
            temp_file.unlink()
            logger.info(f"Removed temporary file {temp_file} for {url}")
        except Exception as e:
            logger.warning(f"Error removing temp file {temp_file}: {e}")


def get_file_metadata(
    urls: List[str],
) -> List[Dict[str, Union[str, int, float, tuple]]]:
    """
    For each URL (or local file path), gather metadata including:
      - URL
      - file_size (human-readable)
      - file_type (MIME)
      - If image → dimensions (width×height in pixels)
      - If PDF → number_of_pages, page_size (ISO A-series)
      - If audio → duration
      - If video → dimensions, duration
      - If DOCX → number_of_paragraphs, number_of_words
      - If PPTX → number_of_slides, slide_size
      - If XLSX → number_of_sheets
      - If ODT → number_of_paragraphs_odt
    Returns a list of metadata dicts.
    """
    results: List[Dict[str, Union[str, int, float, tuple]]] = []

    for url in urls:
        logger.info(f"Starting metadata extraction for: {url}")
        meta: Dict[str, Union[str, int, float, tuple]] = {"URL": url}

        local_path = _is_local_file(url)
        size, mime, temp_file, is_local = _get_basic_info(local_path or url)
        size, mime = _finalize_size_mime(size, mime, temp_file, url)

        meta["file_size"] = _hr(size)
        meta["file_type"] = mime or DEFAULT_MIME

        # Extract additional metadata if we downloaded a temp file (or can probe locally)
        extra = _extract_all_metadata(mime, temp_file, url)
        meta.update(extra)

        # Clean up any temporary download
        _cleanup_temp_file(temp_file, is_local, url)

        results.append(meta)
        logger.info(f"Finished {url}. Metadata → {json.dumps(meta)}")

    logger.info(f"Collected metadata for {len(results)} files.")
    return results
