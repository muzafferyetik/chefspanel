FROM python:3.10-slim

# Paket listesini yenile, sadece gerekenleri kur ve gereksiz dosyaları temizle
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-tur \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:10000"]
