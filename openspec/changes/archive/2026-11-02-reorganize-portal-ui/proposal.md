# Proposal

## Why

A página do sistema (`portal/appaiforge/ui/system_detail.py`) empilha verticalmente, numa única `ui.page`, tudo que o editor precisa: status/ações, conexões de banco, chat de geração, checkpoints, gate de destrutivas e uso de tokens. Cada "seção" é só um `ui.label` em negrito seguido de um `ui.column`/`ui.card`, sem hierarquia real, e a página cresce indefinidamente conforme o histórico aumenta. O chat (`portal/appaiforge/ui/chat.py`) renderiza cada evento como `ui.label` cru prefixado por emoji, sem usar o componente de chat do próprio NiceGUI. O resultado, confirmado pelo usuário a partir de screenshots reais, é uma interface difícil de escanear e de navegar.

## What Changes

- `system_detail.py`: reorganizar as seções em `ui.tabs()`/`ui.tab_panels()` (padrão já usado em `admin.py`), com 4 abas: **Chat** (padrão), **Conexões**, **Checkpoints**, **Auditoria** (une as atuais seções "Gate de destrutivas" e "Uso de tokens" — ambas são histórico read-only de uso pouco frequente). O cabeçalho (nome, slug, badge de status, provedor/modelo, botões Abrir app/Arquivar/Excluir) permanece fixo acima das abas.
- `chat.py`: substituir o log construído com `ui.label` por `ui.chat_message` dentro de um `ui.scroll_area` de altura fixa — mensagens do usuário com `sent=True`, eventos do agente com `sent=False`, diferenciando por `name`/ícone conforme o tipo de evento (`message`, `file_edited`, `command_run`, `gate_request`/`gate_denied`/`gate_approved`/`gate_resolved`, `run_started`/`run_finished`/`run_interrupted`/`run_error`). Isso vale tanto para o log da execução corrente (em memória) quanto para os eventos persistidos de execuções anteriores (`run_events`, já carregados do banco). Remover os prefixos de emoji cru; usar `ui.icon`/`ui.button(icon=...)`.
- `system_detail.py` (Checkpoints): trocar a lista plana por `ui.timeline()`, cada item com SHA, mensagem e botão "Restaurar" com ícone.
- `systems.py` (lista de sistemas): ícone no botão "Novo sistema" e indicador visual por card, para consistência com o resto do portal.
- `admin.py`: adicionar ícones às abas já existentes (Usuários/Grupos) e aos botões de ação (criar usuário, criar grupo, adicionar membro, vincular sistema).
- `admin.py`/`system_detail.py`: padronizar a ordem — botões de ação sempre **acima** das listas/tabelas (o botão "Novo usuário" ficava abaixo da tabela; os botões de Grupos ficavam abaixo da lista).
- `admin.py`: rótulos sem ambiguidade — "Adicionar membro" → "Adicionar membro a um grupo" (título e botão); confirmar "Adicionar ao grupo"; "Vincular" → "Vincular ao sistema". Empty state "Nenhum grupo ainda." quando não há grupos.
- `system_create.py`: dar largura cheia ao select "Provedor de LLM" (estava truncado para "Pr...") e ícone no botão "Criar sistema".
- `guidelines_admin.py`: ícone no botão "Salvar".
- `system_detail.py` (Uso de tokens): agrupar as linhas por execução com barra de peso relativo ao total, em vez da lista crua linha-a-linha.
- Correção de regressão: a tabela de usuários havia ficado sem criação (`table` indefinido) na reorganização anterior — restaurada acima do botão, com Ativo em "Sim/Não".
- Nenhuma mudança de comportamento, dado, API ou regra de negócio — apenas reorganização visual e troca de componentes NiceGUI por equivalentes mais apropriados ao conteúdo (abas, chat, timeline, ícones).

## Capabilities

### New Capabilities

(nenhuma)

### Modified Capabilities

(nenhuma — ver nota abaixo)

Esta é uma mudança puramente de apresentação: as specs existentes (`agent-harness`, `destructive-gate`, `db-connections`, `portal-identity`) descrevem comportamento observável ("o editor vê os eventos chegando progressivamente no chat", "um checkpoint... aparece no histórico do sistema", "o portal... SHALL exibir esse histórico na página do sistema") sem prescrever layout, widget específico ou estilo visual. Reorganizar em abas, usar `ui.chat_message`/`ui.timeline` e adicionar ícones não altera a veracidade de nenhum desses requisitos — os eventos continuam chegando progressivamente no chat, o checkpoint continua aparecendo no histórico do sistema (agora numa aba dedicada da mesma página), o histórico do gate continua visível na página do sistema (agora na aba Auditoria). Por isso esta change declara `skip_specs: true` em `.openspec.yaml` em vez de inventar uma capability `portal-ui` sem requisito de comportamento real para sustentá-la.

## Impact

- **Código afetado**: `portal/appaiforge/ui/system_detail.py`, `portal/appaiforge/ui/chat.py`, `portal/appaiforge/ui/systems.py`, `portal/appaiforge/ui/admin.py`, `portal/appaiforge/ui/system_create.py`, `portal/appaiforge/ui/guidelines_admin.py`, `portal/appaiforge/gate.py`.
- **Testes**: os testes E2E (`portal/tests/e2e/test_chat.py`, `test_systems.py`, `test_admin_users.py`, `test_gate.py`) usam seletores `data-testid` e texto visível — os `data-testid` existentes (`chat-input`, `chat-send`, `chat-interrupt`, `gate-approve`, `gate-deny`, `archive-system`, `delete-system`, etc.) devem ser preservados nos elementos reorganizados; testes que dependem de uma seção estar sempre visível na mesma página (sem precisar clicar numa aba) podem precisar de um clique de navegação adicional.
- **Sem mudança** em modelos de dados, migrations, specs, harness, gate, ou qualquer contrato externo.
- **Dependências**: nenhuma nova — NiceGUI 3.18 (já instalado) já inclui `ui.tabs`, `ui.tab_panels`, `ui.chat_message`, `ui.scroll_area`, `ui.timeline`, `ui.icon` e o parâmetro `icon=` de `ui.button`.
