import logging
import os
import uuid
from datetime import datetime

from PIL import Image
from segno import make_qr

logger = logging.getLogger(__name__)


def generate_qr_code_with_logo(url: str):
    """
    Generates a QR code image with a logo and returns the URL of the saved image.

    Args:
        url (str): The URL to encode in the QR code.

    Returns:
        str: The URL of the saved QR code image, or None if an error occurs.
    """

    OUTPUT = "qr_code_images_w_logo"
    LOGO = os.path.join("core", "images", "gov_uk_logo.png")

    # Create output directory if it doesn't exist
    if not os.path.exists(OUTPUT):
        os.makedirs(OUTPUT)

    now = datetime.now()
    unique_id = str(uuid.uuid4.int)[:8]
    filename = f"qr_code_{now.strftime('%Y%m%d_%H%M%S')}_{unique_id}.png"
    output_path_logo = os.path.join(OUTPUT, filename)

    try:
        # Generate QR code
        qr = make_qr(url, error="H")
        qr.save(output_path_logo, finder_dark="#df2037", scale=100)

        # Open the saved image and add logo
        img = Image.open(output_path_logo).convert("RGBA")
        width, _ = img.size
        logo_size = 1100

        logo = Image.open(LOGO).convert("RGBA")
        xmin = ymin = int((width / 2) - (logo_size / 2))
        xmax = ymax = int((width / 2) + (logo_size / 2))
        logo = logo.resize((xmax - xmin, ymax - ymin))
        img.paste(logo, (xmin, ymin, xmax, ymax))
        img.save(output_path_logo)

        # TODO: Upload to S3 bucket and return s3 public url

        # Return the URL of the saved image relative to the current directory
        return os.path.join(OUTPUT, filename)
    except Exception as e:
        logger.error(f"Error generating QR code: {e}")


def generate_and_store_qr_code(self, product):
    """Generate a QR code and upload it to S3, then return the URL."""
    file_url = product.file_url
    qr_code_path = generate_qr_code_with_logo(file_url)
    return qr_code_path if qr_code_path else None
