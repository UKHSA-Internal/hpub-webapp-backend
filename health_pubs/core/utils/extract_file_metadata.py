import json
import logging
import mimetypes
import subprocess
import shlex
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Dict, List, Union
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
    Given width_mm and height_mm (in millimeters), return the standard ISO A‐series
    size name if within ±5 mm of one of A0…A6. If none match, return "W×H mm"
    (rounded to two decimals) so that GDS validators won’t reject it as "Custom".

    Example:
        width_mm=210.0, height_mm=297.0 → "A4"
        width_mm=224.68, height_mm=312.00 → "224.68×312.00 mm"
    """
    w_r = round(width_mm, 2)
    h_r = round(height_mm, 2)

    for name, (iso_w, iso_h) in ISO_A_SIZES_MM.items():
        # check direct orientation
        if abs(w_r - iso_w) <= 5.0 and abs(h_r - iso_h) <= 5.0:
            return name
        # check rotated orientation
        if abs(w_r - iso_h) <= 5.0 and abs(h_r - iso_w) <= 5.0:
            return name

    # if no ISO match within tolerance, return explicit dimensions
    return f"{w_r}×{h_r} mm"


def _is_presigned_s3(url: str) -> bool:
    """
    Check if the URL is a pre-signed Amazon S3 URL by looking for any query key
    that starts with "X-Amz-".
    """
    qs = parse_qs(urlsplit(url).query)
    return any(k.startswith("X-Amz-") for k in qs)


def _fetch_remote_file_size_and_type(url: str) -> Dict[str, Union[int, str]]:
    """
    Attempt to retrieve Content-Length and Content-Type for a remote URL via:
      1) HEAD request
      2) If HEAD fails or has no Content-Length, a Range request (bytes=0-0)
      3) If still unknown, do a full GET streaming to measure size manually

    Returns a dict: {"size": <int bytes>, "content_type": "<mime/type>"}
    """
    size = 0
    content_type = ""
    session = requests.Session()

    logger.info(f"Attempting to fetch size/type via HEAD for {url}")

    # 1) HEAD
    try:
        with session.head(url, allow_redirects=True, timeout=15) as resp_head:
            resp_head.raise_for_status()
            content_length = resp_head.headers.get("Content-Length")
            if content_length:
                size = int(content_length)
                logger.info(f"HEAD → size={_hr(size)} for {url}")
            content_type = resp_head.headers.get("Content-Type", "")
            if content_type:
                logger.debug(f"HEAD → type={content_type} for {url}")
    except requests.RequestException as e:
        logger.warning(f"HEAD request failed for {url}: {e}")
    except ValueError as e:
        logger.warning(f"Error parsing Content-Length from HEAD for {url}: {e}")

    # 2) Range request if HEAD did not give size
    if size <= 0:
        logger.info(f"HEAD did not yield size; attempting Range request for {url}")
        try:
            headers = {"Range": "bytes=0-0"}
            with session.get(
                url, headers=headers, stream=True, timeout=15
            ) as resp_range:
                resp_range.raise_for_status()
                content_range = resp_range.headers.get("Content-Range", "")
                if content_range and "/" in content_range:
                    try:
                        total_str = content_range.split("/")[-1]
                        size = int(total_str)
                        logger.info(f"Range → size={_hr(size)} for {url}")
                    except (ValueError, IndexError) as e:
                        logger.warning(
                            f"Cannot parse Content-Range '{content_range}' for {url}: {e}"
                        )
                if not content_type:
                    content_type = resp_range.headers.get("Content-Type", "")
                    if content_type:
                        logger.debug(f"Range → type={content_type} for {url}")
        except requests.RequestException as e:
            logger.warning(f"Range request failed for {url}: {e}")

    # 3) Full GET streaming if still no size
    if size <= 0:
        logger.info(f"Range failed; streaming full file to measure size for {url}")
        try:
            with session.get(url, stream=True, timeout=120) as resp_stream:
                resp_stream.raise_for_status()
                bytes_accum = 0
                for chunk in resp_stream.iter_content(chunk_size=8192):
                    if not chunk:
                        break
                    bytes_accum += len(chunk)
                size = bytes_accum
                logger.info(f"Streamed full file → size={_hr(size)} for {url}")
                if not content_type:
                    content_type = resp_stream.headers.get("Content-Type", "")
                    if content_type:
                        logger.debug(f"Streamed → type={content_type} for {url}")
        except requests.RequestException as e:
            logger.error(f"Failed to stream {url}: {e}")
            size = 0
        except Exception as e:
            logger.critical(f"Unexpected streaming error for {url}: {e}")
            size = 0

    # 4) Guess from extension if still no type
    if not content_type:
        guessed = mimetypes.guess_type(urlsplit(url).path)[0]
        if guessed:
            content_type = guessed
            logger.debug(f"Guessed MIME type '{content_type}' from extension for {url}")

    return {"size": size, "content_type": content_type}


def get_file_metadata(
    urls: List[str],
) -> List[Dict[str, Union[str, int, float, tuple]]]:
    """
    For each URL (or local file path), gather metadata including:
      - file_size (human-readable)
      - file_type (MIME)
      - If image/ → image_dimensions (width, height) in pixels
      - If PDF/ → page_count, page_size_mm, iso_page_size
      - If audio/ → audio_duration
      - If video/ → video_dimensions, video_duration
      - If DOCX → paragraph_count, word_count
      - If PPTX → slide_count, slide_size_mm, iso_slide_size
      - If XLSX → sheet_count
      - If ODT → paragraph_count_odt
    Returns a list of metadata dicts.
    """
    results: List[Dict[str, Union[str, int, float, tuple]]] = []

    for url in urls:
        logger.info(f"Starting metadata extraction for: {url}")
        meta: Dict[str, Union[str, int, float, tuple]] = {"URL": url}
        parsed = urlparse(url)

        # Determine if local file path
        is_local = False
        local_path: Path = None  # type: ignore
        if parsed.scheme in ("", "file"):
            try:
                candidate = Path(parsed.path)
                if candidate.exists() and candidate.is_file():
                    local_path = candidate
                    is_local = True
            except Exception as e:
                logger.debug(f"Cannot interpret '{url}' as local file: {e}")

        size = 0
        mime = ""
        temp_probe_file: Path = None  # type: ignore

        # 1) Local file
        if is_local:
            temp_probe_file = local_path
            try:
                size = local_path.stat().st_size
                mime = (
                    magic.Magic(mime=True).from_file(str(local_path))
                    or mimetypes.guess_type(str(local_path))[0]
                    or ""
                )
                logger.info(f"Local file → size={_hr(size)}, type={mime} for {url}")
            except Exception as e:
                logger.error(f"Error reading local file {url}: {e}")
                size = 0
                mime = "application/octet-stream"
        else:
            # 2) Remote file: HEAD/Range/full‐GET
            remote_info = _fetch_remote_file_size_and_type(url)
            size = remote_info["size"]
            mime = remote_info["content_type"]
            logger.debug(f"Remote fetch → size={_hr(size)}, type={mime} for {url}")

            # 3) If likely needs “deep probe,” download to a temp file
            if (
                size > 0
                and mime.startswith(
                    (
                        "application/pdf",
                        "video/",
                        "audio/",
                        "image/",
                        "application/vnd.openxmlformats-officedocument",
                        "application/vnd.oasis",
                    )
                )
                and not _is_presigned_s3(url)
            ):
                logger.info(f"Downloading {url} for deep probing (type={mime})")
                try:
                    with requests.get(url, stream=True, timeout=60) as resp_dl:
                        resp_dl.raise_for_status()
                        with NamedTemporaryFile(delete=False, suffix=".tmp") as tmpf:
                            for chunk in resp_dl.iter_content(chunk_size=8192):
                                if not chunk:
                                    break
                                tmpf.write(chunk)
                            temp_probe_file = Path(tmpf.name)
                        logger.info(f"Downloaded to temp file: {temp_probe_file}")
                except requests.RequestException as e:
                    logger.warning(f"Download failed for deep probe of {url}: {e}")
                    temp_probe_file = None
                except Exception as e:
                    logger.critical(f"Temp file write error for {url}: {e}")
                    temp_probe_file = None

        # 4) If we have a temp_probe_file, re‐probe size + MIME
        if temp_probe_file and temp_probe_file.exists():
            if not is_local:
                logger.info(f"Re‐probing temp file {temp_probe_file}")
            try:
                actual_size = temp_probe_file.stat().st_size
                if actual_size > size:
                    size = actual_size
                    logger.debug(f"Updated size from temp file: {_hr(size)}")
                new_mime = magic.Magic(mime=True).from_file(str(temp_probe_file))
                if new_mime:
                    mime = new_mime
                    logger.info(f"Updated MIME from temp file: {mime}")
            except Exception as e:
                logger.warning(f"Error re‐probing {temp_probe_file}: {e}")
        else:
            if size == 0 and not mime:
                logger.warning(
                    f"Unable to determine size/type for {url}; defaulting to octet-stream"
                )
                mime = "application/octet-stream"

        # Base metadata fields
        meta["file_size"] = _hr(size)
        meta["file_type"] = mime or "application/octet-stream"

        # ===== Deep probes by MIME =====

        # --- IMAGES: width × height (pixels) ---
        if mime.startswith("image/") and temp_probe_file and temp_probe_file.exists():
            try:
                with Image.open(temp_probe_file) as img:
                    w_px, h_px = img.width, img.height
                    meta["image_dimensions"] = (w_px, h_px)
                    logger.debug(f"Image dims: {w_px}×{h_px} px for {url}")
            except Exception as e:
                logger.warning(f"Failed to read image dimensions for {url}: {e}")

        # --- PDF: page count, page size mm, iso_page_size or explicit dims ---
        elif mime == "application/pdf" and temp_probe_file and temp_probe_file.exists():
            try:
                with open(temp_probe_file, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    page_count = len(reader.pages)
                    meta["page_count"] = page_count
                    logger.debug(f"PDF pages: {page_count} for {url}")

                    # Take MediaBox of first page
                    first_page = reader.pages[0]
                    media_box = first_page.mediabox
                    # MediaBox coords are in PDF points (1 point = 1/72 inch)
                    llx = float(media_box.lower_left[0])
                    lly = float(media_box.lower_left[1])
                    urx = float(media_box.upper_right[0])
                    ury = float(media_box.upper_right[1])
                    width_pt = urx - llx
                    height_pt = ury - lly

                    # Convert points → inches → millimeters
                    width_in = width_pt / 72.0
                    height_in = height_pt / 72.0
                    width_mm = width_in * 25.4
                    height_mm = height_in * 25.4
                    w_mm_r = round(width_mm, 2)
                    h_mm_r = round(height_mm, 2)
                    meta["page_size_mm"] = (w_mm_r, h_mm_r)

                    # Determine ISO or explicit dimension
                    iso_name = _find_closest_iso_size(w_mm_r, h_mm_r)
                    meta["iso_page_size"] = iso_name
                    logger.debug(
                        f"PDF size: {w_mm_r}×{h_mm_r} mm → {iso_name} for {url}"
                    )
            except Exception as e:
                logger.warning(f"Could not extract PDF metadata for {url}: {e}")

        # --- AUDIO: duration (MP3) ---
        elif mime.startswith("audio/") and temp_probe_file and temp_probe_file.exists():
            try:
                audio = MP3(str(temp_probe_file))
                duration = audio.info.length
                meta["audio_duration"] = _format_duration(duration)
                logger.debug(f"Audio duration: {meta['audio_duration']} for {url}")
            except Exception as e:
                logger.warning(f"Failed to read audio duration for {url}: {e}")

        # --- VIDEO: dimensions + duration via ffprobe ---
        elif mime.startswith("video/") and temp_probe_file and temp_probe_file.exists():
            try:
                cmd = (
                    f"ffprobe -v quiet -print_format json -show_format -show_streams "
                    f"{shlex.quote(str(temp_probe_file))}"
                )
                completed = subprocess.run(
                    shlex.split(cmd), capture_output=True, text=True, timeout=30
                )
                if completed.returncode == 0 and completed.stdout:
                    info = json.loads(completed.stdout)
                    # Find first video stream
                    video_stream = next(
                        (
                            s
                            for s in info.get("streams", [])
                            if s.get("codec_type") == "video"
                        ),
                        None,
                    )
                    if video_stream:
                        w = video_stream.get("width")
                        h = video_stream.get("height")
                        if w and h:
                            meta["video_dimensions"] = (int(w), int(h))
                            logger.debug(f"Video dims: {w}×{h} for {url}")
                    fmt = info.get("format", {})
                    dur_str = fmt.get("duration")
                    if dur_str:
                        dur = float(dur_str)
                        meta["video_duration"] = _format_duration(dur)
                        logger.debug(
                            f"Video duration: {meta['video_duration']} for {url}"
                        )
                else:
                    logger.warning(f"ffprobe error for {url}: {completed.stderr}")
            except Exception as e:
                logger.warning(f"Error running ffprobe on {url}: {e}")

        # --- DOCX: paragraph & word counts ---
        elif (
            mime
            in (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/msword",
            )
            and temp_probe_file
            and temp_probe_file.exists()
        ):
            try:
                doc = DocxDocument(str(temp_probe_file))
                paras = [p.text for p in doc.paragraphs if p.text]
                para_count = len(paras)
                word_count = sum(len(p.split()) for p in paras)
                meta["paragraph_count"] = para_count
                meta["word_count"] = word_count
                logger.debug(f"DOCX paras={para_count}, words={word_count} for {url}")
            except Exception as e:
                logger.warning(f"Failed to read DOCX metadata for {url}: {e}")

        # --- PPTX: slide count + slide size (mm) + ISO or explicit dims ---
        elif (
            mime
            == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            and temp_probe_file
            and temp_probe_file.exists()
        ):
            try:
                prs = Presentation(str(temp_probe_file))
                slide_count = len(prs.slides)
                meta["slide_count"] = slide_count
                logger.debug(f"PPTX slides: {slide_count} for {url}")

                # Slide dimensions are in EMU (English Metric Units)
                # 1 inch = 914400 EMU; 1 inch = 25.4 mm
                emu_per_inch = 914400.0
                w_emu = prs.slide_width
                h_emu = prs.slide_height
                w_in = w_emu / emu_per_inch
                h_in = h_emu / emu_per_inch
                w_mm = w_in * 25.4
                h_mm = h_in * 25.4
                w_mm_r = round(w_mm, 2)
                h_mm_r = round(h_mm, 2)
                meta["slide_size_mm"] = (w_mm_r, h_mm_r)

                iso_slide = _find_closest_iso_size(w_mm_r, h_mm_r)
                meta["iso_slide_size"] = iso_slide
                logger.debug(f"PPTX size: {w_mm_r}×{h_mm_r} mm → {iso_slide} for {url}")
            except Exception as e:
                logger.warning(f"Failed to read PPTX metadata for {url}: {e}")

        # --- XLSX: sheet count ---
        elif (
            mime
            in (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.ms-excel",
            )
            and temp_probe_file
            and temp_probe_file.exists()
        ):
            try:
                wb = openpyxl.load_workbook(
                    str(temp_probe_file), read_only=True, data_only=True
                )
                sheet_count = len(wb.sheetnames)
                meta["sheet_count"] = sheet_count
                logger.debug(f"XLSX sheets: {sheet_count} for {url}")
            except Exception as e:
                logger.warning(f"Failed to read XLSX metadata for {url}: {e}")

        # --- ODT: paragraph count ---
        elif (
            mime == "application/vnd.oasis.opendocument.text"
            and temp_probe_file
            and temp_probe_file.exists()
        ):
            try:
                odt = load_odt(str(temp_probe_file))
                paras = odt.getElementsByType(P)
                meta["paragraph_count_odt"] = len(paras)
                logger.debug(f"ODT paras: {len(paras)} for {url}")
            except Exception as e:
                logger.warning(f"Failed to read ODT metadata for {url}: {e}")

        # ----- Clean up temporary file if we downloaded one -----
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
