# Tasks

## 1. Modelo e migration

- [x] 1.1 Alterar `password_encrypted` de `String(500)` para `Text` em `models.py`; criar migration Alembic e verificar com `alembic upgrade head --sql` que a coluna aparece como TEXT na tabela `db_connections`.

## 2. Serviço — teste e connection string

- [x] 2.1 Implementar `_test_bigquery(project, dataset, sa_json)` em `connections.py`: cria `bigquery.Client` com `service_account.Credentials` (scope `bigquery.readonly`), executa query leve no INFORMATION_SCHEMA, levanta `ConnectionFailed` em qualquer erro (JSON inválido, permissão negada, projeto/dataset inexistente); adicionar `google-cloud-bigquery` a `pyproject.toml`.
- [x] 2.2 Atualizar `test_connection` para despachar `bigquery`; atualizar `connection_string` para gerar `bigquery://<host>/<database>?credentials_base64=<b64>`; atualizar `register_connection` para extrair `client_email` do SA JSON e persistir em `username`; verificar com unit tests que a URL gerada contém `credentials_base64` e que o email é extraído corretamente.

## 3. Base image

- [x] 3.1 Adicionar `google-cloud-bigquery sqlalchemy-bigquery` ao `pip install` em `base-image/Dockerfile`; verificar que `docker build -t appaiforge-base ./base-image` conclui sem erro.

## 4. MCP server

- [x] 4.1 Adicionar driver BigQuery em `mcp_server.py`: parsear `credentials_base64` da URL quando `kind == "bigquery"`, criar `bigquery.Client` via `run_in_executor`; adaptar `list_tables` e `describe_table` para usar `INFORMATION_SCHEMA` do BigQuery (`project.dataset.INFORMATION_SCHEMA.TABLES/COLUMNS`); adaptar `read_query` para executar via client BQ; verificar com unit test (mock de `bigquery.Client`) que `list_tables` retorna tabelas e que escrita é bloqueada pelo gate.

## 5. Provisionamento

- [x] 5.1 Verificar que `write_opencode_config` e `_connection_env` em `provisioning.py` geram o URL BQ correto (ambos já chamam `connection_string`, que agora cobre BigQuery); verificar com unit test que o `opencode.json` gerado contém `bigquery://` e `credentials_base64` para uma conexão `kind="bigquery"`.

## 6. UI

- [x] 6.1 Adicionar `BigQuery` às `_KIND_OPTIONS` em `ui/system_detail.py`; reestruturar dialogs de criar e editar conexão com campos dinâmicos: quando `kind == "bigquery"`, ocultar Host/Porta/Usuário/Senha e exibir Project ID (mapeado para `host`), Dataset (mapeado para `database`), Service Account JSON (textarea mapeado para `password`); exibir o email do SA (`username`) após salvar no card da conexão; verificar manualmente que a troca de tipo oculta/exibe os campos corretos.

## 7. Verificação integrada (Postgres/MySQL não regridem)

- [x] 7.1 Rodar `cd portal && uv run pytest tests/unit tests/bdd` — verdes (sem regressão em Postgres/MySQL).

## Workflow follow-up

- Adicionar serviço `bigquery-emulator` (ou conta GCP de teste) ao stack E2E e rodar `uv run pytest tests/e2e/test_systems.py` com conexão BigQuery.
- Documentar no cadastro UI que o SA deve ter a role mínima `roles/bigquery.dataViewer`.
- Arquivar a change após revisão.
