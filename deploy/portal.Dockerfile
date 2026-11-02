FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY portal/pyproject.toml /app/portal/pyproject.toml
COPY portal/appaiforge /app/portal/appaiforge
COPY portal/alembic.ini /app/portal/alembic.ini
COPY portal/migrations /app/portal/migrations

RUN pip install --no-cache-dir ./portal

EXPOSE 8080
CMD ["uvicorn", "appaiforge.main:app", "--host", "0.0.0.0", "--port", "8080"]
