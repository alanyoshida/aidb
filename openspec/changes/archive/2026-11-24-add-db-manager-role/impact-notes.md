# Impacto (task 1.1) — para a descrição do PR

Rodado com o GitNexus (`repo: aidb-db-manager`, commit 273428f), `impact` upstream:

| Símbolo | Risco | Diretos | Total | Observação |
|---|---|---|---|---|
| `DbConnection` | CRITICAL | 41 | 63 | `epistemic: lower-bound` (despacho via `Base`) |
| `User` | CRITICAL | 41 | 63 | idem |
| `Session` | CRITICAL | 41 | 63 | idem |

Os três resultados são idênticos: o índice conta quem importa `models.py`, não quem usa cada
classe. Por isso os pontos reais foram levantados por busca de texto.

## Quem lê `DbConnection.system_id`, `.name` ou `.access_mode`

| Arquivo | Uso | Task |
|---|---|---|
| `services/connections.py` | cadastro, edição, listagem, degradadas, saúde, remoção | 3.1–3.4, 4.x |
| `provisioning.py` `db_connections_manifest` | manifesto do sidecar | 5.1 |
| `provisioning.py` `_connection_env` | `DATABASE_URL_*` | 5.1 |
| `provisioning.py` `write_opencode_config` | MCP do opencode (`access_mode`) | 5.1, 6.4 |
| `provisioning.py` (config Claude Code) | MCP do Claude Code (`access_mode`) | 5.1, 6.4 |
| `provisioning.py` checagem de saúde | ids por sistema | 3.3 |
| `deploy.py` `check_manifest` | nomes exigidos | 5.2 |
| `git_sync.py` manifesto | nome e tipo | 5.3 |
| `ui/system_detail.py`, `ui/admin.py` | via serviço | 7.x |

Testes que usam o modelo antigo e precisam ser atualizados: `tests/unit/test_connections.py`,
`test_claude_code_provisioning.py`, `test_llm_provisioning.py`, `test_reconciler_health.py`,
`tests/integration/test_connection_live.py`, `test_connections_manifest.py`,
`test_db_gate_proxy.py`, `test_deploy_versions.py`, `test_network_perimeter.py`,
`test_provisioning.py`, `tests/e2e/test_systems.py`, `tests/e2e_gitlab/test_deploy_only.py`.

## `detect_changes` antes do commit (task 8.4)

`scope: all`, `repo: aidb-db-manager`: 243 símbolos alterados em 66 arquivos, 123 fluxos de execução
afetados, risco **critical**. Resultado completo (`partial` e `truncated` ausentes). O risco vem de a
mudança tocar autenticação (`resolve_principal`, OIDC), provisionamento (manifesto do sidecar,
`DATABASE_URL_*`, config do agente), o laço de reconciliação e o proxy de banco.

Mitigação: suíte unitária e BDD completa, testes da imagem base, integração com Docker real e os
cenários E2E listados no PR.

## Checagem da migração num stack real (task 8.3)

Portal antigo (código do commit 273428f) num Postgres próprio, schema em `a0b1c2d3e4f5`, com o
sistema `migcheck` e três conexões no modelo antigo: `vendas` (read_write, com descrição),
`Estoque legado` (read_only, nome com espaço) e `base`. Depois, `alembic upgrade head` com o portal
novo (`b6c7d8e9f0a1`), boot do portal novo e recriação do container pelo código novo.

| O que se comparou | Resultado |
|---|---|
| `DATABASE_URL_*` do container do sistema | idêntico (`BASE`, `ESTOQUE_LEGADO`, `VENDAS`, mesmas portas) |
| MCP do agente no `opencode.json` | idêntico (rótulos, URLs e modos) |
| Manifesto do sidecar | mesmas entradas e DSNs; só ganhou o campo `mode` |
| Catálogo | `vendas (migcheck)`, `Estoque legado (migcheck)`, `base (migcheck)` |
| Autorizações | três ativas, alias = nome antigo, teto = modo = `access_mode` antigo, sem avisos |

Achado corrigido: o alias migrado `Estoque legado` não passa no formato de hoje, e a reativação
o sugeria assim. A sugestão agora normaliza esse caso (`estoque-legado`), que gera a mesma
`DATABASE_URL_ESTOQUE_LEGADO` (teste `test_alias_migrado_fora_do_formato_reativa_com_a_mesma_variavel`).

## Verificação final (tasks 8.1, 8.2 e 8.4)

| Suíte | Resultado |
|---|---|
| `tests/unit` + `tests/bdd` (`-n 8`) | 919 passaram |
| `base-image/` (dbproxy, gated-mcp, httpproxy, claude-code-shim) | todos passaram |
| `tests/integration` (Docker) | 129 passaram |
| `tests/integration -k kubernetes` | 36 passaram, com `appaiforge/base:1.11.0` e `appaiforge/claude-code:1.11.0` carregadas no kind |
| `tests/e2e` | 38 passaram na rodada cheia; os 2 restantes passaram rodados à parte (ver abaixo) |
| `tests/e2e_oidc` | 9 passaram |
| `tests/e2e_gitlab` | 8 passaram, 1 pulado (piloto Kubernetes, só com `AIDB_PILOT_K8S=1`) |

- O stack GitLab foi atualizado pelo caminho real (`alembic upgrade head` de `a0b1c2d3e4f5` para
  `b6c7d8e9f0a1`) com os dados do piloto preservados. Os stacks principal e OIDC foram recriados
  com volume novo, porque o schema antigo deles vinha de `create_all`, sem Alembic.
- Achados dos E2E, corrigidos: o painel de autorizações do catálogo fechava a cada autorização,
  mudança de teto ou revogação (agora guarda quais estão abertos); `test_chat.py` ainda cadastrava
  conexão pela aba do sistema; `test_databases.py` não abria o catálogo antes de revogar; a limpeza
  de `tests/e2e/conftest.py` apagava conexões por `system_id`.
- `test_admin_gerencia_acoes_de_grupo` falhou uma vez na rodada cheia esperando `group.delete` na
  auditoria e passou isolado; o teste e esse fluxo não foram alterados pela mudança.
- Num banco novo, o seed do admin de demonstração não roda, porque o break-glass é criado antes e o
  seed exige zero usuários. O comportamento é anterior à mudança; nos testes o admin foi criado com
  `appaiforge create-admin`.
