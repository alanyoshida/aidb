# Proposal

## Why

O spec `db-connections` restringe conexões ao PostgreSQL, mas usuários precisam conectar agentes e apps geradas ao BigQuery — o data warehouse mais comum em ambientes GCP. A autenticação do BigQuery (Service Account JSON) e sua ausência de TCP invalidam os campos e o fluxo atuais.

## What Changes

- **Modelo**: `password_encrypted` ampliado de `String(500)` para `Text` (SA JSON criptografado cabe ~2–3 KB); migration Alembic.
- **Serviço de conexões**: `test_connection` e `connection_string` despacham para BigQuery via `google-cloud-bigquery`; `register_connection` extrai automaticamente o service account email do JSON para o campo `username`.
- **Convenção de env var**: conexão BigQuery gera `DATABASE_URL_<NOME>=bigquery://<project>/<dataset>?credentials_base64=<b64>` — mesmo padrão `DATABASE_URL_*` que Postgres/MySQL; app gerada usa `sqlalchemy-bigquery` sem aprender nova convenção.
- **MCP server**: novo driver BigQuery via `google-cloud-bigquery` em thread executor (client síncrono); `list_tables` e `describe_table` via `INFORMATION_SCHEMA`; `read_query` com gate `is_read_only` inalterado.
- **Base image**: adiciona `google-cloud-bigquery sqlalchemy-bigquery` ao pip.
- **Portal**: adiciona `google-cloud-bigquery` para teste de conexão; `pymysql` já presente.
- **UI**: dialog de nova/editar conexão reestrutura campos dinamicamente para BigQuery (Project ID, Dataset, SA JSON textarea) ocultando host/porta/usuário.

## Capabilities

### New Capabilities

- `db-bigquery`: Comportamento específico de conexões BigQuery: credencial via Service Account JSON, campos project/dataset, geração de `bigquery://` URL com `credentials_base64`, driver MCP assíncrono via executor.

### Modified Capabilities

- `db-connections`: O requisito "único tipo suportado é PostgreSQL" é estendido para incluir BigQuery. Os requisitos de teste antes de salvar, credenciais protegidas e provisão via MCP e env var continuam válidos e se aplicam igualmente ao BigQuery.

## Impact

- `portal/appaiforge/models.py` + migration Alembic
- `portal/appaiforge/services/connections.py`
- `portal/pyproject.toml` + `portal/uv.lock`
- `base-image/Dockerfile`
- `base-image/gated-mcp/mcp_server.py`
- `portal/appaiforge/provisioning.py`
- `portal/appaiforge/ui/system_detail.py`
- Testes unitários e E2E (E2E com BQ real é follow-up; testes unitários mockam o cliente)
