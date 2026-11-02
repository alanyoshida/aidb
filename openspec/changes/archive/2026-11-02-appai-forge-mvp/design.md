# Design

## Context

Projeto novo (greenfield) neste host: Docker 29.9, 28 CPUs, 46 GB RAM, RTX 2080 SUPER (ociosa para este MVP — LLM via API externa). O portal nasce como monolito único gerenciando containers por sistema via Docker API. Ver `proposal.md` (Why/What) para a motivação e o recorte da fatia vertical: Postgres como único tipo de banco suportado, sem gate de operações destrutivas (change posterior).

```
                   +----------------------------------------------------+
   browser ------> | Traefik (edge) :80/:443                            |
                   |   /            -> portal (FastAPI+NiceGUI)        |
                   |   /apps/{slug}/ -> container do sistema :8080     |
                   +--------------------+-----------------------------+
                                        | Docker API (socket)
                     +------------------v-------------------+
                     | PORTAL: auth, RBAC, sistemas, conexoes,  |
                     | adapter harness, fila, checkpoints, uso  |
                     | Postgres (metadados)                     |
                     +------------------+----------------------+
                                        | rede docker interna
             +--------------------------+-------------------------+
             |  CONTAINER SISTEMA (imagem base appaiforge)       |
             |  supervisor (PID 1)                               |
             |   |- opencode serve  (harness, porta 4096 interna)|
             |   |- app NiceGUI     (porta 8080, /workspace/app) |
             |  /workspace (volume) = git + codigo gerado        |
             |  env: creds BD, chave LLM, secret identidade      |
             +---------------------+----------------------------+
                                   | MCP (agente) / driver (app)
                                   v
                          PostgreSQL do cliente (producao)
```

## Goals / Non-Goals

**Goals:**

- Fatia vertical completa e repetível: cadastrar sistema → container → conexão Postgres → chat → app NiceGUI gerada, rodando e proxiada em `/apps/{slug}`.
- Isolamento por sistema: um container, um volume, uma rede interna; credenciais só dentro do container.
- Substituir o harness sem reescrever o portal (adapter) e trocar path-proxy por subdomínio sem refactor (rotas centralizadas no edge).
- Geração consistente entre sistemas via guidelines injetadas no agente.

**Non-Goals:**

- MySQL/MariaDB, SQLite, MongoDB (changes seguintes); gate de destrutivas; subdomínios; OIDC; multi-host/K8s; billing e bloqueio de custo; auto-stop de containers.
- Multi-tenant entre empresas: todos os usuários confiam no mesmo portal/admin.

## Decisions

Cada decisão abaixo está registrada como ADR (formato MADR, PT-BR) em `docs/adr/` — ver `docs/adr/README.md` para o índice completo, incluindo decisões de produto da exploração (ADRs 0010, 0014, 0015). Decisões novas tomadas durante a implementação geram ADR sequencial e passam a constar aqui.

| Decisão | ADR |
|---|---|
| D1 — Monorepo com três entregáveis | [ADR 0001](../../../../docs/adr/0001-monorepo-portal-base-image-deploy.md) |
| D2 — Edge proxy Traefik com config dinâmica | [ADR 0002](../../../../docs/adr/0002-traefik-edge-com-config-dinamica.md) |
| D3 — Container por sistema com supervisor PID 1 | [ADR 0003](../../../../docs/adr/0003-container-por-sistema-com-supervisor-pid1.md) |
| D4 — Adapter de harness como fronteira arquitetural | [ADR 0004](../../../../docs/adr/0004-opencode-serve-atras-de-adapter-com-fila-no-portal.md) |
| D5 — Streaming ao navegador por WebSocket | [ADR 0005](../../../../docs/adr/0005-streaming-do-chat-por-websocket.md) |
| D6 — Identidade injetada por header assinado (HMAC) | [ADR 0006](../../../../docs/adr/0006-identidade-injetada-por-token-hmac.md) |
| D7 — Metadados em Postgres; credenciais cifradas | [ADR 0007](../../../../docs/adr/0007-metadados-em-postgres-e-credenciais-cifradas.md) |
| D8 — MCP para o agente, driver direto para a app | [ADR 0008](../../../../docs/adr/0008-mcp-para-agente-driver-direto-para-app.md) |
| D9 — Checkpoints git no volume do workspace | [ADR 0009](../../../../docs/adr/0009-git-por-sistema-com-checkpoints.md) |
| D10 — Guidelines como AGENTS.md | [ADR 0011](../../../../docs/adr/0011-guidelines-de-geracao-editaveis-pelo-admin.md) |
| D11 — Provedor LLM por sistema; chaves globais | [ADR 0012](../../../../docs/adr/0012-llm-via-api-externa-provedor-por-sistema.md) |
| D12 — Ciclo de vida declarativo e reconciliação | [ADR 0013](../../../../docs/adr/0013-containers-sempre-ativos-com-reconciliacao.md) |
| D13 — Testes em três camadas | [ADR 0016](../../../../docs/adr/0016-testes-em-tres-camadas-unit-bdd-e2e.md) |

### D1 — Monorepo com três entregáveis

`portal/` (app FastAPI+NiceGUI), `base-image/` (Dockerfile da imagem dos sistemas) e `deploy/` (compose do stack do portal + Traefik). Alternativa: repositórios separados — descartada pela fase de descoberta, um repo só atravessa tudo.

### D2 — Edge proxy Traefik com config dinâmica gerada pelo portal

Traefik roda como container e publica o portal (`/`) e as apps (`/apps/{slug}/`). O portal escreve a config dinâmica (file provider em volume compartilhado) ao criar/remover sistema. Alternativa: proxy in-process ASGI no FastAPI — menos um container, mas forwarding de WebSocket e path-strip ficam frágeis; Traefik já resolve strip-prefix + WS. Apps NiceGUI precisam honrar `root_path=/apps/{slug}` (requisito das guidelines, injetado por env `APP_ROOT_PATH`). A abstração "roteador de apps" do portal é a única dona dessas rotas — trocar por subdomínios depois é mudar esse módulo, não o portal inteiro.

### D3 — Container por sistema com supervisor como PID 1

Imagem base `appaiforge/base:<ver>` (pinada na config do portal): Python 3.12 + uv + binário opencode + MCP server Postgres + supervisor Python enxuto. O supervisor: sobe `opencode serve` (porta interna 4096), sobe/reinicia a app gerada quando arquivos mudam (watchdog em `/workspace/app`), expõe healthcheck (`/healthz` na 8080) e reinicia a app em loop controlado (backoff). Alternativa: s6-overlay — mais robustez do que o MVP precisa; supervisor próprio é ~200 linhas testáveis.

### D4 — Adapter de harness como fronteira arquitetural

Interface interna do portal `HarnessPort` com operações: criar/listar sessões, enviar mensagem, stream de eventos, interromper, uso de tokens. Implementação `OpencodeHarness` fala HTTP com o `opencode serve` do container na rede interna do Docker. A fila "um agente por sistema" é do portal (estado em tabela `agent_runs`), não do harness — se o opencode mudar API ou for trocado, a fila e o chat sobrevivem. Versão do opencode pinada na imagem; eventos normalizados pelo adapter (`run_started`, `file_edited`, `command_run`, `tool_output`, `usage`, `run_finished`).

### D5 — Streaming ao navegador por WebSocket

O chat (NiceGUI) recebe eventos normalizados do adapter via WebSocket do portal. Interrupt = cancelamento da run atual propagado ao harness. Alternativa: SSE — descartada porque interrupt e fila precisam de canal bidirecional.

### D6 — Identidade injetada por header assinado (HMAC)

Ao proxiar `/apps/{slug}`, o edge não conhece usuário; quem autentica é o portal: a página da app no portal emite link/redirect passando um token curto (HMAC-SHA256 com segredo do sistema, TTL ~60s, payload: user_id, tipo, system_role, exp) que a app troca por sessão própria. As apps geradas validam com o segredo injetado por env (`APP_IDENTITY_SECRET`). Alternativa: JWT com assinatura assimétrica — overkill para confiança single-portal; HMAC com segredo por sistema basta e as guidelines já trazem o middleware pronto.

### D7 — Metadados em Postgres do portal; credenciais cifradas em repouso

SQLAlchemy + Alembic. Tabelas centrais: `users` (tipo global admin/editor/app_user), `groups`, `group_members`, `system_groups`, `systems` (slug, dono, estado, provedor/modelo LLM), `db_connections` (tipo=postgres no MVP; segredo cifrado com Fernet, chave na config do portal), `chat_sessions`, `agent_runs` (fila, estado, eventos resumidos), `checkpoints` (git sha, mensagem, sessão), `token_usage` (por run/modelo). Credenciais só são materializadas como env do container; logs e eventos nunca contêm segredo.

### D8 — MCP para o agente, driver direto para a app

Ao provisionar, o portal gera o `opencode.json` do sistema com um MCP server Postgres por conexão (connection string via env). A app gerada usa asyncpg com a mesma connection string (env `DATABASE_URL_<CONEXAO>`). Sem camada de dados intermediária: MCP é ferramenta de análise do agente, não runtime da app.

### D9 — Checkpoints git no volume do workspace

`/workspace` é volume dedicado com `git init` no provisionamento. Ao fim de cada run bem-sucedida o adapter commita (autor = usuário editor) e registra em `checkpoints`. Rollback = `git reset --hard` para o sha + reinício da app pelo supervisor. Alternativa: snapshots de volume — pesados e sem diff visível; git dá diff e histórico na UI de graça.

### D10 — Guidelines como arquivo de regras do agente

Documento de padrões (PT-BR) editável pelo admin, versionado em tabela própria; materializado no workspace como `AGENTS.md` do opencode a cada atualização. Define: layout de projeto NiceGUI padrão, `root_path`, middleware de identidade, uso de `DATABASE_URL_*`, estilo de CRUD/dashboards, idioma PT-BR. É o mecanismo que torna gerações consistentes entre sistemas.

### D11 — Provedor LLM configurável por sistema; chaves globais do admin

Chaves por provedor (GLM padrão, Anthropic, OpenAI) cifradas na config do portal e injetadas como env apenas no container do sistema; o sistema escolhe provedor+modelo no cadastro (default GLM). Uso de tokens por run coletado do harness e acumulado em `token_usage` para os dashboards de visibilidade.

### D12 — Ciclo de vida declarativo por labels e reconciliação no boot

Containers criados com labels `appaiforge.system_id`, `appaiforge.version`. No boot (e periodicamente), o portal reconcilia: container ausente ou com imagem/version divergente é recriado; rede interna e volume garantidos. Limites padrão (2 CPU / 2 GB / 10 GB) e teto de simultâneos (~10) vêm da config do portal. Restart policy `unless-stopped` mantém tudo de pé após reboot do host.

### D13 — Testes em três camadas: unitários, BDD e E2E pelo browser

Todo o trabalho (portal, imagem base, supervisor, adapter) nasce com verificação em três camadas complementares:

- **Unitários (pytest)**: lógica isolada e rápida — guardas de permissão, token HMAC, cifra de credenciais, fila por sistema, adapter contra servidor HTTP falso, normalização de eventos, backoff/watchdog do supervisor. Rodam a cada mudança.
- **BDD (pytest-bdd)**: os cenários WHEN/THEN das specs são a fonte única — cada `#### Scenario` vira um cenário Gherkin em `tests/bdd/features/<capability>.feature`, tagado com a capability de origem para rastreabilidade spec→teste. Cenários que exigem banco usam Postgres efêmero (testcontainers); os de ciclo de vida de container usam o Docker real. A suíte BDD é o contrato de comportamento: spec scenario sem feature correspondente é lacuna; feature sem cenário na spec é escopo indevido.
- **E2E pelo browser (Playwright + pytest-playwright)**: jornadas completas contra um stack de teste dedicado (compose próprio): login e RBAC na UI, cadastro de sistema/conexão, chat com streaming, app proxiada com identidade, rollback por checkpoint.

Racional das escolhas: pytest-bdd mantém um único runner para as três camadas e liga os `.feature` diretamente às specs; Playwright vence Cypress/Selenium aqui por ser Python-nativo (mesma stack do portal), suportar WebSocket (chat e NiceGUI) e oferecer trace viewer para diagnóstico. Alternativas descartadas: behave (runner separado do pytest) e Cypress (ecossistema Node, duas stacks de teste).

**Determinismo no E2E**: a suíte roda por padrão com um **harness fake** — segunda implementação de `HarnessPort` que reproduz o padrão de eventos do opencode sem chamar LLM — exercitando portal, fila, supervisor, proxy e apps sem custo nem flakiness de modelo. O caminho real (opencode + provedor) fica nos testes de integração do adapter e num cenário E2E único tagado `@llm_real`, executado manualmente na verificação final.

## Risks / Trade-offs

- [API do `opencode serve` é experimental e pode mudar] → versão pinada na imagem; adapter é a única consumidora; spike de validação da API na primeira task de implementação.
- [NiceGUI sob path prefix + WebSocket pode apresentar quirks] → spike dedicado antes de congelar as guidelines; `root_path` documentado; escape hatch: migrar para subdomínios já abstraído (D2).
- [App gerada escreve em produção com a mesma credencial, sem gate] → risco aceito pelo dono do produto; recomendação operacional: primeiro sistema apontar para banco de homologação; gate de destrutivas é a próxima change.
- [Agente gera código quebrado; supervisor entra em restart loop] → healthcheck com backoff, erro visível no chat, rollback para checkpoint anterior em um clique.
- [Portal com acesso ao socket Docker = poder de root no host] → aceito para single-host interno; mitigação futura possível (socket proxy), fora do escopo.
- [Fila por sistema pode frustrar editores simultâneos] → estado da run visível a todos os editores do sistema (quem está com o agente, o que está rodando).
- [Consumo de LLM sem bloqueio pode gerar fatura surpresa] → dashboards de uso por sistema/usuário desde o MVP; bloqueio é change futura.
- [E2E pelo browser é lento e sujeito a flakiness] → escopo E2E limitado às jornadas críticas; harness fake para determinismo (D13); retries só em CI; trace viewer do Playwright para diagnóstico; caminho com LLM real isolado num cenário `@llm_real` manual.
- [BDD pode virar cerimônia oca (feature que só repete o teste unitário)] → convenção D13: features cobrem o comportamento observável dos cenários de spec (via API/UI), unitários cobrem o interno; nenhuma feature sem cenário de origem na spec.

## Migration Plan

1. Subir stack do portal (compose: Postgres, Traefik, portal) e aplicar migrações Alembic.
2. Buildar e pinar a imagem base; smoke test do supervisor + opencode serve isolado.
3. Criar o primeiro sistema apontando para um Postgres de homologação; rodar o fluxo E2E (chat → geração → app no ar).
4. Rollback: parar o stack do portal; containers de sistema e volumes permanecem intactos no host (reconciliação os reassume ao voltar).

## Open Questions

- ~~Superfície de eventos do `opencode serve`~~ **Resolvido no spike (task 5.1)**, contra opencode 1.19.5: `POST /session` cria sessão; `POST /session/{id}/prompt_async` dispara o agente sem bloquear; `GET /event` é SSE com envelopes `{id, type, properties}` — tipos relevantes: `session.updated`, `message.updated` (info com role/model/tokens), `message.part.updated` (part `text`|`tool`), `message.part.delta`, `session.status` ({type: busy|idle}), `session.diff`; interrupção via `POST /session/{id}/abort` (200); diffs por sessão em `GET /session/{id}/diff`. Provider id do GLM no catálogo (models.dev): `zhipuai`.
- ~~Caminho real com LLM (`@llm_real`)~~ **Executado e validado em 2026-11-02** (tasks 5.4/7.2), com GLM-4.6 via coding plan da Z.ai sobre Postgres de homologação: o agente analisou o schema via MCP (conexão `vendas`), gerou um CRUD NiceGUI completo (asyncpg + `DATABASE_URL_VENDAS`, SSO por token, venv própria via uv), o supervisor o colocou no ar em `/apps/homolog-crm` e checkpoint/uso de tokens foram registrados. Descobertas incorporadas: env da chave do catálogo é `ZHIPU_API_KEY`; coding plan usa `baseURL https://api.z.ai/api/coding/paas/v4` (config `GLM_BASE_URL`); normalizador tolera uso de tokens em formato int; supervisor usa o Python do venv da app e reaps filhos (Popen.poll).
- ~~Convenções finais de layout de projeto NiceGUI nas guidelines~~ **Resolvido no spike 6.1**: NiceGUI + WebSocket funcionam plenamente sob `/apps/{slug}` (Traefik stripPrefix), com uma exigência: a app gerada **não** deve definir `root_path` — o Traefik injeta `X-Forwarded-Prefix` e o Starlette o soma ao root_path, duplicando o prefixo dos assets. Guidelines atualizadas; `APP_ROOT_PATH` permanece como env para o modo subdomínio futuro.
- Necessidade real de chave LLM por sistema (override) além das chaves globais — decidir na implementação da tela de cadastro.
