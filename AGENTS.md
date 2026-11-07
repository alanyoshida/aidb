# AGENTS.md

Guia para agentes que trabalham neste repositório. Produto: **AIDB** — portal que gera
apps de gestão (NiceGUI, Python) sobre bancos PostgreSQL, MySQL e BigQuery, conduzido por chat. A documentação de
produto fica no [`README.md`](README.md); decisões em [`docs/adr/`](docs/adr/README.md).

## Estrutura

- `portal/` — app FastAPI + NiceGUI (`appaiforge/`), migrações (`migrations/`), testes (`tests/`).
  - `appaiforge/ui/` — páginas NiceGUI; `ui/theme.py` define tema e tokens, `ui/common.py` o `notify()` e a topbar, `ui/chat.py` o chat.
  - `appaiforge/harness/` — adapters do agente (`opencode.py` real, `fake.py` determinístico).
  - `appaiforge/services/` — conexões, provedores/chaves de LLM, auditoria, catálogo.
- `base-image/` — Dockerfile da imagem dos sistemas + `afsupervisor` (PID 1) + `gated-mcp/`.
- `deploy/` — `docker-compose.yml` (postgres, mysql, traefik, portal) e `docker-compose.e2e.yml`.
- `docs/adr/` — decisões de arquitetura (MADR). `openspec/specs/` — specs vigentes;
  `openspec/changes/` — changes ativas; `openspec/changes/archive/` — histórico.
- `docs/roadmap-confinamento-do-agente.md` — roadmap de longa duração (9 etapas, uma change por
  etapa) de confinamento e política do agente. Leia antes de propor change nessa área.

## Comandos

```bash
# Stack local (do zero)
cd deploy && docker compose up -d --build
docker compose exec portal alembic upgrade head
# O código do portal vai dentro da imagem (sem bind do host): após editar, rebuild
docker compose -f deploy/docker-compose.yml build portal && docker compose -f deploy/docker-compose.yml up -d portal

# Testes (a partir de portal/)
uv sync
uv run pytest tests/unit          # rápidos, sem Docker
uv run pytest tests/bdd           # cenários Gherkin das specs
uv run pytest tests/integration   # Docker real + Postgres efêmero
uv run pytest tests/e2e           # Playwright contra o stack E2E

# E2E isolado (porta 8081, harness fake, nunca toca o ambiente real)
docker compose -f deploy/docker-compose.e2e.yml up -d --build
cd portal && uv run pytest tests/e2e
```

Não há config de lint/format (ruff/black) no repositório — não invente uma; siga o estilo existente.

## Convenções

- Idioma do produto e do código: **PT-BR** (UI, comentários de domínio, mensagens). Sem comentários
  novos no código, a menos que pedido.
- Marque testes novos com os markers já definidos: `e2e`, `integration`, `llm_real`
  (`llm_real` nunca roda em CI).
- A suíte E2E nunca deve apontar para o stack de produção; use o compose E2E dedicado (8081).
- Toda SQL contra bancos de conexão passa pelo **gate** (`gate.py`): `normal` executa,
  `confirmável` aguarda aprovação, **DDL é sempre bloqueada** (ADR 0017, spec `destructive-gate`). Não burle essa camada.
- Credenciais são cifradas nos metadados (ADR 0007); nunca logue segredos nem os inclua em commits.
  A config do agente (chaves, MCP) vive em `CONFIGS_DIR`, fora do workspace que o agente edita.
- O runtime de cada agente se declara em `appaiforge/agent_profiles.py` (comando, cwd, config,
  env de credencial, caminhos) — o supervisor e o provisionamento lêem o perfil, nunca embutem um
  agente por nome (ADR 0018). Adicionar um agente é registrar um perfil, não editar os dois.
  Containers de sistema novos sobem com identidade de execução reduzida (não-root, sem
  capabilities); sistemas criados antes do ADR 0018 ficam no modo antigo, sem migração automática.
- Cores da UI: use os tokens `--ap-*` / `--ch-*` e `ui/common.py:notify()`; não fixe cores nem use
  `ui.notify(type=...)` (o Quasar sobrescreve o tema). Todo par texto/fundo novo deve manter contraste
  WCAG AA nas 12 combinações de tema (spec `portal-theming`).
- Horários são gravados em UTC e convertidos na UI por `display_timezone`.
- Mudança de schema exige migração Alembic encadeada ao head atual (`alembic heads` deve listar um só).
- O compose sobe em harness `fake` por padrão; para o agente real use `APPAIFORGE_HARNESS_MODE=opencode`
  (em `deploy/.env`, não versionado).
- **NUNCA encadeie `docker ps --filter ... | xargs docker rm -f` (ou similar) num comando só, pra
  limpar containers reais.** Isso já aconteceu DUAS vezes na mesma sessão, cada vez com um filtro
  diferente: `--filter 'label=appaiforge.managed=true'` sozinho (pega todo sistema, de teste ou
  real) e depois `--filter 'label=appaiforge.managed=true' --filter 'network=appaiforge-net'` (achando
  que o filtro de rede protegia — `appaiforge-net` É a rede do stack real de dev, não uma rede de
  teste). As duas vezes apagaram os 4 sistemas reais do usuário (`homolog-crm`, `pets`, `projetos`,
  `chat-a0a915bd`) junto dos containers de teste. Nenhum filtro de label/rede/prefixo é confiável
  sozinho — mesmo um que pareça escopado pode bater em produção sem avisar.
  **Regra mecânica, sem exceção**: toda limpeza é SEMPRE dois passos separados —
  1. `docker ps -a --filter ...` (ou `grep` num `docker ps -a` simples) pra LISTAR, sem `rm` no mesmo
     comando; leia a lista inteira e confirme visualmente que nenhum nome bate em
     `homolog-crm|pets|projetos|chat-a0a915bd` (ou o que mais for conhecido como sistema real na
     hora);
  2. só então `docker rm -f <nome1> <nome2> ...` com os nomes exatos, digitados/colados da lista que
     você acabou de revisar — nunca um pipe direto de `docker ps` pra `rm`/`xargs`, mesmo com filtro.
  Se isso já aconteceu: o workspace (bind do host) e a linha no banco sobrevivem ao `docker rm`;
  `provisioning.reconcile()` (chamado de dentro do container do portal) recria o container a partir
  deles sem perda — mas o objetivo é nunca precisar disso.

## Fluxo OpenSpec

Mudanças seguem o workflow OpenSpec (specs em `openspec/specs/`, propostas em
`openspec/changes/`). Antes de implementar, leia a change ativa (se houver) e a spec afetada. Não edite
specs diretamente para refletir código novo sem passar pelo fluxo de change: propor → aplicar →
arquivar (o arquivamento sincroniza os deltas para `openspec/specs/`). Mudança de decisão arquitetural
vira ADR sequencial em `docs/adr/` (o próximo número é 0019).

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **aidb** (4096 symbols, 8289 relationships, 288 execution flows).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` — e.g. `bunx gitnexus@latest analyze` (npm 11 npx crash; #1939).

## Always Do

- **MUST run impact before editing.** Use `impact({target: "symbolName", direction: "upstream"})` or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .`; report callers, processes, and risk. Never substitute grep for graph analysis.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check — a zero means unseen, not unaffected; re-run it. For regression review: `detect_changes({scope: "compare", base_ref: "main"})` or `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- MUST warn on HIGH/CRITICAL `risk` pre-edit; never use `riskSharedAxes` to waive a HIGH/CRITICAL `risk` warning. Compare File/symbol: MCP File omits axes; Graph-RAG expands File.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** An empty caller set is not evidence the symbol is unused — it can also mean the callers are not resolvable by the index (plain-object property access, dynamic dispatch, cross-language calls). `impact` pairs `UNKNOWN` with a `riskNote` saying so. Confirm with a text search before treating the symbol as safe to change or delete; do not proceed on the strength of a zero.
- **MUST use `query({search_query: "concept"})` for concepts/flows, `context({name: "symbolName"})` for a named symbol, or `impact` for blast radius, on read-only callers, dependencies, imports, or execution flow.** Graph first; text search only for empty/`UNKNOWN`/literals.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis, and never read `UNKNOWN` as an all-clear — it means the walk could not answer, which is the one verdict that requires confirming by other means.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource | Use for |
| --- | --- |
| `gitnexus://repo/aidb/context` | Codebase overview, check index freshness |
| `gitnexus://repo/aidb/clusters` | All functional areas |
| `gitnexus://repo/aidb/processes` | All execution flows |
| `gitnexus://repo/aidb/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
| --- | --- |
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
