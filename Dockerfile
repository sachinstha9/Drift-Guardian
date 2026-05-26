FROM python:3.11-slim

WORKDIR /app

# System deps for python-docx / pypdf are pure-python, no apt needed.
RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY data/ ./data/

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/app \
    LOG_LEVEL=INFO

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/app"]