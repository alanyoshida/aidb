# Spec Delta

## ADDED Requirements

### Requirement: Guidelines incluem instruções de uso do OpenSpec
As guidelines padrão da plataforma SHALL incluir instruções que ensinam o agente a usar os comandos `/opsx-*` do OpenSpec — quando o editor pedir para planejar, propor, explorar, implementar ou arquivar uma mudança — e a manter os artefatos em `openspec/` do workspace.

#### Scenario: Agente segue o fluxo OpenSpec quando pedido
- **WHEN** o editor pede ao agente "planeje essa mudança antes de implementar"
- **THEN** o agente usa o fluxo `/opsx-propose` e registra a change em `openspec/changes/`

#### Scenario: Pedido simples não exige OpenSpec
- **WHEN** o editor faz um ajuste pontual sem pedir planejamento
- **THEN** o agente pode implementar diretamente, sem criar uma change

### Requirement: Autocomplete de comandos no chat
O chat SHALL sugerir, quando o editor digitar `/` no início da mensagem, os comandos disponíveis no agente daquele sistema, com nome e descrição, filtrando conforme o texto digitado e permitindo escolher por teclado ou mouse. A lista SHALL vir do ambiente do agente do sistema, e a indisponibilidade dela SHALL NOT impedir o envio de mensagens.

#### Scenario: Sugestões ao digitar barra
- **WHEN** o editor digita `/` no campo do chat de um sistema com OpenSpec configurado
- **THEN** o chat lista os comandos do agente, incluindo `/opsx-propose`, `/opsx-explore`, `/opsx-apply` e `/opsx-archive`, cada um com sua descrição

#### Scenario: Filtro pelo texto digitado
- **WHEN** o editor digita `/opsx-ap`
- **THEN** as sugestões se restringem aos comandos que começam com esse texto, como `/opsx-apply`

#### Scenario: Escolha pelo teclado
- **WHEN** o editor navega pelas sugestões com as setas e confirma com Enter ou Tab
- **THEN** o campo passa a conter o comando escolhido seguido de espaço, pronto para os argumentos, sem enviar a mensagem

#### Scenario: Comando inexistente no agente
- **WHEN** um comando não existe no ambiente do agente daquele sistema
- **THEN** ele não aparece nas sugestões

#### Scenario: Lista indisponível
- **WHEN** o agente do sistema não responde à listagem de comandos
- **THEN** o chat não mostra sugestões e o editor continua podendo digitar e enviar mensagens normalmente

#### Scenario: Texto que não é comando
- **WHEN** a mensagem não começa com `/`
- **THEN** nenhuma sugestão é exibida

