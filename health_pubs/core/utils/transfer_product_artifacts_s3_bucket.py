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
from typing import Optional, Tuple, List

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
EXCEL_PATH = "./files/updated_lookup_data.xlsx"
MISSING_LOG = "./files/missing_links_assetss_pub.csv"

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
OBJECT_KEYS = {"main_download_url", "video_url"}

missing_entries = []


def normalize_smart_quotes(name: str) -> str:
    return name.replace("‘", "'").replace("’", "'")


def content_disposition_header(
    original_filename: str, disposition_type: str = "attachment"
) -> str:
    orig_nfc = unicodedata.normalize("NFC", original_filename)
    quoted = quote(orig_nfc, encoding="utf-8", safe="")
    return f"{disposition_type}; filename*=UTF-8''{quoted}"


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


def log_missing_local_file(original, target, directory):
    missing_log_path = "./files/missing_local_files.log"
    with open(missing_log_path, "a", encoding="utf-8") as logf:
        logf.write(
            f"No local file found for: {original} (sanitized: {target}). "
            f"Available files: {[sanitize_filename(f) for f in os.listdir(directory)]}\n"
        )


# Split filenames on commas, ignoring commas inside parentheses
def split_filenames(s: str) -> List[str]:
    parts = []
    buf = ""
    depth = 0
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        if ch == "," and depth == 0:
            parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf.strip())
    return parts


# Extract filenames by regex matching allowed extensions
def extract_filenames(cell: str, col: str) -> List[str]:
    exts = ALLOWED_EXTS.get(col, [])
    if not exts:
        return []
    # build regex for extensions
    pattern = (
        r"[^,]+" + r"\.(" + "|".join(exts) + r")(?=$|,)"
    )  # match up to .ext before comma or end
    regex = re.compile(pattern, flags=re.IGNORECASE)
    matches = regex.findall(cell + ",")  # add comma to match end case
    # regex.findall returns list of ext group; use finditer
    filenames = [m.group(0).strip() for m in regex.finditer(cell + ",")]
    return filenames or [cell.strip()]


def find_local_filename(directory: str, original: str) -> Optional[str]:
    if not os.path.isdir(directory):
        logger.error("Local directory missing: %s", directory)
        return None
    target = sanitize_filename(original)
    available = os.listdir(directory)
    sanitized_files = {sanitize_filename(f): f for f in available}
    if target in sanitized_files:
        return sanitized_files[target]
    orig_lower = original.lower()
    for fname in available:
        if fname.lower() == orig_lower:
            return fname
    norm_forms = [
        unicodedata.normalize(form, original) for form in ["NFC", "NFD", "NFKD"]
    ]
    for fname in available:
        if fname in norm_forms:
            return fname

    def undash(s):
        return (
            s.replace("–", "-")
            .replace("—", "-")
            .replace("\u2013", "-")
            .replace("\u2014", "-")
        )

    undashed = undash(original)
    for fname in available:
        if undash(fname) == undashed:
            return fname
    candidates = list(sanitized_files.keys())
    closest = difflib.get_close_matches(target, candidates, n=1, cutoff=0.80)
    if closest:
        return sanitized_files[closest[0]]
    log_missing_local_file(original, target, directory)
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


def canonicalize_youtube_url(url: str) -> Optional[str]:
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
        if parsed.path.startswith(
            tuple(["/channel/", "/@", "/user/", "/c/", "/playlist"])
        ):
            return url
    return None


def normalize_existing_field(val):
    if val is None:
        return None
    if isinstance(val, str):
        try:
            return json.loads(val)
        except:
            return None
    return val


def update_db(cur, update_ref_id, db_field: str, metadata: dict) -> bool:
    current = fetch_current_downloads(cur, update_ref_id) or {}
    arr = normalize_existing_field(current.get(db_field)) or []
    if not isinstance(arr, list):
        arr = []

    def is_valid(entry):
        if not isinstance(entry, dict):
            return False
        url = entry.get("URL", "")
        fs = entry.get("file_size", "")
        if not url.startswith("http"):
            return False
        try:
            size = float(
                str(fs).replace("KB", "").replace("MB", "").replace("Bytes", "").strip()
            )
            if "MB" in str(fs):
                size *= 1000
            if size < 10:
                return False
        except:
            return False
        return True

    if not is_valid(metadata):
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
        ) WHERE page_ptr_id=%s
        """,
        (path, extras.Json([metadata]), update_ref_id),
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
            extras.Json({db_field: [metadata]}),
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


def _process_row(idx: int, row: pd.Series, cur, conn) -> Tuple[int, int]:
    processed = skipped = 0
    code = row.get("product_code", "").strip()
    tag = row.get("tag", "").strip().lower()
    logger.info(f"Row {idx+1} → product_code={code}, tag={tag}")
    if tag == "order-only" and not row.get("main_download_file_name", "").strip():
        missing_entries.append(
            (code, "main_download", "order-only without main_download", "")
        )
        logger.warning("  order-only without main_download; skipping")
        return 0, 1
    ref_id = get_update_ref_id(cur, code)
    if not ref_id:
        missing_entries.append((code, "all", "no update_ref_id", ""))
        logger.warning(f"  no update_ref_id for {code}; skipping")
        return 0, 1
    has_row = fetch_current_downloads(cur, ref_id) is not None
    for col in DOWNLOAD_COLUMNS:
        p, s, has_row = _process_column(cur, conn, ref_id, code, col, row, has_row)
        processed += p
        skipped += s
    p2, s2, has_row = _process_video_urls(cur, conn, ref_id, code, row, has_row)
    return processed + p2, skipped + s2


def _process_column(cur, conn, ref_id, prod_code, col, row, has_row):
    original = row.get(col, "").strip()
    if not original:
        return 0, 0, has_row
    files = split_filenames(original)
    processed = skipped = 0
    for fname in files:
        ext = os.path.splitext(fname)[1].lower().lstrip(".")
        if ext not in ALLOWED_EXTS.get(col, set()):
            missing_entries.append(
                (prod_code, col, f"extension '{ext}' not allowed", fname)
            )
            logger.warning(f"  extension '{ext}' not allowed; skipping {fname}")
            skipped += 1
            continue
        matched = find_local_filename(LOCAL_DIR, fname)
        if not matched:
            missing_entries.append((prod_code, col, "file missing locally", fname))
            logger.warning(f"  file missing locally for {fname}; skipping")
            skipped += 1
            continue
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
            md = get_file_metadata([presigned])[0]
        except Exception as e:
            missing_entries.append(
                (prod_code, col, f"Error processing file: {e}", fname)
            )
            logger.error(f"  Error processing file: {e}")
            skipped += 1
            continue
        metadata = {
            "URL": presigned,
            "s3_bucket_url": f"https://{BUCKET_NAME}.s3.amazonaws.com/{key}",
            "file_size": md.get("file_size"),
            "file_type": md.get("file_type"),
        }
        db_field = EXCEL_TO_DB[col]
        try:
            if has_row:
                updated = update_db(cur, ref_id, db_field, metadata)
                action = "updated" if updated else "exists"
            else:
                insert_db(cur, ref_id, db_field, metadata)
                has_row = True
                action = "inserted"
            conn.commit()
            logger.info(f"  {action} {prod_code} → {db_field}")
            processed += 1
        except Exception as e:
            conn.rollback()
            missing_entries.append((prod_code, col, f"DB write failed: {e}", fname))
            logger.error(f"  DB write failed: {e}")
            skipped += 1
    return processed, skipped, has_row


def _process_video_urls(cur, conn, ref_id, prod_code, row, has_row):
    original = row.get("video_urls", "").strip()
    if not original:
        return 0, 0, has_row
    urls = split_filenames(original)
    first = urls[0]
    canonical = canonicalize_youtube_url(first)
    if not canonical:
        missing_entries.append((prod_code, "video_urls", "invalid YouTube URL", first))
        logger.warning(f"  invalid YouTube URL; skipping: {first}")
        return 0, 1, has_row
    metadata = {"URL": canonical, "original": first, "type": "youtube"}
    db_field = EXCEL_TO_DB["video_urls"]
    try:
        if has_row:
            updated = update_db(cur, ref_id, db_field, metadata)
            action = "updated" if updated else "exists"
        else:
            insert_db(cur, ref_id, db_field, metadata)
            has_row = True
            action = "inserted"
        conn.commit()
        logger.info(f"  {action} {prod_code} → {db_field} (YouTube link)")
        return (1 if action in ("updated", "inserted") else 0), 0, has_row
    except Exception as e:
        conn.rollback()
        missing_entries.append(
            (prod_code, "video_urls", f"DB write failed: {e}", first)
        )
        logger.error(f"  DB write failed: {e}")
        return 0, 1, has_row


def main():
    conn, cur = _connect_db()
    df = _load_dataframe(EXCEL_PATH)
    proc, skip = _process_rows(df, cur, conn)
    _report_missing()
    cur.close()
    conn.close()
    logger.info(f"Done: processed={proc}, skipped={skip}")


if __name__ == "__main__":
    main()
