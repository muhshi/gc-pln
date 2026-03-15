FROM python:3.11-slim

# Set zona waktu ke Waktu Indonesia Barat (WIB)
ENV TZ="Asia/Jakarta"
RUN apt-get update && apt-get install -y tzdata && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code dan konfigurasi ke container
COPY . .

# Jalankan script setiap kali container dijalankan
ENTRYPOINT ["python", "app.py"]
CMD ["--workers", "10"]
