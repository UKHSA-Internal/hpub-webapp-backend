import os
import sys
import logging
import boto3
import psycopg2
import pandas as pd
from psycopg2 import extras

# Configure logging: output to both console and a file.
LOG_FILENAME = "transfer_product_artifacts.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.FileHandler(LOG_FILENAME, mode="w"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Append parent directories so that our custom modules can be found.
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from generate_s3_presigned_url import generate_presigned_urls
from configs.get_secret_config import Config
from extract_file_metadata import get_file_metadata

# --------------------------
# Configuration
# --------------------------
config = Config()

# AWS S3 configuration
BUCKET_NAME = config.get_hpub_s3_bucket_name()
s3_client = boto3.client("s3")

# PostgreSQL DB configuration
PG_HOST = config.get_db_host()
PG_PORT = config.get_db_port()
PG_DATABASE = config.get_db_name()
PG_USER = config.get_db_user()
PG_PASSWORD = "ip.AHcR-Zy1!)2C15?E<ZFy-:a0q"

try:
    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DATABASE,
        user=PG_USER,
        password=PG_PASSWORD,
    )
    cursor = conn.cursor()
    logger.info("Connected to PostgreSQL successfully.")
except Exception as e:
    logger.error("Error connecting to PostgreSQL: %s", e)
    sys.exit(1)

# --------------------------
# Paths
# --------------------------
local_directory = "./files/"
excel_path = "./files/updated_lookup_data.xlsx"

# --------------------------
# Allowed Extensions Mapping (Excel column names)
# --------------------------
allowed_extensions = {
    "main_download_file_name": ["jpg", "jpeg", "png", "gif"],
    "transcript_file_name": ["txt"],
    "web_download_file_name": [
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
    ],
    "print_download_file_name": [
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
    ],
}

# Mapping from Excel download key to database field name.
excel_to_db_field = {
    "main_download_file_name": "main_download_url",
    "transcript_file_name": "transcript_url",
    "web_download_file_name": "web_download_url",
    "print_download_file_name": "print_download_url",
}

# Define which DB keys are stored as objects versus arrays.
OBJECT_KEYS = {"main_download_url", "video_url"}
ARRAY_KEYS = {"transcript_url", "web_download_url", "print_download_url"}

# --------------------------
# Read the Excel File
# --------------------------
try:
    df = pd.read_excel(excel_path)
    logger.info("Excel file '%s' read successfully.", excel_path)
except Exception as e:
    logger.error("Failed to read Excel file %s: %s", excel_path, e)
    sys.exit(1)

total_rows = len(df)
processed_count = 0
skipped_count = 0

logger.info("Total rows read from Excel: %d", total_rows)

# List of file columns in the new Excel format.
download_columns = [
    "main_download_file_name",
    "transcript_file_name",
    "web_download_file_name",
    "print_download_file_name",
]

# --------------------------
# Process Each Row in the Excel
# --------------------------
for index, row in df.iterrows():
    product_code = str(row["product_code"]).strip()
    tag = str(row.get("tag", "")).strip().lower()  # e.g., 'download-only', 'order-only'

    logger.info(
        "Processing row %d: Product code=%s, Tag=%s", index + 1, product_code, tag
    )

    # If this is order-only, require main_download
    if tag == "order-only" and not str(row.get("main_download_file_name", "")).strip():
        logger.warning(
            " Tag is 'order-only' but no main_download_file_name provided. Skipping row."
        )
        skipped_count += 1
        continue

    # For each file download column in the row
    for file_key in download_columns:
        # Skip based on tag logic
        if tag == "download-only" and file_key == "print_download_file_name":
            logger.info(
                "  Tag is 'download-only'; skipping print_download requirement."
            )
            continue
        if tag == "order-only" and file_key != "main_download_file_name":
            logger.info(
                "  Tag is 'order-only'; only processing main_download_file_name."
            )
            continue

        file_name = str(row[file_key]).strip()
        if not file_name:
            logger.info("  No file provided for '%s'. Skipping.", file_key)
            continue

        # Determine extension from the file name (if present)
        if "." in file_name:
            extension = file_name.split(".")[-1].lower().strip()
        else:
            extension = str(row.get("Extension", "")).lower().strip()

        logger.info(
            "  Processing '%s': file=%s, ext=%s", file_key, file_name, extension
        )

        # Verify that the extension is allowed for this file type.
        allowed_exts = allowed_extensions.get(file_key, [])
        if extension not in allowed_exts:
            logger.warning(
                "    Extension '%s' is not allowed for '%s'. Skipping.",
                extension,
                file_key,
            )
            skipped_count += 1
            continue

        # Build local file path
        file_path = os.path.join(local_directory, file_name)
        if not os.path.isfile(file_path):
            logger.warning("    File '%s' does not exist. Skipping.", file_path)
            skipped_count += 1
            continue

        # Build the S3 key and upload
        s3_key = f"{product_code}/{file_name}"
        try:
            s3_client.upload_file(
                file_path,
                BUCKET_NAME,
                s3_key,
                ExtraArgs={"ServerSideEncryption": "AES256"},
            )
            logger.info("    Uploaded '%s' to S3 as '%s'.", file_name, s3_key)
        except Exception as e:
            logger.error("    Error uploading '%s': %s", file_name, e)
            skipped_count += 1
            continue

        s3_bucket_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}"

        # Generate presigned URL
        presigned_urls_dict = generate_presigned_urls([s3_bucket_url], expiration=3600)
        presigned_url = presigned_urls_dict.get(s3_bucket_url)
        if not presigned_url:
            logger.error(
                "    Failed to generate presigned URL for %s. Skipping.", s3_bucket_url
            )
            skipped_count += 1
            continue

        # Extract file metadata
        try:
            metadata_list = get_file_metadata([presigned_url])
            full_metadata = metadata_list[0]
        except Exception as e:
            logger.error("    Error extracting metadata: %s", e)
            skipped_count += 1
            continue

        metadata = {
            "URL": presigned_url,
            "s3_bucket_url": s3_bucket_url,
            "file_size": full_metadata.get("file_size"),
            "file_type": full_metadata.get("file_type"),
        }
        db_field = excel_to_db_field[file_key]

        # Fetch update_ref_id
        try:
            cursor.execute(
                "SELECT update_ref_id FROM public.products_product WHERE product_code = %s;",
                (product_code,),
            )
            result = cursor.fetchone()
            if not result or not result[0]:
                logger.warning(
                    "    No update_ref_id for product_code '%s'. Skipping.",
                    product_code,
                )
                skipped_count += 1
                continue
            update_ref_id = result[0]
        except Exception as e:
            logger.error("    Error fetching update_ref_id: %s", e)
            skipped_count += 1
            continue

        # Check for existing productupdate
        try:
            cursor.execute(
                "SELECT page_ptr_id, product_downloads FROM public.products_productupdate WHERE page_ptr_id = %s;",
                (update_ref_id,),
            )
            update_row = cursor.fetchone()
        except Exception as e:
            logger.error("    Error querying productupdate: %s", e)
            skipped_count += 1
            continue

        # Insert or update
        if update_row:
            current_downloads = update_row[1] or {}
            if db_field in OBJECT_KEYS:
                existing = current_downloads.get(db_field)
                if (
                    isinstance(existing, dict)
                    and existing.get("s3_bucket_url") == s3_bucket_url
                ):
                    logger.info("    '%s' already up-to-date. Skipping.", db_field)
                    continue
                update_query = (
                    "UPDATE public.products_productupdate "
                    "SET product_downloads = COALESCE(product_downloads, '{}'::jsonb) || jsonb_build_object(%s, %s::jsonb) "
                    "WHERE page_ptr_id = %s;"
                )
                params = (db_field, extras.Json(metadata), update_ref_id)
            else:
                arr = current_downloads.get(db_field, [])
                if any(
                    isinstance(i, dict) and i.get("s3_bucket_url") == s3_bucket_url
                    for i in arr
                ):
                    logger.info("    Duplicate entry in '%s'. Skipping.", db_field)
                    continue
                update_query = (
                    "UPDATE public.products_productupdate "
                    "SET product_downloads = jsonb_set(COALESCE(product_downloads, '{}'::jsonb), %s, "
                    "COALESCE(product_downloads->%s, '[]'::jsonb) || %s::jsonb, true) "
                    "WHERE page_ptr_id = %s;"
                )
                params = (
                    f"{{{db_field}}}",
                    db_field,
                    extras.Json([metadata]),
                    update_ref_id,
                )
            try:
                cursor.execute(update_query, params)
                conn.commit()
                logger.info("    Updated DB for %s (%s).", product_code, db_field)
                processed_count += 1
            except Exception as e:
                logger.error("    Error updating DB: %s", e)
                conn.rollback()
                skipped_count += 1
        else:
            # Build default inserts
            new_downloads = {
                db_field: metadata if db_field in OBJECT_KEYS else [metadata]
            }
            insert_query = """
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
                ) VALUES (%s, NULL, NULL, 0, NULL, NULL, NULL, NULL, NULL,
                          NULL, NULL, NULL, NULL, NULL, %s,
                          %s, %s, %s, %s, %s, NULL, NULL, NULL);
            """
            main_val = (
                extras.Json(metadata)
                if file_key == "main_download_file_name"
                else extras.Json({})
            )
            video_val = extras.Json({})
            print_val = (
                extras.Json([metadata])
                if file_key == "print_download_file_name"
                else extras.Json([])
            )
            web_val = (
                extras.Json([metadata])
                if file_key == "web_download_file_name"
                else extras.Json([])
            )
            transcript_val = (
                extras.Json([metadata])
                if file_key == "transcript_file_name"
                else extras.Json([])
            )
            try:
                cursor.execute(
                    insert_query,
                    (
                        update_ref_id,
                        extras.Json(new_downloads),
                        main_val,
                        video_val,
                        print_val,
                        web_val,
                        transcript_val,
                    ),
                )
                conn.commit()
                logger.info(
                    "    Inserted new productupdate for %s (%s).",
                    product_code,
                    db_field,
                )
                processed_count += 1
            except Exception as e:
                logger.error("    Error inserting DB: %s", e)
                conn.rollback()
                skipped_count += 1

# --------------------------
# Clean Up
# --------------------------
cursor.close()
conn.close()

logger.info(
    "Done: total=%d, processed=%d, skipped=%d",
    total_rows,
    processed_count,
    skipped_count,
)
