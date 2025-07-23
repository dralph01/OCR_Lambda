This project provides an OCR microservice that extracts address information from scanned PDF envelopes and stores the results in daily Excel files in S3. The service is built as a Python AWS Lambda function with added native binaries for tesseract and poppler-utils via a custom Lambda layer.

The Lambda is invoked via an HTTP endpoint (API Gateway), and will be triggered by Make or other automation tools passing PDF files for processing.

# Trigger deploy-prod
# trigger prod
# test prod deploy
# test dev trigger
# test dev trigger
# Trigger dev workflow
