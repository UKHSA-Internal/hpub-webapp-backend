import logging
from typing import Dict, Union, List
import importlib
import json

from rest_framework import serializers
from core.utils.extract_file_metadata import get_file_metadata

logger = logging.getLogger(__name__)


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
    Uses "0 Bytes" for size and "application/octet-stream" for MIME.
    """
    return {
        "URL": url,
        "file_size": "0 Bytes",
        "file_type": "application/octet-stream",
        "s3_bucket_url": url,
    }


def _normalise_entry(entry: Union[str, Dict]) -> Dict:
    """
    If entry is a string, treat it as a URL and attempt to fetch real metadata.
    If get_file_metadata fails or returns an empty list, fall back to a minimal stub.

    If entry is already a dict, attempt to fill in any missing fields from
    get_file_metadata(entry["URL"]) if available.  Otherwise, fall back to a minimal stub.
    """
    # 1) If entry is just a string → URL
    if isinstance(entry, str):
        url = entry
        try:
            meta_list = get_file_metadata([url])
        except Exception as e:
            logger.warning("Error calling get_file_metadata(%s): %s", url, e)
            meta_list = []

        if meta_list:
            # Use the first (and only) element returned by get_file_metadata
            return meta_list[0]
        else:
            # Fallback stub
            return _minimal_stub_for_url(url)

    # 2) If entry is already a dict
    if isinstance(entry, dict):
        url = entry.get("URL")
        base_metadata: Dict = {}

        if url:
            # Try fetching real metadata if we have a URL field
            try:
                meta_list = get_file_metadata([url])
            except Exception as e:
                logger.warning("Error calling get_file_metadata(%s): %s", url, e)
                meta_list = []

            if meta_list:
                base_metadata = meta_list[0]
            else:
                base_metadata = _minimal_stub_for_url(url)
        else:
            # No URL at all—just provide a stub with no URL
            base_metadata = {
                "URL": "",
                "file_size": "0 Bytes",
                "file_type": "application/octet-stream",
                "s3_bucket_url": "",
            }

        # Now merge `entry` on top of base_metadata, so that any explicitly provided keys
        # in `entry` take precedence. Everything else is filled from base_metadata.
        merged = {**base_metadata, **entry}

        # Ensure that at least these keys exist, even if someone passed a dict missing them:
        merged.setdefault("URL", "")
        merged.setdefault("file_size", base_metadata.get("file_size", "0 Bytes"))
        merged.setdefault(
            "file_type", base_metadata.get("file_type", "application/octet-stream")
        )
        merged.setdefault("s3_bucket_url", base_metadata.get("s3_bucket_url", ""))

        return merged

    # 3) If entry is some unexpected type, return an empty stub with no URL
    logger.warning("Unexpected entry type in _normalise_entry: %r", entry)
    return {
        "URL": "",
        "file_size": "0 Bytes",
        "file_type": "application/octet-stream",
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
        for raw in lst:
            normalized = _normalise_entry(raw)
            try:
                out.append(file_metadata_serializer(normalized).data)
            except serializers.ValidationError as exc:
                logger.warning("Skipping invalid file metadata entry: %s", exc)
        return out

    return {
        "main_download_url": download_data.get("main_download_url"),
        "video_url": download_data.get("video_url"),
        "web_download_url": _build_list(download_data.get("web_download_url", [])),
        "print_download_url": _build_list(download_data.get("print_download_url", [])),
        "transcript_url": _build_list(download_data.get("transcript_url", [])),
    }
