# 使用Python基础镜像
FROM python:3.9-slim

WORKDIR /app

RUN useradd -m -s /bin/bash appuser && \
    mkdir -p /app/data && \
    chown -R appuser:appuser /app

COPY --chown=appuser:appuser requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser . .

USER appuser
CMD ["python", "reminder.py"]