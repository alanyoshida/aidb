# Tasks

## 1. Fundação da auditoria de gestão

- [x] 1.1 Adicionar o modelo `ManagementAudit` (autor, ação, recurso, alvo, sistema, detalhes, data) em `models.py` e a migration Alembic correspondente; verificar com `alembic upgrade head` no stack e conferir a tabela criada.
- [x] 1.2 Implementar o serviço `audit.record(...)` (chamado por cada mutador de gestão), `audit.list_global(filtros)` e `audit.list_by_system(system_id)`; verificar com `tests/unit/test_management_audit.py` cobrindo gravação, filtros e ausência de campos de segredo.

## 2. Conexões: editar e remover

- [x] 2.1 Implementar `connections.update_connection(system, connection_id, ...)` com senha **opcional** (vazia mantém a atual), teste de conexão obrigatório quando muda e `_refresh_provisioning`; registrar auditoria `conn.update`. Verificar com unit test (vazio mantém; preenchido troca; inválido recusa).
- [x] 2.2 Na aba Conexões, adicionar ações **Editar** e **Remover** por conexão (dono/admin), com diálogo de edição (senha opcional) e confirmação de remoção; no remover, chamar `remove_connection` e registrar auditoria. Verificar por E2E em `tests/e2e/test_systems.py` (editar metadados reflete na lista; remover tira o card).

## 3. Sistema: renomear e editar provedor/modelo

- [x] 3.1 Implementar `systems.rename_system(system_id, name)` (dono/admin, slug imutável) com auditoria `system.rename`; verificar com unit test e com o cenário BDD correspondente.
- [x] 3.2 Expor mapa de modelos conhecidos por provedor no `config.py` (padrão atual como primeiro); verificar com unit test do mapa.
- [x] 3.3 No cabeçalho do sistema, adicionar **Renomear** e **Editar provedor/modelo** (select de modelos por provedor) reusando `set_provider`, com auditoria `system.provider`; verificar por E2E (renomear reflete no cabeçalho e na lista; trocar provedor reflete no cabeçalho).

## 4. Usuários: editar tipo, desativar e excluir

- [x] 4.1 Adicionar `directory.update_user_type(email, tipo)` (admin) e auditoria `user.type`; passar a registrar auditoria `user.active` em `set_user_active`. Verificar com unit tests das duas operações.
- [x] 4.2 Implementar `directory.delete_user(email, actor)` (admin): remove `group_members` e sessões do usuário, transfere `systems.owner_id` para o admin executor, anula as FKs de histórico (preservando o e-mail) e registra auditoria `user.delete` com os ids transferidos. Verificar com unit test (vínculos apagados; posse transferida; histórico preservado; auditoria sem segredo).
- [x] 4.3 Na tabela de usuários do `/admin`, adicionar ações por linha: editar tipo, ativar/desativar e **Excluir** com confirmação (informando quantos sistemas serão transferidos); verificar por E2E em `tests/e2e/test_admin_users.py`.
- [x] 4.4 Histórico com e-mail do autor: adicionar colunas de e-mail em `agent_runs`, `token_usage`, `checkpoints`, `gate_decisions`, `guidelines` e `management_audit`, fazer backfill a partir de `users` e tornar nuláveis as FKs obrigatórias de usuário (migration + modelos). Verificar com `alembic upgrade head --sql` e unit test de backfill.
- [x] 4.5 Escrita/leitura do histórico pelo e-mail armazenado: gravar o e-mail ao criar execuções, uso de tokens, checkpoints, decisões do gate, auditoria de gestão e guidelines; ler sem `join` com `users` (gate, auditoria de gestão, painel de uso). Verificar com unit tests e com os testes de gate/histórico existentes.

## 5. Grupos: renomear, excluir, remover membro e desvincular

- [x] 5.1 Implementar `directory.rename_group`, `delete_group` (remove `system_groups` e `group_members`), `remove_member` e `unlink_group_from_system`, todos com auditoria (`group.*`). Verificar com unit tests de cada operação.
- [x] 5.2 No card do grupo em `/admin`, adicionar ações: renomear, remover membro, desvincular sistema e **Excluir** com confirmação; verificar por E2E em `tests/e2e/test_admin_users.py`.

## 6. Checkpoints: excluir

- [x] 6.1 Implementar `checkpoints.delete_checkpoint(system, checkpoint_id)` com auditoria `checkpoint.delete`. Verificar com unit test.
- [x] 6.2 Na timeline de Checkpoints, adicionar **Excluir** por checkpoint com confirmação; verificar por E2E (o checkpoint some da timeline).

## 7. Chaves de LLM (admin)

- [x] 7.1 Implementar serviço de chaves sobre `ProviderKey`: cadastrar/trocar (cifrado, ADR 0007), remover e testar (chamada mínima sem gravar); registrar auditoria `provider_key.*` sem o valor da chave. Verificar com unit tests (incluindo teste com a chamada ao provedor simulada).
- [x] 7.2 Criar a área "Provedores de LLM" em `/admin`: lista por provedor com estado (configurada/não) e ações cadastrar/trocar, remover e **Testar**; verificar por E2E em `tests/e2e/test_llm_keys.py`.

## 8. Superfícies de auditoria na UI

- [x] 8.1 Adicionar a aba "Auditoria de gestão" em `/admin` com filtros por autor, recurso e ação; verificar por E2E (a ação de um grupo/usuário recém-excluído aparece na trilha).
- [x] 8.2 Na aba Auditoria da página do sistema, exibir as ações de gestão daquele sistema junto do histórico do gate (sem alterar o gate); verificar por E2E em `tests/e2e/test_gate.py`.

## 9. Verificação de integração

- [x] 9.1 Rodar `cd portal && uv run pytest tests/unit tests/bdd` — devem passar sem regressões.
- [x] 9.2 Subir o stack E2E dedicado (`docker compose -f deploy/docker-compose.e2e.yml up -d --build`) e rodar `uv run pytest tests/e2e` — suíte completa verde.

## Workflow follow-up

- Arquivar esta change depois que as tasks acima estiverem concluídas e revisadas.