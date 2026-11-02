# 0008 — MCP para o agente analisar; driver direto para a app gerada

* Status: aceito
* Data: 2026-11-01
* Decidida em: change `appai-forge-mvp` (design D8)

## Contexto

O agente precisa explorar schema e dados de forma interativa (ferramentas de leitura), enquanto a app gerada precisa de acesso runtime de baixa latência e transacional ao mesmo banco.

## Decisão

Cada conexão ativa é provisionada ao agente como um MCP server Postgres (no `opencode.json` do sistema, connection string via env). A app gerada conecta por driver direto (asyncpg) com a mesma connection string via env `DATABASE_URL_<CONEXAO>`. Sem camada intermediária de dados: MCP é ferramenta de análise, não runtime.

## Alternativas consideradas

- **App usar MCP em runtime** — descartado: latência e complexidade indevidas para operação CRUD.
- **Camada de dados intermediária (API de dados própria)** — descartada na v1: peça extra sem necessidade validada.

## Consequências

Remoção de uma conexão reverte os dois provisionamentos (spec `db-connections`). A app compartilha a credencial da conexão — ver ADR 0015.
