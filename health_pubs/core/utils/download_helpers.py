# core/utils/download_helpers.py
import logging
from typing import Dict, List, Union

import importlib
from rest_framework import serializers

from core.utils.extract_file_metadata import get_file_metadata

logger = logging.getLogger(__name__)


def _get_file_metadata_serializer():
    """
    Lazy-import to avoid circular reference. Called only after
    core.products.serializers has finished initialising.
    """
    module = importlib.import_module("core.products.serializers")
    return module.FileMetadataSerializer


def _normalise_entry(entry: Union[str, Dict]) -> Dict:
    if isinstance(entry, str):
        meta = get_file_metadata([entry])
        return (
            meta[0]
            if meta
            else {
                "URL": entry,
                "file_size": "Unknown",
                "file_type": "application/octet-stream",
                "s3_bucket_url": entry,
            }
        )

    defaults = {
        "file_size": "Unknown",
        "file_type": "application/octet-stream",
        "s3_bucket_url": entry.get("URL", ""),
    }
    return {**defaults, **entry}


def parse_downloads(download_data) -> Dict[str, Union[str, List[Dict]]]:
    if not download_data:
        return {
            "main_download_url": None,
            "video_url": None,
            "web_download_url": [],
            "print_download_url": [],
            "transcript_url": [],
        }

    # Accept JSON string or decoded dict
    if isinstance(download_data, str):
        import json

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

    FileMetadataSerializer = _get_file_metadata_serializer()  # <── lazy import

    def _build_list(lst):
        out = []
        for raw in lst:
            meta = _normalise_entry(raw)
            try:
                out.append(FileMetadataSerializer(meta).data)
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
