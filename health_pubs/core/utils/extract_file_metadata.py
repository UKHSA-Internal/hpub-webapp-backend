import logging
from pathlib import Path
from tempfile import NamedTemporaryFile

import magic
import moviepy.editor as mp
import openpyxl
import PyPDF2
import requests
from docx import Document
from mutagen.mp3 import MP3
from odf.opendocument import load as load_odt
from PIL import Image, ImageSequence
from pptx import Presentation

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- ISO A-series sizes in millimetres ---
ISO_A_SIZES_MM = {
    "A0": (841, 1189),
    "A1": (594, 841),
    "A2": (420, 594),
    "A3": (297, 420),
    "A4": (210, 297),
    "A5": (148, 210),
    "A6": (105, 148),
}


def download_from_presigned_url(presigned_url):
    with NamedTemporaryFile(delete=False) as tmp:
        with requests.get(presigned_url, stream=True) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_content(10 * 1024 * 1024):  # 10 MB at a time
                tmp.write(chunk)
        return tmp.name


def convert_file_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} Bytes"
    if size_bytes < 1024**2:
        return f"{size_bytes / 1024:.2f} KB"
    if size_bytes < 1024**3:
        return f"{size_bytes / (1024**2):.2f} MB"
    return f"{size_bytes / (1024**3):.2f} GB"


def format_duration(seconds):
    if seconds < 60:
        return f"{seconds:.2f} seconds"
    if seconds < 3600:
        return f"{seconds/60:.2f} minutes"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours} hours {minutes} minutes"


def points_to_mm(pt):
    """Convert PDF points (1 pt = 1/72 in) to millimetres."""
    return (pt / 72) * 25.4


def detect_iso_page_size(width_pt, height_pt):
    """
    Always return the closest ISO A-series size name for given dimensions in points.
    """
    w_mm = points_to_mm(width_pt)
    h_mm = points_to_mm(height_pt)
    best_name, best_delta = None, float("inf")
    for name, (std_w, std_h) in ISO_A_SIZES_MM.items():
        # check both orientations
        delta1 = abs(w_mm - std_w) + abs(h_mm - std_h)
        delta2 = abs(w_mm - std_h) + abs(h_mm - std_w)
        delta = min(delta1, delta2)
        if delta < best_delta:
            best_name, best_delta = name, delta
    return best_name


def get_pdf_metadata(file_path):
    with open(file_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        num_pages = len(reader.pages)
        box = reader.pages[0].mediabox
        w_pt, h_pt = float(box.width), float(box.height)
        dimensions_pt = (w_pt, h_pt)
        page_size = detect_iso_page_size(w_pt, h_pt)
    return num_pages, dimensions_pt, page_size


def get_video_duration(file_path):
    return mp.VideoFileClip(file_path).duration


def get_audio_duration(file_path):
    return MP3(file_path).info.length


def get_image_dimensions(file_path):
    with Image.open(file_path) as img:
        return img.size  # (width, height)


def get_pptx_metadata(file_path):
    return len(Presentation(file_path).slides)


def get_xlsx_metadata(file_path):
    return len(openpyxl.load_workbook(file_path, read_only=True).sheetnames)


def get_odt_metadata(file_path):
    return len(load_odt(file_path).getElementsByType("text:p"))


def get_gif_duration(file_path):
    with Image.open(file_path) as img:
        total_ms = sum(fr.info.get("duration", 0) for fr in ImageSequence.Iterator(img))
    return total_ms / 1000.0


def get_docx_metadata(file_path):
    return len(Document(file_path).paragraphs)


def get_file_metadata(presigned_urls):
    results = []
    for url in presigned_urls:
        logger.info("Processing URL: %s", url)
        try:
            path = download_from_presigned_url(url)
            size = Path(path).stat().st_size
            hr_size = convert_file_size(size)
            mime = magic.Magic(mime=True).from_file(path)

            md = {
                "URL": url,
                "file_size": hr_size,
                "file_type": mime,
            }

            if mime == "application/pdf":
                pages, dims, layout = get_pdf_metadata(path)
                md.update(
                    {
                        "number_of_pages": pages,
                        "dimensions_pt": dims,
                        "page_size": layout,
                    }
                )

            elif mime.startswith("video/"):
                dur = get_video_duration(path)
                md["duration"] = format_duration(dur)

            elif mime.startswith("audio/"):
                dur = get_audio_duration(path)
                md["duration"] = format_duration(dur)

            elif mime.startswith("image/"):
                md["dimensions"] = get_image_dimensions(path)

            elif (
                mime
                == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            ):
                slides = get_pptx_metadata(path)
                md["number_of_slides"] = slides
                md["number_of_pages"] = slides

            elif (
                mime
                == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ):
                sheets = get_xlsx_metadata(path)
                md["number_of_pages"] = sheets

            elif mime == "application/vnd.oasis.opendocument.text":
                paras = get_odt_metadata(path)
                md["number_of_paragraphs"] = paras

            elif mime == "image/gif":
                dur = get_gif_duration(path)
                md["duration"] = format_duration(dur)

            elif (
                mime
                == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ):
                paras = get_docx_metadata(path)
                md["number_of_paragraphs"] = paras

            results.append(md)

        except Exception as e:
            logger.error("Error processing %s: %s", url, e)

    logger.info("Completed metadata for %d files", len(results))
    return results
