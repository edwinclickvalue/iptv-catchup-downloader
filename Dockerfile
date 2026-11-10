FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py f1.py ./
COPY templates ./templates
ENV HOST=0.0.0.0 PORT=5123 DOWNLOAD_DIR=/downloads CACHE_DIR=/cache PYTHONUNBUFFERED=1
EXPOSE 5123
CMD ["python", "app.py"]
