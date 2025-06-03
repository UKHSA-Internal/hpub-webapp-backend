import json
import logging
import mimetypes
import subprocess
import shlex
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Dict, List, Tuple, Union, Optional
from urllib.parse import urlparse, urlsplit, parse_qs

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

# Default MIME type when unknown
DEFAULT_MIME = "application/octet-stream"


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


def _fetch_via_head(url: str, session: requests.Session) -> Tuple[int, str]:
    """
    Attempt to retrieve size and content type using a HEAD request.
    Returns (size_in_bytes, content_type_or_empty).
    """
    size = 0
    content_type = ""
    try:
        resp = session.head(url, allow_redirects=True, timeout=15)
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
        resp = session.get(url, headers=headers, stream=True, timeout=15)
        resp.raise_for_status()
        content_range = resp.headers.get("Content-Range", "")
        if content_range and "/" in content_range:
            total_str = content_range.split("/")[-1]
            try:
                size = int(total_str)
                logger.info(f"Range → size={_hr(size)} for {url}")
            except ValueError as e:
                logger.warning(f"Cannot parse Content-Range '{content_range}': {e}")
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
        resp = session.get(url, stream=True, timeout=120)
        resp.raise_for_status()
        bytes_accum = 0
        for chunk in resp.iter_content(chunk_size=8192):
            if not chunk:
                break
            bytes_accum += len(chunk)
        size = bytes_accum
        logger.info(f"Streamed full file → size={_hr(size)} for {url}")
        if not content_type:
            ct = resp.headers.get("Content-Type", "")
            if ct:
                content_type = ct
                logger.debug(f"Streamed → type={content_type} for {url}")
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

    if not content_type:
        guessed = mimetypes.guess_type(urlsplit(url).path)[0]
        content_type = guessed if guessed else DEFAULT_MIME
        logger.debug(f"Guessed MIME type '{content_type}' from extension for {url}")

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


def _needs_deep_probe(mime: str, size: int) -> bool:
    """
    Decide if a remote file should be downloaded for deeper probing.

    - Always probe PDFs, images, audio, and office‐type documents to get full metadata.
    - Skip any 'video/' (or other extremely large types) to avoid big downloads.
    """
    deep_types = (
        "application/pdf",
        "audio/",
        "image/",
        "application/vnd.openxmlformats-officedocument",
        "application/vnd.oasis",
    )
    return size > 0 and any(mime.startswith(t) for t in deep_types)


def _download_to_temp(url: str) -> Optional[Path]:
    """
    Download remote file to a temporary file for deep probing.
    Returns Path to temp file or None on failure.
    """
    logger.info(f"Downloading {url} for deep probing")
    try:
        resp = requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
        with NamedTemporaryFile(delete=False, suffix=".tmp") as tmpf:
            for chunk in resp.iter_content(chunk_size=8192):
                if not chunk:
                    break
                tmpf.write(chunk)
            temp_path = Path(tmpf.name)
        logger.info(f"Downloaded to temp file: {temp_path}")
        return temp_path
    except requests.RequestException as e:
        logger.warning(f"Download failed for {url}: {e}")
    except Exception as e:
        logger.critical(f"Temp file write error for {url}: {e}")
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
            result["image_dimensions"] = (w_px, h_px)
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
        result["audio_duration"] = _format_duration(duration)
        logger.debug(f"Audio duration: {result['audio_duration']} for {temp_path}")
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
                    result["video_dimensions"] = (int(w), int(h))
                    logger.debug(f"Video dims: {w}×{h} for {source}")
            fmt = info.get("format", {})
            dur_str = fmt.get("duration")
            if dur_str:
                dur = float(dur_str)
                result["video_duration"] = _format_duration(dur)
                logger.debug(f"Video duration: {result['video_duration']} for {source}")
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
        result["paragraph_count"] = para_count
        result["word_count"] = word_count
        logger.debug(f"DOCX paras={para_count}, words={word_count} for {temp_path}")
    except Exception as e:
        logger.warning(f"Failed to read DOCX metadata for {temp_path}: {e}")
    return result


def _extract_pptx_metadata(temp_path: Path) -> Dict[str, Union[int, str]]:
    """
    Extract PPTX slide count and ISO A-series slide size.
    Always returns 'slide_count' and 'slide_size' as ISO name.
    """
    result: Dict[str, Union[int, str]] = {}
    try:
        prs = Presentation(str(temp_path))
        slide_count = len(prs.slides)
        result["slide_count"] = slide_count
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
        result["sheet_count"] = sheet_count
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
        result["paragraph_count_odt"] = len(paras)
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
    if mime.startswith("video/"):
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
    Handle a remote file: fetch size and MIME, then download if deep probe is needed.
    Returns (size, mime, temp_probe_file_or_None).
    """
    size = 0
    mime = ""
    temp_probe_file: Optional[Path] = None

    remote_info = _fetch_remote_file_size_and_type(url)
    size = remote_info["size"]
    mime = remote_info["content_type"]
    logger.debug(f"Remote fetch → size={_hr(size)}, type={mime} for {url}")

    if _needs_deep_probe(mime, size):
        temp_probe_file = _download_to_temp(url)

    return size, mime, temp_probe_file


def get_file_metadata(
    urls: List[str],
) -> List[Dict[str, Union[str, int, float, tuple]]]:
    """
    For each URL (or local file path), gather metadata including:
      - file_size (human-readable)
      - file_type (MIME)
      - If image → image_dimensions (width, height) in pixels
      - If PDF → number_of_pages, page_size (ISO A0–A10)
      - If audio → audio_duration
      - If video → video_dimensions, video_duration  (via ffprobe on either URL or local file)
      - If DOCX → paragraph_count, word_count
      - If PPTX → slide_count, slide_size (ISO A0–A10)
      - If XLSX → sheet_count
      - If ODT → paragraph_count_odt
    Returns a list of metadata dicts.
    """
    results: List[Dict[str, Union[str, int, float, tuple]]] = []

    for url in urls:
        logger.info(f"Starting metadata extraction for: {url}")
        meta: Dict[str, Union[str, int, float, tuple]] = {"URL": url}

        parsed = urlparse(url)
        is_local = False
        local_path: Optional[Path] = None

        if parsed.scheme in ("", "file"):
            try:
                candidate = Path(parsed.path)
                if candidate.exists() and candidate.is_file():
                    local_path = candidate
                    is_local = True
            except Exception as e:
                logger.debug(f"Cannot interpret '{url}' as local file: {e}")

        if is_local and local_path is not None:
            size, mime, temp_probe_file = _process_local_file(local_path)
        else:
            size, mime, temp_probe_file = _process_remote_file(url)

        if temp_probe_file and temp_probe_file.exists():
            size, mime = _reprobe_file(temp_probe_file, size, mime)
        else:
            if size == 0 and not mime:
                logger.warning(
                    f"Unable to determine size/type for {url}; defaulting to {DEFAULT_MIME}"
                )
                mime = DEFAULT_MIME

        meta["file_size"] = _hr(size)
        meta["file_type"] = mime or DEFAULT_MIME

        if mime.startswith("video/"):
            video_source = (
                temp_probe_file
                if (temp_probe_file and temp_probe_file.exists())
                else url
            )
            video_meta = _extract_video_metadata(video_source)
            meta.update(video_meta)
        elif temp_probe_file and temp_probe_file.exists():
            additional = _extract_additional_metadata(mime, temp_probe_file)
            meta.update(additional)

        if temp_probe_file and not is_local and temp_probe_file.exists():
            try:
                temp_probe_file.unlink()
                logger.info(f"Removed temporary file {temp_probe_file} for {url}")
            except Exception as e:
                logger.warning(f"Error removing temp file {temp_probe_file}: {e}")

        results.append(meta)
        logger.info(f"Finished {url}. Metadata → {json.dumps(meta)}")

    logger.info(f"Collected metadata for {len(results)} files.")
    return results
