FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
# OCR determinista del Módulo B (F7, ADR 0015): Tesseract con español e inglés.
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py && pip install -e ".[dev]"
COPY . .
RUN useradd --create-home --uid 10001 api && chown -R api /app && mkdir -p /var/capturas /var/evaluacion /var/n2 && chown api /var/capturas /var/evaluacion /var/n2
USER api
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
