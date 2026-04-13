FROM python:3.10-slim

# Yapay Zeka (Fiş Okuma) için gerekli sistem paketlerini kur
RUN apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-tur libgl1-mesa-glx

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render portuna uyumlu olarak sistemi ayağa kaldır
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:10000"]