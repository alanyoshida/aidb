# Imagem base dos containers de sistema do AIDB (ADR 0003).
# Python 3.12 + uv + opencode (pinado) + MCP server de Postgres + supervisor PID 1.
FROM python:3.12-slim

ARG OPENCODE_VERSION=1.19.5
ARG MCP_POSTGRES_VERSION=0.6.2
ENV NODE_VERSION=22.14.0

# node é necessário para os MCP servers (npx)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl xz-utils ca-certificates git bash procps \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
        | tar -xJ -C /usr/local --strip-components=1

# opencode em versão pinada (ADR 0004)
RUN curl -fsSL https://opencode.ai/install | bash -s -- --version "${OPENCODE_VERSION}" \
    && ln -sf /root/.opencode/bin/opencode /usr/local/bin/opencode

# uv para rodar a app gerada com deps próprias
RUN pip install --no-cache-dir uv

# MCP server de leitura do AIDB + deps (mcp/sqlglot/asyncpg no python do sistema)
COPY gated-mcp /opt/gated-mcp
RUN pip install --no-cache-dir "mcp>=1.0" sqlglot asyncpg

# supervisor como PID 1
COPY afsupervisor /opt/afsupervisor/afsupervisor
ENV PYTHONPATH=/opt/afsupervisor
ENV APP_PORT=8080

# workspaces ficam em /workspace (bind do portal); entrypoint é o supervisor
WORKDIR /workspace
CMD ["python", "-m", "afsupervisor"]
