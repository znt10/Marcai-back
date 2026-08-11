FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app/backend
ENV PYTHONUNBUFFERED=1

# Do Unistock ficaram build-essential, gcc, pkg-config e libpq-dev.
# SAIRAM: default-libmysqlclient-dev (nao ha MySQL aqui) e as bibliotecas do
# weasyprint (libglib, libpango, libharfbuzz, libjpeg, libopenjp2) — nao ha PDF.
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    pkg-config \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
