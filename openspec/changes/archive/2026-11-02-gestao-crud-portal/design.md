# Design

## Context

Ver `proposal.md` — Why. Estado atual que molda a solução:

- A UI do portal já usa o padrão de **diálogos** para criação (`admin.py`) e **abas** na página do sistema (`system_detail.py`), consolidado na change `reorganize-portal-ui` (já arquivada). As novas ações de edição/remoção seguem o mesmo padrão.
- Vários mutadores já existem no serviço e são testados, mas sem chamador na UI: `connections.remove_connection`, `systems.set_provider`, `directory.set_user_active`. A change os **liga**, em vez de recriar.
- O gate de SQL tem trilha própria (`gate_decisions`, `gate.list_decisions`) e mostra autor por e-mail. A trilha de gestão é **separada** (ver proposal) — não reusa nem sobrecarrega `gate_decisions`.
- Segredos já são cifrados com `security.encrypt_secret` (ADR 0007); a chave de LLM segue o mesmo caminho (`ProviderKey.key_encrypted`).
- Permissão já tem guardas em `rbac.py` (`can_manage_system`, `can_create_systems`, `can_chat`); admin tem acesso total.

## Goals / Non-Goals

**Goals:**
- Completar o ciclo de vida (editar/remover) dos recursos de gestão na UI, reaproveitando serviços existentes.
- Registrar **toda ação de escrita de gestão** numa trilha consultável global e por sistema.
- Manter segredos (senha de conexão, chave de LLM) cifrados e nunca devolvidos à interface.

**Non-Goals:**
- Não altera o gate de SQL nem o harness/agente.
- Não muda o esquema de `token_usage`, checkpoints ou containers além do refresh já existente de conexões.
- Não introduz slug editável, nem exclusão em cascata de dependentes.
- Não implementa autenticação externa nem permissões por grupo além do que já existe.

## Decisions

### 1. Ligar serviços existentes antes de criar novos

Conexão (remover), provedor do sistema e ativação de usuário já têm serviço e teste. A UI chama esses serviços. Só criamos serviço novo onde não existe: renomear/excluir grupo, remover membro, desvincular, excluir usuário (com transferência), editar conexão, excluir checkpoint, editar tipo de usuário, e a própria auditoria.

*Alternativa considerada:* reescrever os mutadores junto com a UI — rejeitada por descartar teste e lógica já validados.

### 2. Trilha de auditoria de gestão como tabela própria

Nova tabela `management_audit`:

```
management_audit
  id             str (pk)
  actor_id       FK users.id           -- quem executou
  action         str                   -- ex.: "user.delete", "conn.update", "group.rename"
  resource_type  str                   -- user | group | system | connection | checkpoint | provider_key
  resource_id    str | null            -- id do alvo
  system_id      FK systems.id | null  -- preenchido p/ ações ligadas a um sistema
  details        JSON                  -- contexto livre (nome antigo/novo, provedor, etc.) SEM segredos
  created_at     datetime
```

Um serviço `audit.record(...)` centraliza a escrita; cada mutador de gestão chama-o após a operação. Leitura: `audit.list_global()` (admin) e `audit.list_by_system(system_id)` — este último alimenta a aba Auditoria existente ao lado do histórico do gate.

*Alternativas consideradas:* (a) reusar `gate_decisions` — rejeitada: o gate é específico de SQL destrutivo e tem semântica própria; (b) log em arquivo — rejeitada: não filtrável/consultável na UI; (c) event sourcing — desproporcional.

### 3. Remoção limpa vínculos, não cascateia nem apaga dependentes

- Excluir grupo → remove `system_groups` e `group_members` do grupo.
- Excluir usuário → remove `group_members` do usuário e **transfere** `systems.owner_id` dos sistemas dele para o admin executor.
- Excluir conexão → já é o comportamento de `remove_connection` (hard delete) + `_refresh_provisioning`.

*Alternativa considerada:* bloquear quando há vínculo — recusada pelo usuário (proposta: não bloquear). Cascata total — recusada: apagaria sistemas/registros do cliente sem intenção.

### 3b. Histórico guarda o e-mail do usuário (denormalizado)

Decisão do usuário na implementação: o histórico (execuções, uso de tokens, checkpoints, decisões do gate, auditoria de gestão e guidelines) deve preservar o autor **mesmo depois que o usuário for excluído**. Por isso essas tabelas passam a guardar o e-mail do usuário (coluna própria) e a FK para `users` vira nulável (era obrigatória em `agent_runs`, `token_usage`, `checkpoints`, `guidelines`).

- Escrita: cada criação de item de histórico grava também o e-mail do autor (quando conhecido).
- Leitura: passa a usar o e-mail armazenado, sem `join` com `users` (gate, auditoria de gestão e painel de uso).
- Exclusão de usuário: a FK é anulada (`SET NULL` lógico) e o e-mail permanece — nada de histórico é apagado. Sessões e `chat_sessions` (operacionais) e `group_members` são removidos; `systems.owner_id` é transferido ao admin executor.

*Alternativa considerada:* tornar o histórico órfão só anulando a FK, sem guardar e-mail — recusada: perderia a atribuição de quem fez o quê, que é justamente o valor da trilha.

### 4. Permissões verificadas na UI e no serviço

As ações de dono usam `can_manage_system`; as globais (usuários, grupos, chaves, auditoria global) usam `user.is_admin`. A checagem também ocorre no serviço (não só escondendo o botão), seguindo o padrão de `create_system` que levanta `NotPermitted`.

### 5. Chave de LLM global, cifrada, com teste sob demanda

Reusa `ProviderKey` (uma chave por provedor). UI em `/admin` (nova área "Provedores de LLM"): cadastrar/trocar, remover, e **Testar** — chamada mínima ao provedor que **não grava** nada, só reporta ok/erro (mesma ideia do troubleshooting do README). Nunca exibe a chave de volta, só se está configurada.

### 6. Modelos conhecidos por provedor no config

`config.py` passa a expor um mapa `provider -> [modelos]` (ex.: `glm -> [glm-4.6, ...]`), com o padrão atual como primeiro item. A UI de editar provedor usa esse mapa num select; o valor ainda é gravado em `System.provider`/`System.model`.

### 7. Edição de conexão com senha opcional

Formulário de edição pré-preenche metadados (host/porta/banco/usuário) e deixa a senha em branco; vazia mantém a atual, preenchida dispara `test_connection` e troca. Salvar reusa `test_connection` e `_refresh_provisioning`, como o cadastro.

### 8. Confirmação de exclusão via diálogo

Reusa `ui.dialog` (padrão atual). Exclusões (usuário, grupo, conexão, checkpoint, sistema) confirmam com o nome do alvo; desvincular/remover membro não pede confirmação.

## Risks / Trade-offs

- **[Risco]** Exclusão de conexão em uso pode deixar a app gerada sem credencial até o refresh. → **Mitigação**: `remove_connection` já dispara `_refresh_provisioning`; a UI avisa na confirmação que a conexão deixa de existir para o agente e a app.
- **[Risco]** Transferir posse para o admin executor muda silenciosamente a visibilidade dos sistemas. → **Mitigação**: registrar na trilha (`user.delete` com `details.transferred_system_ids`) e informar na confirmação quantos sistemas serão transferidos.
- **[Risco]** Trilha sem retenção cresce indefinidamente. → **Mitigação**: leitura paginada/limitada na UI; retenção fica como open question.
- **[Risco]** Desvincular grupo/remover membro revoga acesso de um `app_user` que já tem token HMAC válido na app gerada. → **Mitigação**: a visibilidade no portal é imediata; o token existente expira no seu TTL (comportamento atual do app-serving) — documentar no design, não estender o TTL aqui.
- **[Risco]** `details` JSON pode vir a conter segredo por descuido. → **Mitigação**: contrato do serviço `audit.record` proíbe campos de segredo; nunca passar senha/chave.

## Migration Plan

- Duas migrations Alembic: (1) cria `management_audit`; (2) adiciona as colunas de e-mail do autor ao histórico (`agent_runs.user_email`, `token_usage.user_email`, `checkpoints.author_email`, `gate_decisions.author_email`, `guidelines.updated_by_email`, `management_audit.actor_email`), faz o backfill a partir de `users` e torna nuláveis as FKs obrigatórias (`agent_runs.user_id`, `token_usage.user_id`, `checkpoints.author_id`, `guidelines.updated_by_id`). Sem perda de dados.
- Deploy é rebuild normal do container `portal`; a trilha de gestão começa a partir do deploy.
- Rollback: reverter o commit e as migrations (drop dos artefatos adicionados); dados de domínio intactos.

## Open Questions

- Retenção/expurgo da trilha de auditoria de gestão (manter indefinidamente ou janela de N dias) — decidível depois, não muda specs nem tasks.