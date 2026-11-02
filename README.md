# AppAIForge

Portal que cria **sistemas de gestão com IA sobre seus bancos de dados**: você cadastra um sistema, conecta um banco PostgreSQL, conversa com o agente pelo chat do portal e ele gera uma app administrativa (NiceGUI, 100% Python) que sobe automaticamente e fica acessível em `/apps/<slug>`.

- Decisões de arquitetura: [`docs/adr/`](docs/adr/README.md) (16 ADRs, formato MADR)
- Especificações: `openspec/specs/` (change fundadora: `openspec/changes/appai-forge-mvp`)

## Arquitetura em uma linha

Traefik (edge) → portal FastAPI+NiceGUI (auth/RBAC/chat/proxy) → um container por sistema (supervisor + `opencode serve` + app gerada) → PostgreSQL de produção via MCP (agente) e driver direto (app).

## Requisitos

- Docker 24+ com Compose v2
- Porta 80 livre
- ~2 GB RAM por sistema ativo (padrão; ver limites abaixo)

## Subir o stack do zero

```bash
cd deploy
docker compose up -d --build          # postgres + traefik + portal
docker compose exec portal alembic upgrade head   # migrações (opcional: o portal cria o schema no boot)
```

- Portal: http://localhost (admin semeado em dev: `admin@appaiforge.local` / `admin123` — `APPAIFORGE_SEED_DEMO_ADMIN=1` no compose)
- Health: http://localhost/api/health

### Bootstrap do admin (produção)

Em vez do admin semeado, crie o primeiro admin por CLI:

```bash
docker compose -f deploy/docker-compose.yml exec portal appaiforge create-admin --email voce@empresa.com --password 'uma-senha-forte'
# e remova a variável APPAIFORGE_SEED_DEMO_ADMIN do compose
```

## Chave de LLM (para geração real)

O padrão do produto é GLM/Z.ai (ADR 0012). Obtenha uma chave e cadastre-a cifrada:

```bash
docker compose -f deploy/docker-compose.yml exec portal appaiforge set-provider-key --provider glm --key 'SUA_CHAVE_ZHIPUAI'
```

> Os comandos `docker compose -f deploy/...` funcionam de qualquer diretório; se preferir, `cd deploy` antes e use `docker compose exec portal ...` sem o `-f`.

Sem chave, o portal opera em **modo fake** (ver abaixo) — todo o resto funciona.

**Troubleshooting de provedor**: se uma execução falha com *"o provedor de LLM não retornou resposta (verifique chave, saldo e modelo configurados)"*, valide a chave diretamente — exemplo do erro `1113` (saldo insuficiente na Z.ai):

```bash
curl -s https://api.z.ai/api/coding/paas/v4/chat/completions \
  -H "Authorization: Bearer SUA_CHAVE" -H "Content-Type: application/json" \
  -d '{"model":"glm-4.6","messages":[{"role":"user","content":"ok"}]}'
```

## Criar um sistema (fluxo do usuário)

1. Login como **editor** → "Novo sistema" → nome + slug.
2. Aguarde o badge **ativo** (container provisionado, app em `/apps/<slug>` mostrando "ainda não gerada").
3. Na página do sistema: **Conexões** → cadastre o PostgreSQL (host/porta/banco/usuário/senha — testado antes de salvar; vira MCP do agente + `DATABASE_URL_<NOME>` da app).
4. **Chat de geração**: peça em PT-BR ("crie um CRUD da tabela clientes com busca e formulário"). Acompanhe o streaming, interrompa se preciso.
5. Ao concluir: checkpoint criado, app reiniciada e servida em `/apps/<slug>`; "Abrir app" entra com sua identidade (SSO por token HMAC).
6. **Checkpoints** → "Restaurar" para voltar o código a qualquer ponto (a app reinicia no estado restaurado).

## Gate de operações destrutivas

Toda SQL que toca os bancos das conexões passa pelo **gate** (classificador canônico com sqlglot — ADR 0017):

| Classe | Exemplo | Comportamento |
|---|---|---|
| **normal** | `DELETE FROM clientes WHERE id = $1` (escopo por chave) | executa sem atrito |
| **confirmável** | `DELETE FROM clientes` ou `WHERE cidade = 'X'` | **aguarda confirmação** |
| **bloqueada** | DDL (`DROP`/`TRUNCATE`/`ALTER`/...) | **sempre recusada** |

- **Pelo agente**: comandos de banco via bash disparam pedido de permissão; o chat mostra o SQL com botões **Aprovar/Recusar** (auto-aprovação pelo editor que conduz a sessão). DDL nem chega a perguntar. Escritas via MCP são sempre recusadas (o MCP das conexões é somente leitura).
- **Na app gerada**: a camada `dbgate.py` (obrigatória nas guidelines) dispara um diálogo com a contagem estimada de linhas antes de executar operações confirmáveis; DDL é recusada.
- **Auditoria**: toda decisão (aprovada/recusada/bloqueada) fica na seção "Gate de destrutivas" da página do sistema, com autor, SQL e data.
- Apps geradas **antes** desta mudança migram para a camada na próxima edição pelo agente.

## Configuração (env `APPAIFORGE_*`)

| Variável | Padrão | O quê |
|---|---|---|
| `DATABASE_URL` | postgres do compose | metadados do portal |
| `SECRET_KEY` | — | **obrigatória em produção** (deriva a cifra de segredos) |
| `HARNESS_MODE` | `opencode` | `fake` = agente determinístico sem LLM (dev/E2E) |
| `FAKE_DELAY` | `0.15` | ritmo do harness fake em segundos |
| `BASE_IMAGE` | `appaiforge/base:0.1.0` | imagem dos containers de sistema |
| `CONTAINER_CPUS` / `CONTAINER_MEM_MB` / `CONTAINER_DISK_GB` | 2 / 2048 / 10 | limites por sistema (ADR 0013) |
| `MAX_SYSTEMS` | 10 | teto de sistemas simultâneos |
| `HEALTH_INTERVAL` | 15 | sonda de saúde das apps (segundos) |
| `WORKSPACES_DIR` / `HOST_WORKSPACES_DIR` | /workspaces | raiz dos workspaces (bind compartilhado) |
| `DYNAMIC_CONFIG_DIR` | /dynamic | rotas dinâmicas do Traefik (volume compartilhado) |

Limites: CPU/memória aplicados via Docker; **quota de disco** requer storage driver com suporte a `storage-opt` (overlay2/ext4 não suporta — o container sobe sem quota e o portal registra a ressalva).

## Testes (três camadas — ADR 0016)

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

### Cenário com LLM real (`@llm_real`)

O caminho opencode+GLM é validado manualmente (não roda em CI):

1. Suba o stack com `APPAIFORGE_HARNESS_MODE=opencode` e a chave GLM cadastrada.
2. Crie um sistema apontando para um **Postgres de homologação** (ADR 0015: a app usa a mesma credencial da conexão, em produção com escrita).
3. No chat: "analise o banco via MCP e crie um CRUD da tabela <x>".
4. Verifique: eventos de ferramenta no chat, app gerada em `/apps/<slug>`, MCP visível em `GET /mcp/status` do container do sistema.

## Operação

- **Rollback**: página do sistema → Checkpoints → Restaurar.
- **Arquivar** (dono): para o container, preserva o workspace, remove a rota. **Excluir** (admin, só para arquivados): remove container + workspace.
- **Logs**: `docker compose logs -f portal` / `docker logs appaiforge-sys-<slug>`.
- **Estado da app**: o monitor marca `erro — app fora do ar` após 3 sondas falhas e recupera sozinho quando a app volta.
- **Reconciliação**: no boot e periodicamente o portal recria containers ausentes (workspace persiste no bind).
- **Backup**: volumes do Postgres do portal + diretório de workspaces (`APPAIFORGE_WORKSPACES_DIR`).

## Estrutura

```
portal/       appaiforge/ (FastAPI+NiceGUI), tests/ (unit, bdd, integration, e2e), migrations/
base-image/   Dockerfile da imagem dos sistemas + afsupervisor (PID 1)
deploy/       docker-compose.yml (postgres, traefik, portal)
docs/adr/     decisões de arquitetura
openspec/     specs e change ativa
```
