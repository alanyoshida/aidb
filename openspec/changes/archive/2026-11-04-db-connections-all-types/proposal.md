# Proposal

## Why

A spec `db-connections` já descreve conexões PostgreSQL, MySQL e BigQuery, mas o texto de propósito ainda afirma que "no MVP o único tipo suportado é PostgreSQL", e o requisito do `DATABASE_URL_<NOME>` lista só os schemes de PostgreSQL e MySQL, omitindo o BigQuery que o código já entrega (`bigquery://…?credentials_base64=…`). A spec se contradiz e induz leitores a achar que BigQuery não é provisionado à app.

## What Changes

- Requisito "App gerada recebe credenciais de banco conforme tipo" passa a cobrir os três tipos, incluindo o scheme `bigquery://` com `credentials_base64`, com um cenário para BigQuery.
- O parágrafo de propósito da spec é reescrito para listar os três tipos e remover a frase do MVP. Deltas não alteram o Purpose, então essa edição é feita à mão, no mesmo commit do arquivamento.

## Capabilities

### New Capabilities

(nenhuma)

### Modified Capabilities

- `db-connections`: o requisito de credenciais da app gerada passa a incluir o scheme do BigQuery.

## Impact

- Somente documentação de spec: `openspec/specs/db-connections/spec.md`. Nenhuma mudança de código ou de comportamento — o código já entrega o scheme `bigquery://` (`portal/appaiforge/services/connections.py`) e a spec `db-bigquery` já o cobre.
