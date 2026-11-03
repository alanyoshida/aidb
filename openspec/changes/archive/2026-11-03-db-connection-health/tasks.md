# Tasks

## 1. Modelo e migration

- [x] 1.1 Adicionar `status: Mapped[str]` (default `"unknown"`) e `status_checked_at: Mapped[datetime | None]` em `DbConnection` em `models.py`; criar migration Alembic e verificar com `alembic upgrade head --sql` que os dois campos aparecem na tabela `db_connections`.

## 2. Serviço de health check

- [x] 2.1 Implementar `check_connection_health(conn_id: str) -> None` em `services/connections.py`: testa com timeout de 2s, atualiza `status` e `status_checked_at`, nunca levanta exceção; verificar com unit test que status vira `"healthy"` em conexão válida e `"degraded"` em conexão inacessível (mock do psycopg.connect).
- [x] 2.2 Atualizar `_to_safe()` para incluir `status` e `status_checked_at`; verificar com unit test que a listagem retorna os campos sem expor senha.

## 3. Integração no reconciliador

- [x] 3.1 Chamar `check_connection_health` para cada conexão dos sistemas ativos em `provisioning.reconcile()`; verificar com unit test que o reconciler chama o check para cada conexão de um sistema ativo e não chama para sistemas arquivados.

## 4. UI — badge de saúde

- [x] 4.1 Exibir badge de status (verde/amarelo/cinza) em cada card de conexão em `ui/system_detail.py`, usando `status` do `list_connections`; verificar manualmente que badge verde aparece para uma conexão ativa após reconciliação.

## 5. UI admin — conexões degradadas

- [x] 5.1 Adicionar seção "Conexões degradadas" na área admin (`ui/admin.py`), listando sistemas e conexões com `status = "degraded"`; verificar com unit test de `admin.py` que a listagem aparece quando há conexão degradada e fica vazia quando não há.

## 6. Verificação integrada

- [x] 6.1 Rodar `cd portal && uv run pytest tests/unit tests/bdd` — verdes.

## Workflow follow-up

- Subir stack E2E e verificar manualmente que o badge muda de "desconhecido" para "saudável" após o reconciler rodar.
- Arquivar a change após revisão.
