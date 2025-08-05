import logging
from typing import Dict, Union, List
import importlib
import json

from rest_framework import serializers
from core.utils.extract_file_metadata import get_file_metadata

logger = logging.getLogger(__name__)

DEFAULT_FILE_SIZE = "0 Bytes"
DEFAULT_FILE_TYPE = "application/octet-stream"


def _get_file_metadata_serializer():
    """
    Lazy‐import to avoid circular reference. Called only after
    core.products.serializers has finished initialising.
    """
    module = importlib.import_module("core.products.serializers")
    return module.FileMetadataSerializer


def _minimal_stub_for_url(url: str) -> Dict:
    """
    Return a minimal, GDS‐compliant stub for a URL if we cannot retrieve real metadata.
    Uses DEFAULT_FILE_SIZE for size and "application/octet-stream" for MIME.
    """
    return {
        "URL": url,
        "file_size": DEFAULT_FILE_SIZE,
        "file_type": DEFAULT_FILE_TYPE,
        "s3_bucket_url": url,
    }


def _get_url_metadata(url: str) -> Dict:
    """
    Try to fetch real metadata for a URL. If that fails or returns empty, return a minimal stub.
    """
    try:
        meta_list = get_file_metadata([url])
    except Exception as e:
        logger.warning("Error calling get_file_metadata(%s): %s", url, e)
        return _minimal_stub_for_url(url)

    if meta_list:
        return meta_list[0]
    return _minimal_stub_for_url(url)


def _normalise_entry(entry: Union[str, Dict]) -> Dict:
    """
    Normalize an entry (string or dict) into a complete metadata dict.
    """
    # If entry is a string, treat it as a URL
    if isinstance(entry, str):
        return _get_url_metadata(entry)

    # If entry is a dict, fill in missing fields
    if isinstance(entry, dict):
        url = entry.get("URL", "")
        if url:
            base = _get_url_metadata(url)
        else:
            base = {
                "URL": "",
                "file_size": DEFAULT_FILE_SIZE,
                "file_type": DEFAULT_FILE_TYPE,
                "s3_bucket_url": "",
            }

        # Merge explicit fields from entry over base metadata
        merged = {**base, **entry}
        merged.setdefault("URL", "")
        merged.setdefault("file_size", base.get("file_size", DEFAULT_FILE_SIZE))
        merged.setdefault("file_type", base.get("file_type", DEFAULT_FILE_TYPE))
        merged.setdefault("s3_bucket_url", base.get("s3_bucket_url", ""))

        return merged

    # Unexpected type: return empty stub
    logger.warning("Unexpected entry type in _normalise_entry: %r", entry)
    return {
        "URL": "",
        "file_size": DEFAULT_FILE_SIZE,
        "file_type": DEFAULT_FILE_TYPE,
        "s3_bucket_url": "",
    }


def parse_downloads(download_data) -> Dict[str, Union[str, List[Dict]]]:
    """
    Parses a JSON‐like structure of downloads, normalizing each entry
    so that `FileMetadataSerializer` always sees a consistent dict.
    """
    if not download_data:
        return {
            "main_download_url": None,
            "video_url": None,
            "web_download_url": [],
            "print_download_url": [],
            "transcript_url": [],
        }

    # Accept JSON string or already‐decoded dict
    if isinstance(download_data, str):
        try:
            download_data = json.loads(download_data)
        except json.JSONDecodeError:
            logger.warning("Downloads JSON malformed – returning empty structure")
            return {
                "main_download_url": None,
                "video_url": None,
                "web_download_url": [],
                "print_download_url": [],
                "transcript_url": [],
            }

    file_metadata_serializer = _get_file_metadata_serializer()

    def _build_list(lst):
        out = []
        for raw in lst or []:  # Always treat None as empty list
            normalized = _normalise_entry(raw)
            try:
                out.append(file_metadata_serializer(normalized).data)
            except serializers.ValidationError as exc:
                logger.warning("Skipping invalid file metadata entry: %s", exc)
        return out

    return {
        "main_download_url": download_data.get("main_download_url"),
        "video_url": download_data.get("video_url"),
        "web_download_url": _build_list(download_data.get("web_download_url")),
        "print_download_url": _build_list(download_data.get("print_download_url")),
        "transcript_url": _build_list(download_data.get("transcript_url")),
    }
