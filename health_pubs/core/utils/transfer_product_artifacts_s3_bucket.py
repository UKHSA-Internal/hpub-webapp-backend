import os
import sys
import logging
import boto3
import psycopg2
import pandas as pd
from psycopg2 import extras
from botocore.exceptions import ClientError

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
PG_PASSWORD = config.get_db_password()

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
    "transcript_file_name": ["pdf", "txt", "srt"],
    "web_download_file_name": [
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
    logger.info("Processing row %d:", index + 1)
    logger.info("  Product code: %s", product_code)

    # For each file download column in the row
    for file_key in download_columns:
        file_name = str(row[file_key]).strip()
        if not file_name:
            logger.info("  No file provided for '%s'. Skipping.", file_key)
            continue

        # Determine extension from the file name (if present)
        if "." in file_name:
            extension = file_name.split(".")[-1].lower().strip()
        else:
            # Optionally, if you have an "Extension" column fallback:
            extension = str(row.get("Extension", "")).lower().strip()

        logger.info("  Processing '%s':", file_key)
        logger.info("    File name: %s", repr(file_name))
        logger.info("    Extension: %s", extension)

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
        logger.info("    Looking for file at: %s", repr(file_path))
        if not os.path.isfile(file_path):
            logger.warning("    File '%s' does not exist. Skipping.", file_path)
            skipped_count += 1
            continue

        # --------------------------
        # Build the S3 Key and Check Existence
        # --------------------------
        s3_key = f"{product_code}/{file_name}"
        file_exists = False
        try:
            s3_client.head_object(Bucket=BUCKET_NAME, Key=s3_key)
            file_exists = True
            logger.info("    File '%s' already exists in S3. Skipping upload.", s3_key)
        except ClientError as e:
            if int(e.response["Error"]["Code"]) == 404:
                file_exists = False
            else:
                logger.error("    Error checking S3 for '%s': %s", s3_key, e)
                skipped_count += 1
                continue

        if not file_exists:
            try:
                s3_client.upload_file(
                    file_path,
                    BUCKET_NAME,
                    s3_key,
                    ExtraArgs={"ServerSideEncryption": "AES256"},
                )
                logger.info("    Uploaded file '%s' to S3 as '%s'.", file_name, s3_key)
            except Exception as e:
                logger.error("    Error uploading file '%s' to S3: %s", file_name, e)
                skipped_count += 1
                continue
        else:
            logger.info("    Using existing S3 object '%s'.", s3_key)

        s3_bucket_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}"

        # --------------------------
        # Generate Presigned URL and Extract Metadata
        # --------------------------
        presigned_urls_dict = generate_presigned_urls([s3_bucket_url], expiration=3600)
        presigned_url = presigned_urls_dict.get(s3_bucket_url)
        if not presigned_url:
            logger.error(
                "    Failed to generate presigned URL for %s. Skipping.", s3_bucket_url
            )
            skipped_count += 1
            continue

        logger.info("    S3 URL: %s", s3_bucket_url)
        logger.info("    Presigned URL: %s", presigned_url)

        try:
            metadata_list = get_file_metadata([presigned_url])
            if not metadata_list:
                logger.error("    Failed to extract metadata. Skipping.")
                skipped_count += 1
                continue
            full_metadata = metadata_list[0]
        except Exception as e:
            logger.error("    Error extracting metadata: %s", e)
            skipped_count += 1
            continue

        # Build metadata dictionary.
        metadata = {
            "URL": presigned_url,
            "s3_bucket_url": s3_bucket_url,
            "file_size": full_metadata.get("file_size"),
            "file_type": full_metadata.get("file_type"),
        }
        logger.info("    Metadata to be stored: %s", metadata)

        # For this file type, the matching key is simply the current file_key.
        matching_keys = [file_key]
        logger.info("    Download keys (Excel names) to update: %s", matching_keys)

        # --------------------------
        # Retrieve update_ref_id using product_code.
        # --------------------------
        select_query = """
            SELECT update_ref_id
            FROM public.products_product
            WHERE product_code = %s;
        """
        try:
            cursor.execute(select_query, (product_code,))
            result = cursor.fetchone()
            if not result or not result[0]:
                logger.warning(
                    "    No update_ref_id found for product_code '%s'. Skipping.",
                    product_code,
                )
                skipped_count += 1
                continue
            update_ref_id = result[0]
        except Exception as e:
            logger.error(
                "    Error selecting update_ref_id for product_code '%s': %s",
                product_code,
                e,
            )
            skipped_count += 1
            continue

        # --------------------------
        # Check if a row exists in products_productupdate for this update_ref_id.
        # --------------------------
        select_update_query = """
            SELECT page_ptr_id, product_downloads
            FROM public.products_productupdate
            WHERE page_ptr_id = %s;
        """
        try:
            cursor.execute(select_update_query, (update_ref_id,))
            update_row = cursor.fetchone()
        except Exception as e:
            logger.error(
                "    Error checking productupdate for page_ptr_id '%s': %s",
                update_ref_id,
                e,
            )
            skipped_count += 1
            continue

        # --------------------------
        # Update or Insert into the Database for the current file type.
        # --------------------------
        db_field = excel_to_db_field[file_key]
        if update_row:
            current_downloads = update_row[1] or {}
            if db_field in OBJECT_KEYS:
                current_val = current_downloads.get(db_field)
                if (
                    isinstance(current_val, dict)
                    and current_val.get("s3_bucket_url") == metadata["s3_bucket_url"]
                ):
                    logger.info(
                        "    For DB field '%s', metadata already exists. Skipping update.",
                        db_field,
                    )
                    continue

                update_query = """
                    UPDATE public.products_productupdate
                    SET product_downloads = COALESCE(product_downloads, '{}'::jsonb)
                        || jsonb_build_object(%s, %s::jsonb)
                    WHERE page_ptr_id = %s;
                """
                params = (db_field, extras.Json(metadata), update_ref_id)
            else:
                current_array = current_downloads.get(db_field, [])
                duplicate = any(
                    isinstance(item, dict)
                    and item.get("s3_bucket_url") == metadata["s3_bucket_url"]
                    for item in current_array
                )
                if duplicate:
                    logger.info(
                        "    For DB field '%s', an entry with the same s3_bucket_url already exists. Skipping update.",
                        db_field,
                    )
                    continue

                update_query = """
                    UPDATE public.products_productupdate
                    SET product_downloads = jsonb_set(
                        COALESCE(product_downloads, '{}'::jsonb),
                        %s,
                        (COALESCE(product_downloads->%s, '[]'::jsonb)
                        || %s::jsonb),
                        true
                    )
                    WHERE page_ptr_id = %s;
                """
                params = (
                    f"{{{db_field}}}",
                    db_field,
                    extras.Json([metadata]),
                    update_ref_id,
                )
            try:
                cursor.execute(update_query, params)
                conn.commit()
                logger.info(
                    "    Updated DB for product_code '%s' (update_ref_id: %s) for field '%s'.",
                    product_code,
                    update_ref_id,
                    db_field,
                )
            except Exception as e:
                logger.error(
                    "    Error updating DB for product_code '%s' for field '%s': %s",
                    product_code,
                    db_field,
                    e,
                )
                conn.rollback()
                skipped_count += 1
                continue
            processed_count += 1
        else:
            # If no productupdate row exists, prepare default values.
            main_download_url_value = (
                extras.Json(metadata)
                if file_key == "main_download_file_name"
                else extras.Json({})
            )
            video_url_value = (
                extras.Json(metadata) if file_key == "video_url" else extras.Json({})
            )
            print_download_url_value = (
                extras.Json([metadata])
                if file_key == "print_download_file_name"
                else extras.Json([])
            )
            web_download_url_value = (
                extras.Json([metadata])
                if file_key == "web_download_file_name"
                else extras.Json([])
            )
            transcript_url_value = (
                extras.Json([metadata])
                if file_key == "transcript_file_name"
                else extras.Json([])
            )

            new_product_downloads = {
                excel_to_db_field[file_key]: (
                    metadata
                    if excel_to_db_field[file_key] in OBJECT_KEYS
                    else [metadata]
                )
            }

            insert_query = """
                INSERT INTO public.products_productupdate (
                    page_ptr_id,
                    minimum_stock_level,
                    maximum_order_quantity,
                    quantity_available,
                    run_to_zero,
                    available_from_choice,
                    order_from_date,
                    order_end_date,
                    product_type,
                    alternative_type,
                    cost_centre,
                    local_code,
                    unit_of_measure,
                    summary_of_guidance,
                    product_downloads,
                    main_download_url,
                    video_url,
                    print_download_url,
                    web_download_url,
                    transcript_url,
                    order_referral_email_address,
                    stock_owner_email_address,
                    order_exceptions
                )
                VALUES (
                    %s,
                    NULL, NULL, 0, NULL, NULL, NULL, NULL,
                    NULL, NULL, NULL, NULL, NULL, NULL,
                    %s,
                    %s, %s, %s, %s, %s,
                    NULL, NULL, NULL
                );
            """
            try:
                cursor.execute(
                    insert_query,
                    (
                        update_ref_id,
                        extras.Json(new_product_downloads),
                        main_download_url_value,
                        video_url_value,
                        print_download_url_value,
                        web_download_url_value,
                        transcript_url_value,
                    ),
                )
                conn.commit()
                logger.info(
                    "    Inserted new row into DB for product_code '%s' (update_ref_id: %s) for field '%s'.",
                    product_code,
                    update_ref_id,
                    db_field,
                )
                processed_count += 1
            except Exception as e:
                logger.error(
                    "    Error inserting DB for product_code '%s': %s", product_code, e
                )
                conn.rollback()
                skipped_count += 1
                continue

# --------------------------
# Clean Up
# --------------------------
cursor.close()
conn.close()

logger.info("Done processing all files.")
logger.info("Total rows read: %d", total_rows)
logger.info("Total rows processed successfully: %d", processed_count)
logger.info("Total rows skipped: %d", skipped_count)
