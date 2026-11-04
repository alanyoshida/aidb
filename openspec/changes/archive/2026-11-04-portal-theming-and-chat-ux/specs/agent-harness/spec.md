# Spec Delta

## ADDED Requirements

### Requirement: Horário de envio visível por mensagem
O chat SHALL exibir a data e a hora de cada mensagem ao lado do nome de quem a enviou, fora da bolha, convertendo o instante registrado para o fuso de exibição configurado no portal.

#### Scenario: Horário na mensagem do editor
- **WHEN** o editor envia um pedido ao agente
- **THEN** a mensagem exibe data e hora do envio ao lado do nome do remetente

#### Scenario: Horário na resposta do agente
- **WHEN** o agente emite uma mensagem durante a execução
- **THEN** a mensagem exibe data e hora ao lado do nome do agente, antes mesmo de a execução terminar

#### Scenario: Histórico mostra horários originais
- **WHEN** o editor abre uma sessão anterior
- **THEN** cada mensagem do histórico exibe o horário em que foi enviada, não o momento da consulta

### Requirement: Disponibilidade do agente visível no chat
O chat SHALL exibir um indicador do estado do agente junto da descrição textual desse estado, distinguindo visualmente o agente disponível do agente ocupado, com movimento contínuo apenas enquanto houver trabalho em curso.

#### Scenario: Agente disponível
- **WHEN** não há execução em curso nem pedidos na fila do sistema
- **THEN** o chat exibe o indicador em estado de repouso, sem animação, junto da descrição de agente livre

#### Scenario: Agente ocupado
- **WHEN** há uma execução em curso, um pedido na fila ou uma aprovação pendente
- **THEN** o chat exibe o indicador em estado de trabalho, animado, junto da descrição do que está acontecendo

#### Scenario: Movimento respeita preferência de acessibilidade
- **WHEN** o usuário configurou o sistema para reduzir animações
- **THEN** o indicador distingue os estados sem movimento contínuo

### Requirement: Marcadores de execução exibidos em português
O chat SHALL exibir os marcadores de transição de execução em português, em vez do identificador interno do evento.

#### Scenario: Início e fim de execução
- **WHEN** uma execução do agente começa e termina
- **THEN** o chat exibe marcadores legíveis em português para cada transição, sem mostrar o identificador técnico do evento

### Requirement: Retorno da criação manual de checkpoint
O portal SHALL informar o resultado da criação manual de checkpoint, distinguindo o caso em que um checkpoint foi criado daquele em que não havia alteração a salvar.

#### Scenario: Checkpoint criado
- **WHEN** o dono solicita um checkpoint manual e há alterações no workspace
- **THEN** o portal confirma a criação identificando o checkpoint e o exibe no histórico

#### Scenario: Nada a salvar
- **WHEN** o dono solicita um checkpoint manual e o workspace não tem alteração desde o último checkpoint
- **THEN** o portal informa que não havia alteração a salvar, em vez de não dar retorno algum

### Requirement: Provedor e modelo declarados em cada execução
O portal SHALL informar ao harness o provedor e o modelo configurados no sistema a cada execução, em vez de permitir que o harness recorra ao padrão próprio.

#### Scenario: Execução usa o modelo do sistema
- **WHEN** o editor envia um pedido em um sistema com provedor e modelo configurados
- **THEN** a execução usa esse provedor e modelo, e a resposta do agente aparece no chat

#### Scenario: Padrão do harness não substitui a configuração
- **WHEN** o harness possui um modelo padrão próprio diferente do configurado no sistema
- **THEN** a execução ignora esse padrão e usa o modelo do sistema, sem terminar sem resposta
