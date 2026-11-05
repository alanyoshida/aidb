# AIDB

Portal que cria **sistemas de gestão com IA sobre seus bancos de dados**: você cadastra um sistema, conecta um banco (PostgreSQL, MySQL ou BigQuery), conversa com o agente pelo chat do portal e ele gera uma app administrativa (NiceGUI, 100% Python) que sobe automaticamente e fica acessível em `/apps/<slug>`.

- Decisões de arquitetura: [`docs/adr/`](docs/adr/README.md) (17 ADRs, formato MADR)
- Especificações: `openspec/specs/` (13 capacidades); o histórico de mudanças fica em `openspec/changes/archive/` (change fundadora: `2026-11-02-appai-forge-mvp`)

## Arquitetura em uma linha

Traefik (edge) → portal FastAPI+NiceGUI (auth/RBAC/chat/proxy) → um container por sistema (supervisor + `opencode serve` + app gerada) → banco de produção (PostgreSQL, MySQL ou BigQuery) via MCP somente leitura (agente) e driver direto (app).

## Requisitos

- Docker 24+ com Compose v2
- Porta 80 livre
- ~2 GB RAM por sistema ativo (padrão; ver limites abaixo)

## Subir o stack do zero

```bash
cd deploy
docker compose up -d --build          # postgres + mysql + traefik + portal
docker compose exec portal alembic upgrade head   # migrações (opcional: o portal cria o schema no boot)
```

- O serviço `mysql` do compose existe só como banco de teste para cadastrar conexões MySQL (host `mysql`, porta 3306, banco/usuário/senha `appaiforge`); as portas dos bancos não são publicadas no host.
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

Além do GLM, o admin pode cadastrar na UI provedores que falam o padrão OpenAI (o OpenRouter é um preset); os modelos são descobertos na própria rota do provedor, e cada sistema escolhe provedor e modelo. Chaves são globais por provedor, cifradas, e podem ser cadastradas, testadas e removidas pela UI de admin.

Sem chave, o portal opera em **modo fake** (ver abaixo) — todo o resto funciona. O compose sobe em `fake` por padrão; para usar o agente real defina `APPAIFORGE_HARNESS_MODE=opencode` (por exemplo em `deploy/.env`, que não vai para o git).

**Troubleshooting de provedor**: se uma execução falha com *"o provedor de LLM não retornou resposta (verifique chave, saldo e modelo configurados)"*, valide a chave diretamente — exemplo do erro `1113` (saldo insuficiente na Z.ai):

```bash
curl -s https://api.z.ai/api/coding/paas/v4/chat/completions \
  -H "Authorization: Bearer SUA_CHAVE" -H "Content-Type: application/json" \
  -d '{"model":"glm-4.6","messages":[{"role":"user","content":"ok"}]}'
```

## Criar um sistema (fluxo do usuário)

1. Login como **editor** → "Novo sistema" → nome + slug.
2. Aguarde o badge **ativo** (container provisionado, app em `/apps/<slug>` mostrando "ainda não gerada").
3. Na página do sistema: **Conexões** → escolha o tipo e cadastre o banco, testado antes de salvar (vira MCP somente leitura do agente + `DATABASE_URL_<NOME>` da app):
   - **PostgreSQL / MySQL**: host, porta, banco, usuário e senha.
   - **BigQuery**: projeto, dataset e JSON de Service Account (guardado cifrado).
   - Cada conexão tem um estado de saúde monitorado (ver Operação).
4. **Chat de geração**: peça em PT-BR ("crie um CRUD da tabela clientes com busca e formulário"). Acompanhe o streaming, interrompa se preciso (detalhes em *Chat* abaixo).
5. Ao concluir: checkpoint criado, app reiniciada e servida em `/apps/<slug>`; "Abrir app" entra com sua identidade (SSO por token HMAC).
6. **Checkpoints** → "Restaurar" para voltar o código a qualquer ponto (a app reinicia no estado restaurado).

## Chat

- **Sessões**: cada editor mantém várias sessões nomeadas por sistema (criadas na primeira mensagem, renomeáveis, com troca na lista). O agente mantém o contexto dentro da sessão; se o contexto for reiniciado (container recriado, sessão inválida) o chat avisa.
- **Mensagens**: data e hora ao lado do nome de quem enviou, no fuso `APPAIFORGE_DISPLAY_TIMEZONE`. Os marcadores de execução (iniciada, concluída, interrompida, erro) aparecem em português.
- **Disponibilidade**: abaixo do chat, uma bolinha verde indica agente livre e uma amarela pulsando indica trabalho em curso (sem animação se o sistema operacional pede movimento reduzido).
- **Debug**: comandos executados e arquivos alterados só aparecem com a chave **Debug** ligada; ligar e desligar não perde histórico.
- **Artifacts**: o agente pode responder com blocos ` ```echart `, ` ```table ` e ` ```html `, que o chat renderiza como gráfico, tabela interativa e HTML em sandbox.
- **Checkpoint manual**: o botão informa se criou um checkpoint ou se não havia alteração a salvar.

## Editor

Aba ao lado do Chat, visível para quem gerencia o sistema (mesmo acesso das demais abas). Mostra, à esquerda, a árvore de arquivos da pasta onde o agente gera o projeto (`<workspace>/app`, sem `.venv`/`__pycache__`/`.git`/caches do NiceGUI) e, à direita, o conteúdo do arquivo selecionado com destaque de sintaxe pela extensão. **Somente leitura**: o painel nunca aceita edição, e nada feito nessa aba grava no workspace. A árvore reflete o estado atual do workspace (não um checkpoint específico) e se atualiza sozinha a cada 2s, então o editor vê o resultado de uma geração sem precisar trocar de aba e voltar. Um arquivo binário ou ilegível como texto mostra um aviso no lugar do conteúdo, em vez de falhar.

## Aparência

Na topbar o usuário escolhe o modo (Light, Dark ou Pastel) e a cor de destaque (Índigo, Teal, Âmbar ou Violeta). A preferência fica salva por usuário e é aplicada ao portal inteiro sem flash. Todas as 12 combinações respeitam contraste WCAG AA; ao criar componentes novos, use os tokens de `portal/appaiforge/ui/theme.py` em vez de cores fixas.

## Gate de operações destrutivas

Toda SQL que toca os bancos das conexões passa pelo **gate** (classificador canônico com sqlglot — [ADR 0017](docs/adr/0017-gate-de-operacoes-destrutivas-com-classificador-sql.md), spec `destructive-gate`):

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
| `HARNESS_MODE` | `opencode` (no compose: `fake`) | `fake` = agente determinístico sem LLM (dev/E2E) |
| `FAKE_DELAY` | `0.15` | ritmo do harness fake em segundos |
| `BASE_IMAGE` | `appaiforge/base:0.1.0` | imagem dos containers de sistema |
| `CONTAINER_CPUS` / `CONTAINER_MEM_MB` / `CONTAINER_DISK_GB` | 2 / 2048 / 10 | limites por sistema (ADR 0013) |
| `CONTAINER_PIDS_LIMIT` | 512 | teto de processos por container (ADR 0018) |
| `MAX_SYSTEMS` | 10 | teto de sistemas simultâneos |
| `HEALTH_INTERVAL` | 15 | sonda de saúde das apps (segundos) |
| `WORKSPACES_DIR` / `HOST_WORKSPACES_DIR` | /workspaces | raiz dos workspaces (bind compartilhado) |
| `DYNAMIC_CONFIG_DIR` | /dynamic | rotas dinâmicas do Traefik (volume compartilhado) |
| `CONFIGS_DIR` / `HOST_CONFIG_DIR` | /configs | config do agente (MCP, provedor, chaves) **fora do workspace**, montada read-only no container do sistema |
| `DISPLAY_TIMEZONE` | America/Sao_Paulo | fuso das datas exibidas (gravadas em UTC) |
| `SEED_DEMO_ADMIN` | — | `1` semeia o admin de dev quando não há usuários (nunca em produção) |

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
2. Crie um sistema apontando para um **banco de homologação** (ADR 0015: a app usa a mesma credencial da conexão, com escrita; o gate de destrutivas protege as operações).
3. No chat: "analise o banco via MCP e crie um CRUD da tabela <x>".
4. Verifique: eventos de ferramenta no chat, app gerada em `/apps/<slug>`, MCP visível em `GET /mcp/status` do container do sistema.

## Operação

- **Rollback**: página do sistema → Checkpoints → Restaurar.
- **Arquivar** (dono): para o container, preserva o workspace, remove a rota. **Excluir** (admin, só para arquivados): remove container + workspace.
- **Logs**: `docker compose logs -f portal` / `docker logs appaiforge-sys-<slug>`.
- **Saúde das conexões**: cada conexão é sondada periodicamente e exibe seu estado na página do sistema.
- **Auditoria**: toda ação de escrita da gestão (sistemas, conexões, usuários, provedores) fica numa trilha sem segredos, global para o admin e por sistema.
- **Estado da app**: o monitor marca `erro — app fora do ar` após 3 sondas falhas e recupera sozinho quando a app volta.
- **Reconciliação**: no boot e periodicamente o portal recria containers ausentes (workspace persiste no bind).
- **Backup**: volumes do Postgres do portal + diretório de workspaces (`APPAIFORGE_WORKSPACES_DIR`).

## Estrutura

```
portal/       appaiforge/ (FastAPI+NiceGUI), tests/ (unit, bdd, integration, e2e), migrations/
base-image/   Dockerfile da imagem dos sistemas + afsupervisor (PID 1) + gated-mcp/ (MCP somente leitura com o gate)
deploy/       docker-compose.yml (postgres, mysql, traefik, portal) e docker-compose.e2e.yml
docs/adr/     decisões de arquitetura
openspec/     specs vigentes (specs/) e histórico de changes (changes/archive/)
```
