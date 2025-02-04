import os
import sys
import boto3
import psycopg2
import pandas as pd

# Append parent directories to sys.path (if needed)
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from generate_s3_presigned_url import generate_presigned_urls
from configs.get_secret_config import Config

# --------------------------
# Configuration
# --------------------------
config = Config()

# AWS S3 configuration
BUCKET_NAME = "REDACTED_BUCKET_NAME"
s3_client = boto3.client("s3")

# PostgreSQL DB configuration
PG_HOST = config.DB_HOST
PG_PORT = config.DB_PORT
PG_DATABASE = config.DB_NAME
PG_USER = config.DB_USER
PG_PASSWORD = config.DB_PASSWORD

try:
    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DATABASE,
        user=PG_USER,
        password=PG_PASSWORD,
    )
    cursor = conn.cursor()
except Exception as e:
    print("Error connecting to PostgreSQL:", e)
    sys.exit(1)

# --------------------------
# Paths
# --------------------------
local_directory = "./files/product_artifacts/"
excel_path = "./files/product_metadata.xlsx"

# --------------------------
# Allowed Extensions (Optional)
# --------------------------
allowed_extensions = {
    "jpg",
    "jpeg",
    "png",
    "gif",
    "pdf",
    "txt",
    "srt",
    "mp4",
    "mov",
    "avi",
    "pptx",
    "mp3",
    "wav",
    "docx",
    "doc",
    "odt",
    "ppt",
    "xlsx",
}

# --------------------------
# Read the Excel File
# --------------------------
try:
    df = pd.read_excel(excel_path)
except Exception as e:
    print(f"Failed to read Excel file {excel_path}: {e}")
    sys.exit(1)

total_rows = len(df)
processed_count = 0
skipped_count = 0

print(f"Total rows read from Excel: {total_rows}")

# --------------------------
# Process Each Row in the Excel
# --------------------------
for index, row in df.iterrows():
    # Extract and debug the file name
    file_name = str(row["File name"]).strip()
    print(f"\nProcessing row {index+1}:")
    print(f"  File name (raw): {repr(file_name)}")

    product_code = str(row["Product Code"]).strip()
    extension = str(row["Extension"]).lower().strip()
    print(f"  Product code: {product_code}")
    print(f"  Extension: {extension}")

    # Optional check: only process if the extension is allowed.
    if extension not in allowed_extensions:
        print(f"  Extension '{extension}' is not in allowed list. Skipping.")
        skipped_count += 1
        continue

    # Construct full local file path and debug it.
    file_path = os.path.join(local_directory, file_name)
    print(f"  Looking for file at: {repr(file_path)}")

    if not os.path.isfile(file_path):
        print(f"  File '{file_path}' does not exist. Skipping.")
        skipped_count += 1
        continue

    # --------------------------
    # Upload the File to S3
    # --------------------------
    s3_key = f"{product_code}/{file_name}"
    try:
        s3_client.upload_file(
            file_path, BUCKET_NAME, s3_key, ExtraArgs={"ServerSideEncryption": "AES256"}
        )
    except Exception as e:
        print(f"  Error uploading file '{file_name}' to S3: {e}")
        skipped_count += 1
        continue

    s3_bucket_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}"

    # Generate the presigned URL using your custom function.
    presigned_urls_dict = generate_presigned_urls([s3_bucket_url], expiration=3600)
    presigned_url = presigned_urls_dict.get(s3_bucket_url)
    if not presigned_url:
        print(f"  Failed to generate presigned URL for {s3_bucket_url}. Skipping.")
        skipped_count += 1
        continue

    print(f"  Uploaded to S3 as: {s3_key}")
    print(f"  S3 URL: {s3_bucket_url}")
    print(f"  Presigned URL: {presigned_url}")

    # --------------------------
    # Retrieve the Product's page_ptr_id Using product_code
    # --------------------------
    select_query = """
        SELECT page_ptr_id
        FROM public.products_product
        WHERE product_code = %s;
    """
    try:
        cursor.execute(select_query, (product_code,))
        result = cursor.fetchone()
        if not result:
            print(f"  No product found with product_code '{product_code}'. Skipping.")
            skipped_count += 1
            continue
        page_ptr_id = result[0]
    except Exception as e:
        print(f"  Error selecting product for product_code '{product_code}': {e}")
        skipped_count += 1
        continue

    # --------------------------
    # Update the Database
    # --------------------------
    update_query = """
        UPDATE public.products_productupdate
        SET product_downloads = product_downloads || jsonb_build_object('URL', %s, 's3_bucket_url', %s)
        WHERE page_ptr_id = %s;
    """
    try:
        cursor.execute(update_query, (presigned_url, s3_bucket_url, page_ptr_id))
        conn.commit()
        print(
            f"  Updated database for product_code '{product_code}' (page_ptr_id: {page_ptr_id})."
        )
        processed_count += 1
    except Exception as e:
        print(f"  Error updating DB for product_code '{product_code}': {e}")
        conn.rollback()
        skipped_count += 1

# --------------------------
# Clean Up
# --------------------------
cursor.close()
conn.close()

print("\nDone processing all files.")
print(f"Total rows read: {total_rows}")
print(f"Total rows processed successfully: {processed_count}")
print(f"Total rows skipped: {skipped_count}")
