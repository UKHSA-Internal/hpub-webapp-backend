#!/usr/bin/env python3
import os
import sys
import re
import json
import unicodedata
import logging
import csv
import boto3
import psycopg2
from psycopg2 import extras
import pandas as pd
import urllib.parse
from urllib.parse import quote
from typing import Optional, Tuple

LOG_FILENAME = "transfer_product_artifacts.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILENAME, mode="w"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

sys.path.append(os.path.abspath(os.path.join(__file__, "../../..")))
from configs.get_secret_config import Config  # noqa: E402
from extract_file_metadata import get_file_metadata  # noqa: E402

config = Config()
BUCKET_NAME = config.get_hpub_s3_bucket_name()
s3 = boto3.client("s3")

PG = {
    "host": config.get_db_host(),
    "port": config.get_db_port(),
    "dbname": config.get_db_name(),
    "user": config.get_db_user(),
    "password": config.get_db_password().strip(),
}

LOCAL_DIR = "./files/"
EXCEL_PATH = "./files/updated_lookup_data_live.xlsx"
MISSING_LOG = "./files/missing_links_live_pub.csv"

ALLOWED_EXTS = {
    "main_download_file_name": {"jpg", "jpeg", "png", "gif"},
    "transcript_file_name": {"txt"},
    "web_download_file_name": {
        "jpg",
        "jpeg",
        "png",
        "mp4",
        "mov",
        "avi",
        "pdf",
        "pptx",
        "gif",
        "mp3",
        "wav",
        "txt",
        "docx",
        "doc",
        "odt",
        "ppt",
        "xlsx",
        "xslx",
    },
    "print_download_file_name": {
        "pdf",
        "gif",
        "png",
        "jpg",
        "jpeg",
        "docx",
        "doc",
        "odt",
        "ppt",
        "xlsx",
        "xslx",
    },
}

EXCEL_TO_DB = {
    "main_download_file_name": "main_download_url",
    "transcript_file_name": "transcript_url",
    "web_download_file_name": "web_download_url",
    "print_download_file_name": "print_download_url",
    "video_urls": "video_url",  # handled separately (YouTube link)
}

DOWNLOAD_COLUMNS = [k for k in EXCEL_TO_DB.keys() if k != "video_urls"]
OBJECT_KEYS = {"main_download_url", "video_url"}

missing_entries = []


def normalize_smart_quotes(name: str) -> str:
    return name.replace("‘", "'").replace("’", "'")


def sanitize_filename(name: str) -> str:
    name = normalize_smart_quotes(name)
    nkfd = unicodedata.normalize("NFKD", name)
    ascii_bytes = nkfd.encode("ascii", "ignore")
    ascii_str = ascii_bytes.decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", ascii_str)
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned.strip("._")


def content_disposition_header(original_filename: str) -> str:
    orig_nfc = unicodedata.normalize("NFC", original_filename)
    quoted = quote(orig_nfc, encoding="utf-8", safe="")
    return f"attachment; filename*=UTF-8''{quoted}"


def find_local_filename(directory: str, original: str) -> Optional[str]:
    target = sanitize_filename(original)
    try:
        for fname in os.listdir(directory):
            if sanitize_filename(fname) == target:
                return fname
    except FileNotFoundError:
        logger.error("Local directory does not exist: %s", directory)
    return None


def get_update_ref_id(cur, product_code: str) -> Optional[int]:
    cur.execute(
        "SELECT update_ref_id FROM public.products_product WHERE product_code = %s",
        (product_code,),
    )
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def fetch_current_downloads(cur, update_ref_id) -> Optional[dict]:
    cur.execute(
        "SELECT product_downloads FROM public.products_productupdate WHERE page_ptr_id = %s",
        (update_ref_id,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def ensure_s3_object(local_path: str, s3_key: str):
    try:
        s3.head_object(Bucket=BUCKET_NAME, Key=s3_key)
        logger.info("    S3 object exists: %s", s3_key)
    except s3.exceptions.ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "404":
            s3.upload_file(
                local_path,
                BUCKET_NAME,
                s3_key,
                ExtraArgs={"ServerSideEncryption": "AES256"},
            )
            logger.info("    Uploaded to S3: %s", s3_key)
        else:
            raise


def generate_presigned_get(
    bucket: str, key: str, original_filename: str, expires: int = 3600
) -> str:
    cd = content_disposition_header(original_filename)
    return s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": bucket, "Key": key, "ResponseContentDisposition": cd},
        ExpiresIn=expires,
    )


def canonicalize_youtube_url(url: str) -> Optional[str]:
    parsed = urllib.parse.urlparse(url.strip())
    netloc = parsed.netloc.lower()

    # Direct video link (standard or youtu.be)
    if "youtu.be" in netloc:
        video_id = parsed.path.lstrip("/")
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"

    elif "youtube.com" in netloc:
        if parsed.path.startswith("/watch"):
            qs = urllib.parse.parse_qs(parsed.query)
            video_id = qs.get("v", [None])[0]
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"

        # Shorts support
        if parsed.path.startswith("/shorts/"):
            parts = parsed.path.split("/")
            if len(parts) >= 3:
                return f"https://www.youtube.com/shorts/{parts[2]}"

        # Handle channel URLs or @handle pages
        if parsed.path.startswith("/channel/") or parsed.path.startswith("/@"):
            # This is a channel or @handle. Accept as-is.
            return url

        # Fallback: /user/ or /c/ or /playlist or /@handle (featured etc.)
        if any(
            parsed.path.startswith(prefix)
            for prefix in ["/user/", "/c/", "/playlist", "/@"]
        ):
            return url

    # Not a recognized YouTube URL
    return None


def normalize_existing_field(existing_value):
    if existing_value is None:
        return None
    if isinstance(existing_value, str):
        try:
            parsed = json.loads(existing_value)
            return parsed
        except Exception:
            return None
    return existing_value


### !!! THE KEY FUNCTION THAT GUARANTEES ONLY ONE ENTRY, ALL STUBS GONE !!!
def update_db(cur, update_ref_id, db_field: str, metadata: dict) -> bool:
    """
    Purges ALL stub/0-byte/filename-only entries for the field, and leaves only the latest.
    """
    current = fetch_current_downloads(cur, update_ref_id) or {}
    arr = normalize_existing_field(current.get(db_field)) or []
    if not isinstance(arr, list):
        arr = []

    # Remove any 0-bytes, filename-only, empty, or stub entries
    def is_valid(entry):
        if not isinstance(entry, dict):
            return False
        url = entry.get("URL", "") or ""
        fs = entry.get("file_size", "") or ""
        # valid must have > 0 size and must be a URL or full S3 path (not filename only)
        if not url.startswith("http"):
            return False
        try:
            size_val = float(
                str(fs).replace("KB", "").replace("MB", "").replace("Bytes", "").strip()
            )
            if "MB" in str(fs):
                size_val *= 1000
            if size_val < 10:  # Less than 10 bytes? not a real file.
                return False
        except Exception:
            return False
        return True

    # Always remove everything except the new metadata (which must be valid)
    new_arr = []
    # Optionally: only keep entries that are valid AND not the same as the incoming file
    # (But we want only one: the new one.)
    if is_valid(metadata):
        new_arr = [metadata]
    else:
        logger.warning(f"  Refused to insert invalid metadata: {metadata}")
        return False

    path = f"{{{db_field}}}"

    cur.execute(
        """
        UPDATE public.products_productupdate
           SET product_downloads = jsonb_set(
               COALESCE(product_downloads,'{}'::jsonb),
               %s,
               %s::jsonb,
               true
           )
         WHERE page_ptr_id = %s
        """,
        (path, extras.Json(new_arr), update_ref_id),
    )
    return True


def insert_db(cur, update_ref_id, db_field: str, metadata: dict):
    downloads = {db_field: metadata if db_field in OBJECT_KEYS else [metadata]}
    cur.execute(
        """
        INSERT INTO public.products_productupdate (
            page_ptr_id, minimum_stock_level, maximum_order_quantity,
            quantity_available, run_to_zero, available_from_choice,
            order_from_date, order_end_date, product_type,
            alternative_type, cost_centre, local_code,
            unit_of_measure, summary_of_guidance,
            product_downloads, main_download_url,
            video_url, print_download_url,
            web_download_url, transcript_url,
            order_referral_email_address, stock_owner_email_address,
            order_exceptions
        ) VALUES (
            %s, NULL, NULL, 0, NULL, NULL, NULL, NULL, NULL,
            NULL, NULL, NULL, NULL, NULL,
            %s, %s, %s, %s, %s, %s, NULL, NULL, NULL
        )
    """,
        (
            update_ref_id,
            extras.Json(downloads),
            extras.Json(downloads.get("main_download_url", {})),
            extras.Json(downloads.get("video_url", {})),
            extras.Json(downloads.get("print_download_url", [])),
            extras.Json(downloads.get("web_download_url", [])),
            extras.Json(downloads.get("transcript_url", [])),
        ),
    )


def _connect_db():
    try:
        conn = psycopg2.connect(**PG)
        cur = conn.cursor()
        logger.info("Connected to PostgreSQL.")
        return conn, cur
    except Exception as e:
        logger.error("DB connection failed: %s", e)
        sys.exit(1)


def _load_dataframe(path: str) -> pd.DataFrame:
    try:
        df = pd.read_excel(path, dtype=str).fillna("")
        logger.info("Loaded %d rows from Excel.", len(df))
        return df
    except Exception as e:
        logger.error("Excel read failed: %s", e)
        sys.exit(1)


def _report_missing():
    if not missing_entries:
        logger.info("No missing links or data detected.")
        return
    logger.warning(
        "Detected %d missing entries, see %s", len(missing_entries), MISSING_LOG
    )
    with open(MISSING_LOG, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["product_code", "column", "reason"])
        for rec in missing_entries:
            writer.writerow(rec)


def _process_rows(df: pd.DataFrame, cur, conn) -> Tuple[int, int]:
    processed = skipped = 0
    for idx, row in df.iterrows():
        p, s = _process_row(idx, row, cur, conn)
        processed += p
        skipped += s
    return processed, skipped


def _process_row(idx: int, row: pd.Series, cur, conn) -> Tuple[int, int]:
    processed = skipped = 0
    product_code = row.get("product_code", "").strip()
    tag = row.get("tag", "").strip().lower()

    logger.info("Row %d → product_code=%s, tag=%s", idx + 1, product_code, tag)
    if tag == "order-only" and not row.get("main_download_file_name", "").strip():
        reason = "order-only without main_download"
        missing_entries.append((product_code, "main_download", reason))
        logger.warning("  %s; skipping", reason)
        return 0, 1

    update_ref_id = get_update_ref_id(cur, product_code)
    if not update_ref_id:
        reason = "no update_ref_id"
        missing_entries.append((product_code, "all", reason))
        logger.warning("  %s for %s; skipping", reason, product_code)
        return 0, 1

    has_row = fetch_current_downloads(cur, update_ref_id) is not None

    for col in DOWNLOAD_COLUMNS:
        p, s, has_row = _process_column(
            cur, conn, update_ref_id, product_code, col, row, has_row
        )
        processed += p
        skipped += s

    # handle YouTube link separately
    p_vid, s_vid, has_row = _process_video_urls(
        cur, conn, update_ref_id, product_code, row, has_row
    )
    processed += p_vid
    skipped += s_vid

    return processed, skipped


def _process_column(cur, conn, update_ref_id, product_code, col, row, has_row):
    original = row.get(col, "").strip()
    if not original:
        return 0, 0, has_row  # nothing to do

    # If your data is ever comma-separated, handle as a list; else, just wrap as list
    files = [f.strip() for f in original.split(",") if f.strip()]
    if not files:
        return 0, 0, has_row

    processed = skipped = 0
    for fname in files:
        ext = os.path.splitext(fname)[1].lower().lstrip(".")
        if ext not in ALLOWED_EXTS.get(col, set()):
            reason = f"extension '{ext}' not allowed"
            missing_entries.append((product_code, col, reason))
            logger.warning("  %s; skipping", reason)
            skipped += 1
            continue

        matched = find_local_filename(LOCAL_DIR, fname)
        if not matched:
            reason = "file missing locally"
            missing_entries.append((product_code, col, reason))
            logger.warning("  %s for %s; skipping", reason, fname)
            skipped += 1
            continue

        local_path = os.path.join(LOCAL_DIR, matched)
        safe_name = sanitize_filename(fname)
        s3_key = f"{product_code}/{safe_name}"

        try:
            ensure_s3_object(local_path, s3_key)
            presigned = generate_presigned_get(BUCKET_NAME, s3_key, fname)
            md = get_file_metadata([presigned])[0]
        except Exception as e:
            reason = f"Error processing file: {e}"
            missing_entries.append((product_code, col, reason))
            logger.error("  %s", reason)
            skipped += 1
            continue

        metadata = {
            "URL": presigned,
            "s3_bucket_url": f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}",
            "file_size": md.get("file_size"),
            "file_type": md.get("file_type"),
        }
        db_field = EXCEL_TO_DB[col]

        try:
            if has_row:
                updated = update_db(cur, update_ref_id, db_field, metadata)
                action = "updated" if updated else "exists"
            else:
                insert_db(cur, update_ref_id, db_field, metadata)
                has_row = True
                action = "inserted"
            conn.commit()
            logger.info("  %s %s → %s", action, product_code, db_field)
            processed += 1
        except Exception as e:
            conn.rollback()
            reason = f"DB write failed: {e}"
            missing_entries.append((product_code, db_field, reason))
            logger.error("  %s", reason)
            skipped += 1

    return processed, skipped, has_row


def _process_video_urls(cur, conn, update_ref_id, product_code, row, has_row):
    original = row.get("video_urls", "").strip()
    if not original:
        return 0, 0, has_row

    urls = [u.strip() for u in original.split(",") if u.strip()]
    if not urls:
        return 0, 0, has_row

    first_url = urls[0]
    canonical = canonicalize_youtube_url(first_url)
    if not canonical:
        reason = "invalid YouTube URL"
        missing_entries.append((product_code, "video_urls", reason))
        logger.warning("  %s; skipping: %s", reason, first_url)
        return 0, 1, has_row

    metadata = {
        "URL": canonical,
        "original": first_url,
        "type": "youtube",
    }
    db_field = EXCEL_TO_DB["video_urls"]  # should be "video_url"

    try:
        if has_row:
            updated = update_db(cur, update_ref_id, db_field, metadata)
            action = "updated" if updated else "exists"
        else:
            insert_db(cur, update_ref_id, db_field, metadata)
            has_row = True
            action = "inserted"
        conn.commit()
        logger.info("  %s %s → %s (YouTube link)", action, product_code, db_field)
        return (1 if action in ("updated", "inserted") else 0), 0, has_row
    except Exception as e:
        conn.rollback()
        reason = f"DB write failed: {e}"
        missing_entries.append((product_code, db_field, reason))
        logger.error("  %s", reason)
        return 0, 1, has_row


def main():
    conn, cur = _connect_db()
    df = _load_dataframe(EXCEL_PATH)
    processed, skipped = _process_rows(df, cur, conn)
    _report_missing()
    cur.close()
    conn.close()
    logger.info("Done: processed=%d, skipped=%d", processed, skipped)


if __name__ == "__main__":
    main()
