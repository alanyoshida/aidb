# 0007 — Metadados em Postgres; credenciais cifradas em repouso

* Status: aceito
* Data: 2026-11-01
* Decidida em: change `appai-forge-mvp` (design D7)

## Contexto

O portal precisa de estado relacional (usuários, grupos, sistemas, conexões, runs, checkpoints, uso de tokens) e de guardar segredos (senhas de conexão de banco, chaves de LLM) que não podem vazar por interface, log ou evento.

## Decisão

Postgres dedicado do portal com SQLAlchemy + Alembic. Senhas de conexão e chaves de LLM cifradas com Fernet; a chave fica na configuração do portal. Credenciais são materializadas apenas como env do container do sistema; logs e eventos do agente nunca as contêm.

## Alternativas consideradas

- **SQLite** — descartado: single-writer atrapalha portal + workers de provisionamento/fila.
- **Vault externo** — descartado para a v1: mais um serviço para operar; cifra local atende o modelo de ameaça (host único interno).

## Consequências

Dump do banco sem a chave de cifra é inofensivo (bom). Rotação de chave exigirá migração própria (fica para necessidade real).
