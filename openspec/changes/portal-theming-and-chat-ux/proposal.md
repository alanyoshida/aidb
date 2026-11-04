# Proposal

## Why

O portal não tinha controle de aparência: as cores vinham dos padrões do NiceGUI e do Quasar, e vários textos ficavam ilegíveis — texto escuro sobre bolha escura no chat, vermelho escuro sobre fundo escuro em avisos de erro, branco sobre ciano em notificações. Ao mesmo tempo, o chat não dizia quando cada mensagem foi enviada nem se o agente estava disponível, e três comportamentos falhavam em silêncio: o agente não respondia, o botão de checkpoint não dava retorno, e o teste de conexão escondia o motivo do erro.

## What Changes

- Novo sistema de tema do portal com 3 modos (claro, escuro, pastel) e 4 cores de destaque, totalizando 12 combinações, selecionáveis pela barra superior
- Preferência de tema passa a ser gravada por usuário e aplicada em todas as páginas autenticadas, sem flash de cor errada na carga
- Todas as combinações de texto e fundo passam a garantir contraste mínimo WCAG AA
- Chat passa a exibir data e hora ao lado do nome de quem enviou, convertidas para o fuso de exibição configurado
- Chat passa a exibir um indicador de disponibilidade do agente: parado quando livre, animado quando há trabalho em curso
- Marcadores de transição de execução no chat passam a ser exibidos em português, em vez do identificador interno do evento
- Criação manual de checkpoint passa a informar o resultado, inclusive quando não há alteração a salvar
- Falha no teste de conexão passa a informar o motivo relatado pelo driver, com a senha removida do texto
- Execução do agente passa a declarar explicitamente o provedor e o modelo do sistema ao harness, em vez de depender do padrão dele

## Capabilities

### New Capabilities
- `portal-theming`: aparência do portal — modos e cores de destaque, preferência por usuário e garantias de legibilidade

### Modified Capabilities
- `agent-harness`: chat ganha horário por mensagem, indicador de disponibilidade do agente e rótulos em português; checkpoint manual passa a dar retorno; execução passa a fixar provedor e modelo
- `db-connections`: falha no teste de conexão passa a informar o motivo, sem expor a senha

## Impact

- `portal/appaiforge/ui/theme.py`: tokens de cor, folhas de estilo do portal e do chat
- `portal/appaiforge/ui/common.py`: cabeçalho com seletor de tema, paleta do Quasar e notificações
- `portal/appaiforge/ui/chat.py`: horário por mensagem, indicador de disponibilidade, rótulos de status
- `portal/appaiforge/ui/system_detail.py`: retorno do checkpoint manual
- `portal/appaiforge/services/connections.py`: mensagem de falha do teste de conexão
- `portal/appaiforge/harness/opencode.py`: provedor e modelo no envio do prompt
- `portal/appaiforge/models.py` e `portal/migrations/`: campo de preferência de tema no usuário
- `portal/appaiforge/config.py`: fuso de exibição dos horários
