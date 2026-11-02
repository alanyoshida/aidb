# agent-harness Specification

## Purpose

Define a conversa entre editores e o agente de código de cada sistema: chat com streaming, fila de execução, padrão de geração (guidelines), checkpoints git e visibilidade de uso de tokens.

## Requirements

### Requirement: Chat com o agente do sistema
O portal SHALL permitir que editores com acesso a um sistema enviem pedidos em linguagem natural ao agente do sistema e recebam o resultado do trabalho realizado.

#### Scenario: Pedido de geração de admin
- **WHEN** um editor pede "crie um painel administrativo da tabela clientes"
- **THEN** o agente trabalha sobre as conexões do sistema e responde com o resultado, incluindo os arquivos criados ou alterados

#### Scenario: app_user não conversa com o agente
- **WHEN** um `app_user` tenta usar o chat de geração de um sistema
- **THEN** o portal recusa o acesso

### Requirement: Streaming do trabalho em tempo real
O portal SHALL exibir em tempo real, durante a execução do agente, os eventos do seu trabalho, como arquivos editados e comandos executados.

#### Scenario: Acompanhamento ao vivo
- **WHEN** o agente está executando um pedido
- **THEN** o editor vê os eventos chegando progressivamente no chat até a conclusão

### Requirement: Interrupção de execução
O portal SHALL permitir que o editor interrompa o agente durante uma execução, cessando o trabalho em andamento.

#### Scenario: Editor interrompe
- **WHEN** o editor aciona a interrupção durante uma execução
- **THEN** o agente para o trabalho e o chat registra a execução como interrompida

### Requirement: Fila de um agente por sistema
O portal SHALL executar no máximo uma sessão de agente por sistema por vez, enfileirando novos pedidos de outros editores e exibindo a execução em andamento a quem espera.

#### Scenario: Segundo editor espera
- **WHEN** um editor envia um pedido enquanto outro executa no mesmo sistema
- **THEN** o pedido entra em fila e avisa quando a execução anterior terminar

#### Scenario: Fila ordem de chegada
- **WHEN** múltiplos pedidos estão enfileirados
- **THEN** executam na ordem em que foram enviados

### Requirement: Padrão de geração da plataforma
O agente SHALL gerar sistemas como uma única app Python por sistema, com frontend e backend em NiceGUI, interface em português do Brasil, conforme as guidelines da plataforma.

#### Scenario: App gerada segue o padrão
- **WHEN** o agente conclui um pedido de criação do sistema
- **THEN** o resultado é uma app NiceGUI única, em PT-BR, dentro do workspace do sistema

### Requirement: Guidelines editáveis pelo admin
O portal SHALL manter um documento de guidelines de geração, editável por administradores, aplicado a todos os agentes de sistema a partir das próximas execuções após alteração.

#### Scenario: Atualização de guideline propaga
- **WHEN** um admin altera as guidelines
- **THEN** as execuções seguintes em todos os sistemas passam a usar a versão atualizada

### Requirement: Checkpoints git por execução
O portal SHALL criar um checkpoint git do workspace ao final de cada execução bem-sucedida, registrar seu histórico por sistema e permitir rollback para checkpoint anterior.

#### Scenario: Checkpoint criado
- **WHEN** uma execução do agente termina com sucesso
- **THEN** um checkpoint com descrição da alteração aparece no histórico do sistema

#### Scenario: Rollback para checkpoint
- **WHEN** o dono restaura um checkpoint anterior
- **THEN** o workspace volta ao estado daquele checkpoint e a app é reiniciada nesse estado

### Requirement: Visibilidade de uso de tokens
O portal SHALL registrar o consumo de tokens de cada execução por sistema e usuário, e exibi-lo em painéis de consulta.

#### Scenario: Consumo visível
- **WHEN** um admin ou dono consulta o painel de uso de um sistema
- **THEN** vê o consumo de tokens acumulado por execução, usuário e período
