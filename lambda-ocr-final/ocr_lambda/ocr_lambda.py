import pytesseract
from PIL import Image, ImageFilter
from pdf2image import convert_from_bytes
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment
from openpyxl.drawing.image import Image as XLImage
from datetime import datetime
import boto3
import base64
import os
import io
import subprocess
import logging

# === CONFIG ===
ADDRESS_REGION_1 = (750, 760, 919, 260)
ADDRESS_REGION_2 = (750, 2035, 919, 265)
BUCKET_NAME = 'ocr-envelopes'
S3_KEY_PREFIX = 'ocr-results/'
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024

s3 = boto3.client('s3')
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def clean_ocr_text(text):
    lines = text.strip().split('\n')
    cleaned = [
        line.strip() for line in lines
        if line.strip() and len(line.strip()) >= 5 and not line.replace(" ", "").isdigit()
        and not any(c in line for c in '|+*=#[]{}~_<>')
    ]
    return '\n'.join(cleaned)


def insert_image(ws, image_obj, row, col):
    img_path = f"/tmp/temp_{row}_{col}.png"
    image_obj.save(img_path)
    img = XLImage(img_path)
    img.width = 200
    img.height = 80
    ws.row_dimensions[row].height = 75
    ws.add_image(img, ws.cell(row=row, column=col).coordinate)


def process_address_region(ws, base_image, region, filename, label, row):
    x, y, w, h = region
    cropped = base_image.crop((x, y, x + w, y + h))
    gray = cropped.convert('L')
    bw = gray.point(lambda px: 0 if px < 160 else 255, mode='1')
    sharpened = bw.filter(ImageFilter.SHARPEN)
    config = '--oem 3 --psm 4'
    raw_text = pytesseract.image_to_string(sharpened, config=config)
    text = clean_ocr_text(raw_text)

    if text:
        ws.append([f"{filename} ({label})", text, ""])
        ws.cell(row=row, column=2).alignment = Alignment(wrap_text=True)
        insert_image(ws, cropped, row, 3)
        return True
    return False


def s3_file_exists(bucket, key):
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except:
        return False


def lambda_handler(event, context):
    try:
        os.environ["TESSDATA_PREFIX"] = "/opt/tessdata/"
        logger.info("📦 Event headers: %s", event.get('headers'))

        content_type = event['headers'].get('content-type', '').lower()
        filename = event['headers'].get('filename', 'uploaded_file')

        body = event.get('body', '')
        if event.get('isBase64Encoded', False):
            file_data = base64.b64decode(body)
        else:
            file_data = body.encode('utf-8')

        logger.info("📦 Body size: %d", len(file_data))
        if len(file_data) > MAX_FILE_SIZE_BYTES:
            return {"statusCode": 413, "body": "❌ File too large. Max 5MB."}

        ext = os.path.splitext(filename)[-1].lower()
        if not ext or ext == '.uploaded_file':
            ext = '.pdf' if 'pdf' in content_type else '.jpg'

        today_str = datetime.utcnow().strftime('%Y-%m-%d')
        excel_key = f"{S3_KEY_PREFIX}ocr_output_{today_str}.xlsx"
        excel_local = f"/tmp/ocr_output_{today_str}.xlsx"

        if s3_file_exists(BUCKET_NAME, excel_key):
            s3.download_file(BUCKET_NAME, excel_key, excel_local)
            wb = load_workbook(excel_local)
            ws = wb.active
            row_index = ws.max_row + 1
        else:
            wb = Workbook()
            ws = wb.active
            ws.title = "Extracted Addresses"
            ws.append(['Filename', 'Extracted Address', 'Cropped Preview'])
            ws.column_dimensions['A'].width = 30
            ws.column_dimensions['B'].width = 50
            ws.column_dimensions['C'].width = 40
            row_index = 2

        pages = []
        if ext == '.pdf':
            if not file_data.startswith(b'%PDF'):
                return {"statusCode": 400, "body": "❌ Invalid PDF (missing %PDF header)"}
            try:
                logger.info("🔧 Running pdftoppm...")
                pages = convert_from_bytes(file_data, dpi=300, poppler_path="/opt/bin")
            except Exception as e:
                return {"statusCode": 400, "body": f"❌ PDF decode failed: {str(e)}"}
        elif ext in ('.jpg', '.jpeg', '.png'):
            pages = [Image.open(io.BytesIO(file_data))]
        else:
            return {"statusCode": 400, "body": "❌ Unsupported file type"}

        for page_num, img in enumerate(pages):
            rotated = img.rotate(-90, expand=True)
            if process_address_region(ws, rotated, ADDRESS_REGION_1, filename, f"page{page_num+1}_top", row_index):
                row_index += 1
            if process_address_region(ws, rotated, ADDRESS_REGION_2, filename, f"page{page_num+1}_bottom", row_index):
                row_index += 1

        wb.save(excel_local)
        s3.upload_file(excel_local, BUCKET_NAME, excel_key)

        logger.info("✅ Processed %s, saved to %s", filename, excel_key)
        return {"statusCode": 200, "body": f"✅ Processed and saved to {excel_key}"}

    except Exception as e:
        logger.error("❌ Lambda error: %s", str(e))
        return {"statusCode": 500, "body": f"❌ Error: {str(e)}"}
