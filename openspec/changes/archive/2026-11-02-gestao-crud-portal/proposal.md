# Proposal

## Why

A superfície de gestão do portal é, hoje, quase só de criação e leitura: editar e remover faltam ou não estão ligados à interface de forma desigual. Três operações já têm serviço, spec e teste, mas nenhum botão (`connections.remove_connection`, `systems.set_provider`, `directory.set_user_active`); outras não existem em nenhuma camada (renomear/excluir grupo, remover membro, desvincular; excluir usuário; editar conexão; excluir checkpoint). Além disso, não há confirmação nem trilha de auditoria para ações de gestão — diferente do gate de SQL, que audita tudo. Isso obriga o operador a ir ao banco para tarefas corriqueiras e deixa specs (`db-connections`, `portal-identity`) prometendo remoção/edição que a tela não entrega.

## What Changes

- **Conexões**: editar e remover na aba Conexões (dono ou admin). A edição tem senha opcional (vazia mantém a atual; preenchida testa e troca) e reusa o teste antes de salvar; a remoção reusa `remove_connection` e o refresh de provisionamento do container.
- **Sistema**: renomear (somente o nome de exibição — slug/URL `/apps/<slug>`, rota do Traefik e identidade ficam imutáveis); editar provedor/modelo com **select de modelos conhecidos** do provedor (reusa `set_provider`).
- **Usuários (admin)**: editar tipo, desativar/reativar (reusa `set_user_active`) e excluir. Ao excluir, a posse dos sistemas do usuário é **transferida para o admin executor** e os vínculos de grupo do usuário são removidos.
- **Grupos (admin)**: renomear, excluir, remover membro e desvincular sistema. Excluir remove só as linhas de vínculo (`system_groups`, `group_members`), sem apagar os dependentes.
- **Checkpoints (dono/admin)**: excluir um checkpoint, com confirmação.
- **Chave de LLM (admin)**: novo painel global por provedor — cadastrar/trocar chave, remover e **testar** (chamada mínima ao provedor, sem gravar).
- **Auditoria de gestão**: nova trilha que registra **toda ação de escrita** da gestão (autor, ação, recurso, alvo, sistema, detalhes e data), separada do gate de SQL. Visível numa aba global em `/admin` e na aba Auditoria de cada sistema, ao lado do histórico do gate.
- **Confirmação**: ações de exclusão pedem diálogo de confirmação.
- Remoções não bloqueiam por vínculo existente (comportamento escolhido: limpar apenas as linhas de vínculo).

## Capabilities

### New Capabilities

- `management-audit`: trilha de auditoria das ações de escrita da gestão do portal — o que foi feito, por quem, sobre qual recurso/sistema e quando — consultável globalmente e por sistema.
- `llm-provider-keys`: gestão das chaves de API dos provedores de LLM pelo admin — cadastro, troca, remoção e teste de chave, armazenada cifrada e global por provedor.

### Modified Capabilities

- `system-management`: acrescenta a renomeação do sistema (só o nome) e a transferência de posse dos sistemas de um usuário excluído; o comportamento de provedor por sistema (dono altera) permanece como está.
- `portal-identity`: acrescenta gestão de grupos (renomear, excluir, remover membro, desvincular sistema) e completa a administração de usuários com exclusão (com transferência de posse) além de editar tipo e desativar.

> Nota: `db-connections` já possui os requisitos "Remoção de conexão" e o cenário de edição sem revelar senha. Esta change os **realiza na interface**, sem alterar requisitos — por isso não entra como capability modificada.

## Impact

- **Código**: `portal/appaiforge/ui/admin.py`, `portal/appaiforge/ui/system_detail.py`, `portal/appaiforge/services/{directory,connections,systems}.py`, `portal/appaiforge/gate.py` (referência para a trilha), `portal/appaiforge/config.py` (modelos conhecidos por provedor), novo serviço de auditoria de gestão.
- **Dados**: nova tabela de auditoria de gestão → exigirá migration Alembic. Nenhuma alteração de coluna existente.
- **Sem mudança** no gate de SQL nem no contrato do agente/harness.
- **Testes**: unitários dos novos serviços; BDD para os fluxos de gestão; E2E (`tests/e2e/test_admin_users.py`, `test_systems.py` e um novo para conexões/usuários/grupos) — seletores `data-testid` novos para as ações.