# Design

## Context

Ver `proposal.md — Why`. Estado atual relevante:

- `DbConnection.password_encrypted` é `String(500)` — um Service Account JSON cifrado ocupa ~2–3 KB (base64 AES-256 de ~2 KB de JSON). Precisa virar `Text`.
- `test_connection()` despacha por `kind` (Postgres/MySQL já implementado em `db-multi-tipo`).
- `connection_string()` gera `{scheme}://user:pass@host:port/db` — BigQuery não tem host/porta TCP.
- `mcp_server.py` recebe `(DATABASE_URL, kind)` como argv; já abstrai driver por kind.
- `write_opencode_config` passa `(url, kind)` ao MCP server.
- UI usa `_KIND_OPTIONS` + campos estáticos — BQ precisa de campos completamente diferentes.

## Goals / Non-Goals

**Goals:**
- Suporte a BigQuery no cadastro, teste, MCP, env var e app gerada.
- `DATABASE_URL_*` como única convenção de credencial (sem nova convenção para o agente aprender).
- Mesmas ferramentas MCP (`list_tables`, `describe_table`, `read_query`) para todos os tipos.

**Non-Goals:**
- Application Default Credentials (ADC) — requer infraestrutura GCP no container, fora de escopo.
- E2E automatizado com GCP real — custo e complexidade de CI; fica como follow-up.
- Suporte a múltiplos datasets num mesmo projeto via conexão única.
- Workload Identity / OAuth flow.

## Decisions

### D1. `credentials_base64` inline na DATABASE_URL

```
bigquery://<project>/<dataset>?credentials_base64=<urlsafe-b64(sa_json)>
```

O `connection_string()` codifica o SA JSON plaintext em base64 URL-safe e o emite na URL. O MCP server e a app gerada parseiam a URL e reconstroem as credenciais:

```python
# connections.py
def connection_string(conn, password):  # password = SA JSON plaintext
    if conn.kind == "bigquery":
        b64 = base64.urlsafe_b64encode(password.encode()).decode()
        return f"bigquery://{conn.host}/{conn.database}?credentials_base64={b64}"
```

**Alternativa**: env vars separados `BIGQUERY_PROJECT_*` + arquivo de credencial. Requer mudança na provisão, no MCP server e exige que o agente aprenda nova convenção.

### D2. `google-cloud-bigquery` síncrono em thread executor no MCP server

FastMCP usa asyncio; `google-cloud-bigquery` é síncrono. Solução via `run_in_executor`:

```python
async def _bq_fetch(sql: str) -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _bq_query_sync(sql))
```

`_bq_query_sync` cria (ou reutiliza) um `bigquery.Client` com as credenciais parseadas da URL. Queries BQ são network-bound; o thread pool padrão do executor aguenta bem.

**Alternativa**: `bigquery_async` (terceiros, menos maduro) ou `google-cloud-bigquery-storage` (mais complexo, somente leitura em streams). `run_in_executor` é o caminho pragmático.

### D3. `host` como project_id, `database` como dataset (sem novos campos)

Para BQ:
- `host` = GCP project ID (ex: `meu-projeto-gcp`)
- `port` = 0 (sem sentido, mas mantido para não fazer `port` nullable)
- `database` = dataset (ex: `analytics`)
- `username` = service account email (extraído do JSON em `register_connection`)
- `password_encrypted` = SA JSON cifrado (`Text`, sem limite de tamanho)

Reutilizar campos existentes evita uma migration mais invasiva (colunas novas + nullable). A UI oculta `host` como "Project ID" e `database` como "Dataset" para BQ.

**Alternativa**: campos `project_id` e `dataset` explícitos. Mais semântico, mas exige migration + mudanças em todos os lugares que leem `host`/`database`.

### D4. UI com campos dinâmicos por kind (show/hide)

O dialog de criar/editar conexão já tem `_KIND_OPTIONS`. Para BQ, um segundo bloco de campos fica visível/oculto:

```
Tipo: [PostgreSQL | MySQL | BigQuery]

-- Para Postgres/MySQL (visível quando kind != bigquery):
  Host, Porta, Banco, Usuário, Senha

-- Para BigQuery (visível quando kind == bigquery):
  Project ID (host), Dataset (database), Service Account JSON (textarea)
  [email do SA exibido após salvar, em modo somente leitura]
```

NiceGUI suporta `set_visibility(bool)` em componentes — sem reconstruir o dialog.

### D5. `test_connection` para BQ: query leve no INFORMATION_SCHEMA

```python
def _test_bigquery(project, dataset, sa_json):
    from google.cloud import bigquery
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_json),
        scopes=["https://www.googleapis.com/auth/bigquery.readonly"],
    )
    client = bigquery.Client(project=project, credentials=creds)
    list(client.query(
        f"SELECT 1 FROM `{project}.{dataset}.INFORMATION_SCHEMA.TABLES` LIMIT 1"
    ).result())
```

Usa `bigquery.readonly` scope — mínimo necessário para teste. Levanta `ConnectionFailed` em qualquer erro.

## Risks / Trade-offs

- **SA JSON amplo**: um Service Account pode ter acesso além do BigQuery (Storage, etc.). AIDB não restringe o escopo do SA — documentar que o usuário deve criar SAs com permissão mínima (`roles/bigquery.dataViewer`).
- **URL longa**: `credentials_base64` adiciona ~4 KB à DATABASE_URL. Não vai para log (env var), mas é passada como argv[1] ao MCP server — visível em `ps aux`. Mitigação: `/proc/self/cmdline` não é acessível a outros usuários no container isolado.
- **Custo de query**: todo `test_connection` faz uma query real no BQ (cobrada). Para o plano free tier (1 TB/mês), o custo é desprezível. Documentar no cadastro.
- **`sqlalchemy-bigquery` na base-image**: ~15 MB de dependências extras (`google-cloud-bigquery` + transitivas).

## Migration Plan

1. Alembic: `ALTER COLUMN password_encrypted TYPE TEXT` (sem default, retrocompatível).
2. `connections.py`: `_test_bigquery`, `connection_string` BQ, `register_connection` extrai email.
3. `pyproject.toml` + `portal.Dockerfile`: `google-cloud-bigquery`.
4. `base-image/Dockerfile`: `google-cloud-bigquery sqlalchemy-bigquery`.
5. `mcp_server.py`: driver BigQuery via executor, `list_tables`/`describe_table`/`read_query` BQ.
6. `provisioning.py`: `connection_string` já cobre BQ via D1.
7. UI: `system_detail.py` — campos dinâmicos por kind.
8. Rollback: reverter migration (TEXT → VARCHAR(500) só falha se existir valor > 500 chars, o que não ocorre para registros Postgres/MySQL pré-existentes); remover código BQ.
