FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional: install Playwright with Chromium
RUN pip install playwright && playwright install chromium --with-deps || true

COPY . .

RUN mkdir -p data logs

EXPOSE 8000

CMD ["python", "-m", "src.main", "serve"]
