# Testes (três camadas — ADR 0016)

← [README](../README.md)

```bash
cd portal
uv sync                                  # deps (Python 3.12)
docker compose -f ../deploy/docker-compose.yml up -d --build   # stack para E2E

uv run pytest tests/unit                 # unitários (rápidos)
uv run pytest tests/bdd                  # BDD: cenários das specs em Gherkin
uv run pytest tests/integration          # Docker real + Postgres efêmero
uv run pytest tests/e2e                  # browser (Playwright) contra o stack, do zero
```

A suíte E2E roda contra um **stack dedicado e isolado** (porta 8081, harness sempre fake, bancos e workspaces próprios) — nunca toca no portal nem nos sistemas do ambiente real:

```bash
docker compose -f deploy/docker-compose.e2e.yml up -d --build
cd portal && uv run pytest tests/e2e     # browser (Playwright), do zero, no stack 8081
```

## Cenário com LLM real (`@llm_real`)

O caminho opencode+GLM é validado manualmente (não roda em CI):

1. Suba o stack com `APPAIFORGE_HARNESS_MODE=opencode` e a chave GLM cadastrada (ver [Chave de LLM](llm-e-broker.md)).
2. Crie um sistema apontando para um **banco de homologação** (ADR 0015: a app usa a mesma credencial da conexão, com escrita; o gate de destrutivas protege as operações).
3. No chat: "analise o banco via MCP e crie um CRUD da tabela <x>".
4. Verifique: eventos de ferramenta no chat, app gerada em `/apps/<slug>`, MCP visível em `GET /mcp/status` do container do sistema.
