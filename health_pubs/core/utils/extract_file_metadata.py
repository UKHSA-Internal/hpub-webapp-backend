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


# Function to download file from pre-signed S3 URL
def download_from_presigned_url(presigned_url):
    with NamedTemporaryFile(delete=False) as tmp_file:
        response = requests.get(presigned_url)
        tmp_file.write(response.content)
        return tmp_file.name


# Function to convert file size to a human-readable format
def convert_file_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} Bytes"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / (1024 ** 2):.2f} MB"
    else:
        return f"{size_bytes / (1024 ** 3):.2f} GB"


# Function to convert duration in seconds to a human-readable format
def format_duration(seconds):
    if seconds < 60:
        return f"{seconds:.2f} seconds"
    elif seconds < 3600:
        return f"{seconds / 60:.2f} minutes"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{int(hours)} hours {int(minutes)} minutes"


# Function to extract metadata based on file type


def get_file_metadata(presigned_urls):
    metadata_list = []

    for presigned_url in presigned_urls:
        logger.info("Processing presigned URL: %s", presigned_url)

        # Download the file from the presigned URL
        try:
            file_path = download_from_presigned_url(presigned_url)
            logger.info("Downloaded file to: %s", file_path)

            # Check the file size
            file_size = Path(file_path).stat().st_size
            human_readable_size = convert_file_size(file_size)
            logger.info("File size: %s", human_readable_size)

            # Use python-magic to detect file type
            mime = magic.Magic(mime=True)
            file_type = mime.from_file(file_path)
            logger.info("Detected file type: %s", file_type)

            # Initialize the metadata dictionary
            metadata = {
                "URL": presigned_url,
                "file_size": human_readable_size,
                "file_type": file_type,
            }

            # Extract additional metadata based on file type
            if file_type == "application/pdf":
                num_pages, dimensions, page_size = get_pdf_metadata(file_path)
                metadata["number_of_pages"] = num_pages
                metadata["dimensions"] = dimensions
                metadata["page_size"] = page_size

            elif file_type.startswith("video/"):
                duration = get_video_duration(file_path)
                formatted_duration = format_duration(duration)
                metadata["duration"] = formatted_duration

            elif file_type.startswith("audio/"):
                duration = get_audio_duration(file_path)
                formatted_duration = format_duration(duration)
                metadata["duration"] = formatted_duration

            elif file_type.startswith("image/"):
                dimensions = get_image_dimensions(file_path)
                metadata["dimensions"] = dimensions

            elif (
                file_type
                == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            ):
                num_slides = get_pptx_metadata(file_path)
                metadata["number_of_slides"] = num_slides

            elif (
                file_type
                == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ):
                num_sheets = get_xlsx_metadata(file_path)
                metadata["Number_of_sheets"] = num_sheets

            elif file_type == "application/vnd.oasis.opendocument.text":
                num_paragraphs = get_odt_metadata(file_path)
                metadata["number_of_paragraphs"] = num_paragraphs

            elif file_type == "image/gif":
                duration = get_gif_duration(file_path)
                metadata["duration"] = format_duration(duration)

            elif (
                file_type
                == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ):
                num_paragraphs = get_docx_metadata(file_path)
                metadata["number_of_paragraphs"] = num_paragraphs

            # Append the metadata to the list
            metadata_list.append(metadata)

        except Exception as e:
            logger.error("Failed to process URL %s: %s", presigned_url, str(e))
            continue

    logger.info("Extracted metadata for %d files", len(metadata_list))
    return metadata_list


# Function to extract dimensions of an image
def get_image_dimensions(file_path):
    with Image.open(file_path) as img:
        return img.size  # Returns (width, height)


# file metadata extraction functions
def get_pdf_metadata(file_path):
    with open(file_path, "rb") as f:
        pdf_reader = PyPDF2.PdfReader(f)
        num_pages = len(pdf_reader.pages)
        # dimensions of the first page
        page_size = pdf_reader.pages[0].mediaBox
        dimensions = (page_size.getWidth(), page_size.getHeight())
    return num_pages, dimensions, page_size


def get_video_duration(file_path):
    video = mp.VideoFileClip(file_path)
    duration = video.duration  # duration in seconds
    return duration


def get_audio_duration(file_path):
    audio = MP3(file_path)
    duration = audio.info.length  # duration in seconds
    return duration


def get_pptx_metadata(file_path):
    presentation = Presentation(file_path)
    num_slides = len(presentation.slides)
    return num_slides


def get_xlsx_metadata(file_path):
    workbook = openpyxl.load_workbook(file_path, read_only=True)
    num_sheets = len(workbook.sheetnames)
    return num_sheets


def get_odt_metadata(file_path):
    doc = load_odt(file_path)
    num_paragraphs = len(doc.getElementsByType("text:p"))
    return num_paragraphs


def get_gif_duration(file_path):
    with Image.open(file_path) as img:
        duration = (
            sum(frame.info["duration"] for frame in ImageSequence.Iterator(img))
            / 1000.0
        )  # Convert to seconds
    return duration


def get_docx_metadata(file_path):
    doc = Document(file_path)
    num_paragraphs = len(doc.paragraphs)
    return num_paragraphs
