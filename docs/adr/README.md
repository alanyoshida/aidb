# ADRs — Architecture Decision Records do AIDB

Registro das decisões arquiteturais e de produto da plataforma, em formato MADR (Markdown ADR), em português.

## Convenção

- Toda decisão arquitetural ou de produto relevante gera um ADR numerado sequencialmente (`NNNN-titulo-em-kebab-case.md`).
- Um ADR, uma decisão. Decisões revogadas mudam de status (`aceito` → `substituído por NNNN`), nunca são apagadas.
- Decisões tomadas durante a implementação de uma change também viram ADR e são referenciadas no `design.md` da change.

## Índice

| ADR | Decisão | Status |
|---|---|---|
| [0001](0001-monorepo-portal-base-image-deploy.md) | Monorepo com três entregáveis | aceito |
| [0002](0002-traefik-edge-com-config-dinamica.md) | Traefik como edge proxy com config dinâmica; path agora, subdomínio depois | aceito |
| [0003](0003-container-por-sistema-com-supervisor-pid1.md) | Container por sistema com supervisor próprio como PID 1 | aceito |
| [0004](0004-opencode-serve-atras-de-adapter-com-fila-no-portal.md) | Harness opencode serve atrás de adapter; fila de execução no portal | aceito |
| [0005](0005-streaming-do-chat-por-websocket.md) | Streaming do chat por WebSocket | aceito |
| [0006](0006-identidade-injetada-por-token-hmac.md) | Identidade do portal propagada às apps por token HMAC | aceito |
| [0007](0007-metadados-em-postgres-e-credenciais-cifradas.md) | Metadados em Postgres; credenciais cifradas em repouso | aceito |
| [0008](0008-mcp-para-agente-driver-direto-para-app.md) | MCP para o agente analisar; driver direto para a app gerada | aceito |
| [0009](0009-git-por-sistema-com-checkpoints.md) | Git por sistema com checkpoints por execução | aceito |
| [0010](0010-app-unica-em-nicegui-em-pt-br.md) | App única em NiceGUI por sistema, interface em PT-BR | aceito |
| [0011](0011-guidelines-de-geracao-editaveis-pelo-admin.md) | Guidelines de geração centralizadas, editáveis pelo admin | aceito |
| [0012](0012-llm-via-api-externa-provedor-por-sistema.md) | LLM via API externa; provedor por sistema (default GLM); custo só com visibilidade | aceito |
| [0013](0013-containers-sempre-ativos-com-reconciliacao.md) | Containers sempre ativos, com reconciliação e limites padrão | aceito |
| [0014](0014-rbac-com-tipos-globais-de-usuario.md) | RBAC com tipos globais de usuário; só editor cria sistemas | aceito |
| [0015](0015-mesma-credencial-de-producao-para-app-gerada.md) | App gerada usa a mesma credencial de produção; gate de destrutivas adiado | aceito (gate: ver 0017) |
| [0016](0016-testes-em-tres-camadas-unit-bdd-e2e.md) | Testes em três camadas: unitários, BDD e E2E pelo browser | aceito |
| [0017](0017-gate-de-operacoes-destrutivas-com-classificador-sql.md) | Gate de operações destrutivas com classificador SQL único (sqlglot) | aceito |
