#!/usr/bin/env python3
import os
import sys
import re
import json
import difflib
import unicodedata
import logging
import csv
import boto3
import psycopg2
from psycopg2 import extras
import pandas as pd
import urllib.parse
from urllib.parse import quote
from typing import Any, Dict, Optional, Tuple, List
import argparse

# ---------------------------
# Logging
# ---------------------------
LOG_FILENAME = "transfer_product_artifacts.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILENAME, mode="w", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------
# Local imports / Config
# ---------------------------
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
EXCEL_PATH_DEFAULT = "./files/updated_lookup_data_draft.xlsx"
MISSING_LOG = "./files/missing_links_drafts_pubs.csv"

# ---------------------------
# Constants / Mappings
# ---------------------------
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
    "video_urls": "video_url",
}

DOWNLOAD_COLUMNS = [k for k in EXCEL_TO_DB.keys() if k != "video_urls"]

# Fields that should store a single object (dict)
DOWNLOAD_OBJECT_FIELDS = {"main_download_url", "video_url"}
# Fields that should store an array of objects
DOWNLOAD_ARRAY_FIELDS = {"web_download_url", "print_download_url", "transcript_url"}
ALL_DOWNLOAD_FIELDS = DOWNLOAD_OBJECT_FIELDS | DOWNLOAD_ARRAY_FIELDS

# ---------------------------
# State
# ---------------------------
missing_entries: List[Tuple[str, str, str, str]] = []

# ---------------------------
# Filename helpers
# ---------------------------
def fix_mojibake(name: str) -> str:
    replacements = {
        "+ñ+": "-",
        "+í+": "-",
        "ñ": "-",
        "í": "i",
        "’": "",
        "“": "",
        "”": "",
        "ó": "o",
        "ú": "u",
        "á": "a",
        "é": "e",
        "–": "-",
        "—": "-",
        "‘": "",
        "’": "",
    }
    for k, v in replacements.items():
        name = name.replace(k, v)
    return name.replace("+", "_")


def sanitize_filename(name: str) -> str:
    name = fix_mojibake(name)
    nkfd = unicodedata.normalize("NFKD", name)
    ascii_str = nkfd.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_str).strip("._")
    return cleaned.lower()


def content_disposition_header(
    original_filename: str, disposition_type: str = "attachment"
) -> str:
    orig_nfc = unicodedata.normalize("NFC", original_filename)
    quoted = quote(orig_nfc, encoding="utf-8", safe="")
    return f"{disposition_type}; filename*=UTF-8''{quoted}"


def log_missing_local_file(original: str, target: str, directory: str):
    missing_log_path = "./files/missing_local_files.log"
    try:
        available = [sanitize_filename(f) for f in os.listdir(directory)]
    except Exception:
        available = []
    with open(missing_log_path, "a", encoding="utf-8") as logf:
        logf.write(
            f"No local file found for: {original} (normalized: {target}). "
            f"Available files (sanitized): {available}\n"
        )


def parse_filenames(cell: str) -> List[str]:
    # Split on commas NOT inside parentheses
    if not cell or not cell.strip():
        return []
    parts = []
    buf = ""
    depth = 0
    for ch in cell:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        if ch == "," and depth == 0:
            if buf.strip():
                parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf.strip())
    return parts


def get_extension(fname: str) -> str:
    fname = fname.strip()
    _, ext = os.path.splitext(fname)
    return ext.lstrip(".").lower()


def find_local_filename(directory: str, original: str) -> Optional[str]:
    """
    Try to match a file in 'directory' to the provided filename.
    Robust to casing, whitespace, + vs space, dashes, and unicode issues.
    Returns the actual filename if found, else None.
    """
    if not os.path.isdir(directory):
        logger.error("Local directory missing: %s", directory)
        return None

    def normalize(s: str) -> str:
        s = unicodedata.normalize("NFKD", s)
        s = s.replace("+", " ").replace("_", " ").replace("-", " ")
        s = s.strip().lower()
        s = re.sub(r"\s+", " ", s)
        return s

    target_norm = normalize(original)
    available = os.listdir(directory)
    norm_to_real = {normalize(f): f for f in available}

    # 1. Exact match (normalized)
    if target_norm in norm_to_real:
        return norm_to_real[target_norm]

    # 2. Fuzzy match
    closest = difflib.get_close_matches(
        target_norm, norm_to_real.keys(), n=1, cutoff=0.8
    )
    if closest:
        return norm_to_real[closest[0]]

    # 3. Extension-sensitive base match
    orig_base, orig_ext = os.path.splitext(original.strip().lower())
    for f in available:
        base, ext = os.path.splitext(f.lower())
        if ext == orig_ext and base.replace(" ", "") == orig_base.replace(" ", ""):
            return f

    # 4. Substring match
    for norm, real in norm_to_real.items():
        if target_norm in norm or norm in target_norm:
            return real

    # 5. Log and return None
    log_missing_local_file(original, target_norm, directory)
    return None


# ---------------------------
# S3 helpers
# ---------------------------
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
    bucket: str,
    key: str,
    original_filename: str,
    expires: int = 3600,
    is_main_download: bool = False,
) -> str:
    disposition_type = "inline" if is_main_download else "attachment"
    cd = content_disposition_header(
        original_filename, disposition_type=disposition_type
    )
    return s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": bucket, "Key": key, "ResponseContentDisposition": cd},
        ExpiresIn=expires,
    )


# ---------------------------
# URL helpers
# ---------------------------
def canonicalize_youtube_url(url: str) -> Optional[str]:
    if not url:
        return None
    parsed = urllib.parse.urlparse(url.strip())
    netloc = parsed.netloc.lower()
    if "youtu.be" in netloc:
        vid = parsed.path.lstrip("/")
        return f"https://www.youtube.com/watch?v={vid}" if vid else None
    if "youtube.com" in netloc:
        if parsed.path.startswith("/watch"):
            qs = urllib.parse.parse_qs(parsed.query)
            vid = qs.get("v", [None])[0]
            return f"https://www.youtube.com/watch?v={vid}" if vid else None
        if parsed.path.startswith("/shorts/"):
            parts = parsed.path.split("/")
            return (
                f"https://www.youtube.com/shorts/{parts[2]}" if len(parts) > 2 else None
            )
        if parsed.path.startswith(("/channel/", "/@", "/user/", "/c/", "/playlist")):
            return url
    return None


# ---------------------------
# Download JSON shape normalizers (the fixes)
# ---------------------------
URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _json_load_maybe(x: Any) -> Any:
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:
            return x
    return x


def _is_url(s: str) -> bool:
    return isinstance(s, str) and bool(URL_RE.match(s.strip()))


def _coerce_metadata_dict(x: Any) -> Optional[Dict[str, Any]]:
    """
    Coerce 'x' into a metadata dict containing at least: URL, file_size, file_type.
    If 'x' is a URL string, wrap it; otherwise return None if unusable.
    """
    if isinstance(x, dict):
        d = dict(x)
        if "URL" in d and isinstance(d["URL"], str) and _is_url(d["URL"]):
            d.setdefault("file_size", "Unknown")
            d.setdefault("file_type", "application/octet-stream")
            return d
        return None
    if _is_url(x):
        return {
            "URL": x.strip(),
            "file_size": "Unknown",
            "file_type": "application/octet-stream",
        }
    return None


def _uniq_by_url(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for it in items:
        url = it.get("URL")
        if isinstance(url, str) and url not in seen:
            seen.add(url)
            out.append(it)
    return out


def _normalize_downloads_shape(raw: Any) -> Dict[str, Any]:
    """
    Return a dict with guaranteed shapes:
      - object fields: dict or None
      - array fields: list[dict]
    Ignore/clean unexpected strings to avoid char-splitting.
    """
    if raw is None:
        base: Dict[str, Any] = {}
    else:
        base = _json_load_maybe(raw)
        if not isinstance(base, dict):
            base = {}

    out: Dict[str, Any] = {}

    # Object fields
    for f in DOWNLOAD_OBJECT_FIELDS:
        v = _json_load_maybe(base.get(f))
        md = _coerce_metadata_dict(v)
        out[f] = md  # may be None

    # Array fields
    for f in DOWNLOAD_ARRAY_FIELDS:
        v = _json_load_maybe(base.get(f))
        items: List[Dict[str, Any]] = []
        if isinstance(v, list):
            for elem in v:
                elem = _json_load_maybe(elem)
                md = _coerce_metadata_dict(elem)
                if md:
                    items.append(md)
        elif isinstance(v, (dict, str)):
            md = _coerce_metadata_dict(v)
            if md:
                items.append(md)
        out[f] = _uniq_by_url(items)

    # Ensure all keys present
    for f in ALL_DOWNLOAD_FIELDS:
        if f not in out:
            out[f] = None if f in DOWNLOAD_OBJECT_FIELDS else []

    return out


# ---------------------------
# DB helpers (rewritten)
# ---------------------------
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


def _fetch_product_downloads(cur, update_ref_id: int) -> Dict[str, Any]:
    cur.execute(
        "SELECT product_downloads FROM public.products_productupdate WHERE page_ptr_id = %s",
        (update_ref_id,),
    )
    row = cur.fetchone()
    raw = row[0] if row else None
    return _normalize_downloads_shape(raw)


def get_update_ref_id(cur, product_code: str) -> Optional[int]:
    cur.execute(
        "SELECT update_ref_id FROM public.products_product WHERE product_code = %s",
        (product_code,),
    )
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def update_db(cur, update_ref_id: int, db_field: str, metadata: Dict[str, Any]) -> bool:
    """
    For array fields → append (dedup by URL).
    For object fields → replace.
    Returns True if content changed.
    """
    if db_field not in ALL_DOWNLOAD_FIELDS:
        raise ValueError(f"Unknown download field: {db_field}")

    md = _coerce_metadata_dict(metadata)
    if not md:
        logger.warning("Refused to store invalid metadata payload: %s", metadata)
        return False

    current = _fetch_product_downloads(cur, update_ref_id)
    before = json.dumps(current, sort_keys=True)

    if db_field in DOWNLOAD_OBJECT_FIELDS:
        current[db_field] = md
    else:
        items = current.get(db_field) or []
        if not isinstance(items, list):
            items = []
        items.append(md)
        current[db_field] = _uniq_by_url(items)

    after = json.dumps(current, sort_keys=True)
    if after == before:
        return False

    cur.execute(
        """
        UPDATE public.products_productupdate
        SET product_downloads = %s
        WHERE page_ptr_id = %s
        """,
        (extras.Json(current), update_ref_id),
    )
    return True


def insert_db(cur, update_ref_id: int, db_field: str, metadata: Dict[str, Any]) -> None:
    """
    Creates minimal product_update row with product_downloads populated in correct shape.
    Other unrelated fields remain NULL.
    """
    if db_field not in ALL_DOWNLOAD_FIELDS:
        raise ValueError(f"Unknown download field: {db_field}")

    md = _coerce_metadata_dict(metadata)
    if not md:
        raise ValueError("Invalid metadata payload")

    downloads = _normalize_downloads_shape({})
    if db_field in DOWNLOAD_OBJECT_FIELDS:
        downloads[db_field] = md
    else:
        downloads[db_field] = [md]

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
            %s, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL
        )
        """,
        (update_ref_id, extras.Json(downloads)),
    )


# ---------------------------
# Processing helpers
# ---------------------------
def _report_missing():
    if not missing_entries:
        logger.info("No missing links or data detected.")
        return
    logger.warning(
        "Detected %d missing entries, see %s", len(missing_entries), MISSING_LOG
    )
    os.makedirs(os.path.dirname(MISSING_LOG), exist_ok=True)
    with open(MISSING_LOG, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["product_code", "column", "reason", "file_name"])
        for rec in missing_entries:
            writer.writerow(rec)


def _process_rows(df: pd.DataFrame, cur, conn) -> Tuple[int, int]:
    processed = skipped = 0
    for idx, row in df.iterrows():
        p, s = _process_row(idx, row, cur, conn)
        processed += p
        skipped += s
    return processed, skipped


def is_valid_file_value(val: str) -> bool:
    return bool(
        val and val.strip() and val.strip().lower() not in {"n/a", "na", "-", ""}
    )


def _process_row(idx: int, row: pd.Series, cur, conn) -> Tuple[int, int]:
    processed = skipped = 0
    code = (row.get("product_code") or "").strip()
    tag = (row.get("tag") or "").strip().lower()
    logger.info("Row %d → product_code=%s, tag=%s", idx + 1, code, tag)

    if not code:
        missing_entries.append(("", "all", "missing product_code", ""))
        logger.warning("  missing product_code; skipping row")
        return 0, 1

    # Business rule: example kept from original
    if tag == "order-only" and not (row.get("main_download_file_name") or "").strip():
        missing_entries.append(
            (code, "main_download", "order-only without main_download", "")
        )
        logger.warning("  order-only without main_download; skipping")
        return 0, 1

    ref_id = get_update_ref_id(cur, code)
    if not ref_id:
        missing_entries.append((code, "all", "no update_ref_id", ""))
        logger.warning("  no update_ref_id for %s; skipping", code)
        return 0, 1

    # Determine if product_update row exists
    cur.execute(
        "SELECT 1 FROM public.products_productupdate WHERE page_ptr_id=%s",
        (ref_id,),
    )
    has_row = cur.fetchone() is not None

    # Files columns
    for col in DOWNLOAD_COLUMNS:
        p, s, has_row = _process_column(cur, conn, ref_id, code, col, row, has_row)
        processed += p
        skipped += s

    # Video urls column
    p2, s2, has_row = _process_video_urls(cur, conn, ref_id, code, row, has_row)
    processed += p2
    skipped += s2

    return processed, skipped


def _process_column(cur, conn, ref_id, prod_code, col, row, has_row):
    original = (row.get(col) or "").strip()
    if not is_valid_file_value(original):
        return 0, 0, has_row

    fname = original
    ext = get_extension(fname)
    if ext not in ALLOWED_EXTS.get(col, set()):
        missing_entries.append(
            (prod_code, col, f"extension '{ext}' not allowed", fname)
        )
        logger.warning("  extension '%s' not allowed; skipping %s", ext, fname)
        return 0, 1, has_row

    matched = find_local_filename(LOCAL_DIR, fname)
    if not matched:
        missing_entries.append((prod_code, col, "file missing locally", fname))
        logger.warning("  file missing locally for %s; skipping", fname)
        return 0, 1, has_row

    local_path = os.path.join(LOCAL_DIR, matched)
    safe_name = sanitize_filename(fname)
    key = f"{prod_code}/{safe_name}"

    try:
        ensure_s3_object(local_path, key)
        presigned = generate_presigned_get(
            BUCKET_NAME,
            key,
            fname,
            is_main_download=(col == "main_download_file_name"),
        )
        md = get_file_metadata([presigned])[0]  # expects list of URLs
    except Exception as e:
        missing_entries.append((prod_code, col, f"Error processing file: {e}", fname))
        logger.error("  Error processing file: %s", e)
        return 0, 1, has_row

    metadata = {
        "URL": presigned,
        "s3_bucket_url": f"https://{BUCKET_NAME}.s3.amazonaws.com/{key}",
        "file_size": md.get("file_size", "Unknown"),
        "file_type": md.get("file_type", "application/octet-stream"),
    }
    db_field = EXCEL_TO_DB[col]

    try:
        if has_row:
            updated = update_db(cur, ref_id, db_field, metadata)
            action = "updated" if updated else "no-op"
        else:
            insert_db(cur, ref_id, db_field, metadata)
            has_row = True
            action = "inserted"
        conn.commit()
        logger.info("  %s %s → %s", action, prod_code, db_field)
        return 1, 0, has_row
    except Exception as e:
        conn.rollback()
        missing_entries.append((prod_code, col, f"DB write failed: {e}", fname))
        logger.error("  DB write failed: %s", e)
        return 0, 1, has_row


def _process_video_urls(cur, conn, ref_id, prod_code, row, has_row):
    original = (row.get("video_urls") or "").strip()
    if not original:
        return 0, 0, has_row

    urls = parse_filenames(original)
    if not urls:
        return 0, 0, has_row

    first = urls[0]
    canonical = canonicalize_youtube_url(first)
    if not canonical:
        missing_entries.append((prod_code, "video_urls", "invalid YouTube URL", first))
        logger.warning("  invalid YouTube URL; skipping: %s", first)
        return 0, 1, has_row

    metadata = {
        "URL": canonical,
        "original": first,
        "file_size": "Unknown",
        "file_type": "text/html",
        "type": "youtube",
    }
    db_field = EXCEL_TO_DB["video_urls"]

    try:
        if has_row:
            updated = update_db(cur, ref_id, db_field, metadata)
            action = "updated" if updated else "no-op"
        else:
            insert_db(cur, ref_id, db_field, metadata)
            has_row = True
            action = "inserted"
        conn.commit()
        logger.info("  %s %s → %s (YouTube)", action, prod_code, db_field)
        return (1 if action in ("updated", "inserted") else 0), 0, has_row
    except Exception as e:
        conn.rollback()
        missing_entries.append(
            (prod_code, "video_urls", f"DB write failed: {e}", first)
        )
        logger.error("  DB write failed: %s", e)
        return 0, 1, has_row


# ---------------------------
# Repair mode
# ---------------------------
def repair_all_downloads(conn, cur) -> Tuple[int, int]:
    """
    Pass 1: read all rows, normalize shapes; Pass 2: write back the normalized JSON if changed.
    Returns (updated_count, scanned_count).
    """
    logger.info("Starting repair mode: scanning product_downloads for normalization...")
    cur.execute(
        "SELECT page_ptr_id, product_downloads FROM public.products_productupdate"
    )
    rows = cur.fetchall()
    scanned = len(rows)
    updated = 0

    for page_ptr_id, raw in rows:
        try:
            normalized = _normalize_downloads_shape(raw)
            before = (
                json.dumps(raw, sort_keys=True, default=str)
                if isinstance(raw, dict)
                else json.dumps(_json_load_maybe(raw), sort_keys=True, default=str)
            )
            after = json.dumps(normalized, sort_keys=True, default=str)
            if before != after:
                cur.execute(
                    """
                    UPDATE public.products_productupdate
                    SET product_downloads = %s
                    WHERE page_ptr_id = %s
                    """,
                    (extras.Json(normalized), page_ptr_id),
                )
                updated += 1
        except Exception as e:
            logger.error("  Repair error on page_ptr_id=%s: %s", page_ptr_id, e)
            conn.rollback()
            continue
    conn.commit()
    logger.info("Repair complete: updated=%d / scanned=%d", updated, scanned)
    return updated, scanned


# ---------------------------
# CLI / Entrypoint
# ---------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transfer product artifacts to S3 and update DB with normalized product_downloads. Includes a --repair mode."
    )
    parser.add_argument(
        "--excel",
        default=EXCEL_PATH_DEFAULT,
        help=f"Path to Excel (default: {EXCEL_PATH_DEFAULT})",
    )
    parser.add_argument(
        "--files-dir",
        default=LOCAL_DIR,
        help=f"Local directory containing files (default: {LOCAL_DIR})",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Normalize and repair existing product_downloads JSON in DB (no Excel processing).",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    global LOCAL_DIR
    LOCAL_DIR = args.files_dir

    conn, cur = _connect_db()
    try:
        if args.repair:
            updated, scanned = repair_all_downloads(conn, cur)
            logger.info("Repair summary: updated=%d, scanned=%d", updated, scanned)
        else:
            df = _load_dataframe(args.excel)
            processed, skipped = _process_rows(df, cur, conn)
            _report_missing()
            logger.info("Done: processed=%d, skipped=%d", processed, skipped)
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
