# Imagem base dos containers de sistema do AIDB (ADR 0003).
# Python 3.12 + uv + opencode (pinado) + MCP server de Postgres + supervisor PID 1.
FROM python:3.12-slim

ARG OPENCODE_VERSION=1.19.5
ARG MCP_POSTGRES_VERSION=0.6.2
ENV NODE_VERSION=22.14.0

# node é necessário para os MCP servers (npx); default-libmysqlclient-dev
# + pkg-config para o build do pacote python mysqlclient; libseccomp2/-dev
# para o pyseccomp do supervisor (etapa 2 do confinamento, ADR em curso)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl xz-utils ca-certificates git bash procps \
        default-libmysqlclient-dev pkg-config gcc \
        libseccomp2 libseccomp-dev \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
        | tar -xJ -C /usr/local --strip-components=1

# opencode em versão pinada (ADR 0004). O instalador grava em $HOME (ainda
# /root nesta etapa do build); ADR 0018 reloca para fora de /root, que é
# inacessível ao usuário não-root que a imagem passa a ter como padrão.
RUN curl -fsSL https://opencode.ai/install | bash -s -- --version "${OPENCODE_VERSION}" \
    && mv /root/.opencode /opt/opencode \
    && ln -sf /opt/opencode/bin/opencode /usr/local/bin/opencode

# uv para rodar a app gerada com deps próprias
RUN pip install --no-cache-dir uv

# pyseccomp para o filtro de syscalls do supervisor (etapa 2 do confinamento)
RUN pip install --no-cache-dir pyseccomp

# MCP server de leitura do AIDB + deps (mcp/sqlglot/asyncpg no python do sistema)
COPY gated-mcp /opt/gated-mcp
RUN pip install --no-cache-dir "mcp>=1.0" sqlglot asyncpg aiomysql mysqlclient google-cloud-bigquery sqlalchemy-bigquery

# supervisor como PID 1
COPY afsupervisor /opt/afsupervisor/afsupervisor
ENV PYTHONPATH=/opt/afsupervisor
ENV APP_PORT=8080

# Usuário não-root padrão da imagem (ADR 0018, identidade de execução
# reduzida — spec container-lifecycle): o modo de execução reduzido sobe o
# container com este usuário; o modo antigo (sistemas criados antes desta
# mudança) sobrescreve com `user="root"` explícito no provisionamento, sem
# exigir migração do dono do workspace existente. HOME fica numa camada
# gravável da própria imagem — rootfs somente-leitura é etapa futura do
# roadmap (docs/roadmap-confinamento-do-agente.md, etapa 2).
RUN groupadd --gid 1000 agent \
    && useradd --uid 1000 --gid agent --home-dir /home/agent --create-home --shell /bin/bash agent \
    && chown -R agent:agent /opt/opencode /home/agent
ENV HOME=/home/agent
USER agent

# workspaces ficam em /workspace (bind do portal); entrypoint é o supervisor
WORKDIR /workspace
CMD ["python", "-m", "afsupervisor"]
