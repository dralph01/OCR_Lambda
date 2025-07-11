FROM --platform=linux/amd64 public.ecr.aws/lambda/python:3.11

RUN yum -y install poppler-utils tesseract

COPY requirements.txt .
RUN pip install -r requirements.txt -t /opt/python

CMD [ "ocr_lambda.ocr_lambda.lambda_handler" ]
