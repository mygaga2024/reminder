FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gosu \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x /app/entrypoint.sh

ENV UMASK=000

ENTRYPOINT ["/app/entrypoint.sh"]
