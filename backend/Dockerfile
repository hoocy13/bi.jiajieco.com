FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --default-timeout=120 -i https://mirrors.cloud.tencent.com/pypi/simple -r requirements.txt

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY outputs ./outputs

ENV BI_PROJECT_ROOT=/app \
    BI_BACKEND_ROOT=/app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
