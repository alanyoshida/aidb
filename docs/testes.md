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

O modo SSO tem seu **próprio stack** (o modo de autenticação fica travado na base): portal na
porta 8082 com `AUTH_MODE=oidc` e um Keycloak local (8180) com o realm de teste — ver
[Autenticação](autenticacao.md#e2e-com-keycloak-local). Não rode as duas suítes E2E ao mesmo tempo.

```bash
docker compose -f deploy/docker-compose.e2e-oidc.yml up -d --build
cd portal && uv run pytest tests/e2e_oidc
```

O vínculo de um sistema com um repositório remoto (change `add-system-git-remote`) tem um **terceiro
stack**: portal na porta 8083 com harness fake, GitLab CE (API em 8929, SSH em 2229) e GitLab Runner
com executor shell, em versões fixadas. O GitLab pede alguns GB de memória e leva de 4 a 5 minutos
para responder na primeira subida; não rode junto com os outros stacks E2E. O script de inicialização
é idempotente e cria o token de root, registra o runner e prepara os projetos `aidb/ci-templates`
(pipeline dos sistemas) e `aidb/sistema-e2e` (branches `main` e `homolog` protegidas, merge sem squash,
merge só com pipeline verde, CI apontando para o pipeline do outro projeto).

```bash
docker compose -f deploy/docker-compose.e2e-gitlab.yml up -d --build
python3 deploy/e2e-gitlab/init.py
cd portal && uv run pytest tests/e2e_gitlab
```

Para recomeçar o GitLab do zero, remova também os volumes: `docker compose -f
deploy/docker-compose.e2e-gitlab.yml down -v`. O token de root e as senhas do arquivo compose e de
`deploy/e2e-gitlab/init.py` valem só para esse stack.

## Cenário com LLM real (`@llm_real`)

O caminho opencode+GLM é validado manualmente (não roda em CI):

1. Suba o stack com `APPAIFORGE_HARNESS_MODE=opencode` e a chave GLM cadastrada (ver [Chave de LLM](llm-e-broker.md)).
2. Crie um sistema apontando para um **banco de homologação** (ADR 0015: a app usa a mesma credencial da conexão, com escrita; o gate de destrutivas protege as operações).
3. No chat: "analise o banco via MCP e crie um CRUD da tabela <x>".
4. Verifique: eventos de ferramenta no chat, app gerada em `/apps/<slug>`, MCP visível em `GET /mcp/status` do container do sistema.
