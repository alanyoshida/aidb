# Tasks

## 1. Spec

- [x] 1.1 Adicionar a `portal/tests/unit/test_connections.py` um teste de `connection_string` (em `portal/appaiforge/services/connections.py`) que confirme os schemes `postgresql://`, `mysql://` e `bigquery://…?credentials_base64=` (nenhum teste cobre isso hoje); verificar com `uv run pytest tests/unit/test_connections.py`.
- [x] 1.2 Reescrever o parágrafo de Purpose de `openspec/specs/db-connections/spec.md` listando PostgreSQL, MySQL e BigQuery e removendo "No MVP o único tipo suportado é PostgreSQL"; verificar com `grep -n "único tipo" openspec/specs/db-connections/spec.md` sem resultados.
