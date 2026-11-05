FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY portal/pyproject.toml /app/portal/pyproject.toml
COPY portal/appaiforge /app/portal/appaiforge
COPY portal/alembic.ini /app/portal/alembic.ini
COPY portal/migrations /app/portal/migrations

RUN pip install --no-cache-dir ./portal

# afsupervisor.sandbox.landlock_abi(): sonda de confinamento (etapa 2,
# capability agent-sandbox) usada em provisioning.decide_execution_mode() na
# criação de um sistema. Só essa função é usada daqui — build_seccomp_filter
# importa pyseccomp sob demanda, então esta imagem não precisa de
# libseccomp2/pyseccomp (o portal nunca instala um filtro seccomp nela
# mesma, só nos containers de sistema).
COPY base-image/afsupervisor /app/base-image/afsupervisor
ENV PYTHONPATH=/app/base-image

EXPOSE 8080
CMD ["uvicorn", "appaiforge.main:app", "--host", "0.0.0.0", "--port", "8080"]
