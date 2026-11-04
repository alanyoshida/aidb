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

### Requirement: Sessões de conversa nomeadas e múltiplas
O portal SHALL permitir que cada editor mantenha múltiplas sessões de conversa nomeadas por sistema, criadas automaticamente na primeira mensagem e renomeáveis pelo editor a qualquer momento.

#### Scenario: Primeira mensagem cria sessão automaticamente
- **WHEN** um editor envia o primeiro pedido sem ter uma sessão ativa
- **THEN** o portal cria uma nova sessão com título derivado das primeiras palavras do prompt e a usa para essa execução

#### Scenario: Editor cria nova sessão explicitamente
- **WHEN** o editor aciona "Nova sessão" na interface
- **THEN** uma sessão nova e vazia é criada e se torna a sessão ativa

#### Scenario: Editor renomeia sessão
- **WHEN** o editor edita o título de uma sessão na interface
- **THEN** o novo título é salvo e exibido na lista de sessões

#### Scenario: Editor troca de sessão
- **WHEN** o editor seleciona uma sessão diferente na lista
- **THEN** o histórico daquela sessão é carregado e os próximos pedidos são enviados nela

### Requirement: Continuidade de contexto do agente dentro da sessão
O portal SHALL manter o mesmo identificador de sessão do harness (opencode) ao longo de múltiplos pedidos dentro da mesma sessão de conversa, de forma que o agente retenha o contexto das mensagens anteriores.

#### Scenario: Agente lembra pedido anterior na mesma sessão
- **WHEN** o editor envia um segundo pedido na mesma sessão de conversa
- **THEN** o agente processa o novo pedido com contexto das mensagens anteriores dessa sessão, sem que o editor precise repeti-las

#### Scenario: Sessões diferentes têm contextos isolados
- **WHEN** o editor alterna entre duas sessões de conversa do mesmo sistema
- **THEN** cada sessão mantém seu próprio contexto de agente, sem interferência entre elas

### Requirement: Aviso explícito de reinício de contexto
O portal SHALL notificar o editor na linha do tempo do chat quando o contexto do agente for reiniciado, indicando que o agente não lembra as mensagens anteriores da sessão.

#### Scenario: Contexto reiniciado por recriação do container
- **WHEN** o container do sistema é recriado (por reprovisioning ou reconciliação) e o editor envia o próximo pedido na sessão
- **THEN** o chat exibe um aviso "Contexto do agente reiniciado" antes de processar o pedido, e o agente inicia sem memória das mensagens anteriores

#### Scenario: Contexto reiniciado por sessão morta
- **WHEN** a sessão do harness se torna inválida por crash do container e o editor envia um pedido
- **THEN** o portal detecta o erro, exibe o aviso de reinício e cria uma nova sessão do harness para processar o pedido

### Requirement: Guidelines incluem instruções de formatação de artifacts visuais
As guidelines globais da plataforma SHALL incluir instruções que ensinam o agente a usar blocos especiais (```echart```, ```table```, ```html```) quando o editor solicitar visualizações, gráficos ou tabelas, de modo que o chat possa renderizá-los visualmente.

#### Scenario: Agente usa bloco echart ao ser pedido gráfico
- **WHEN** o editor pede ao agente "mostre um gráfico de vendas por mês"
- **THEN** o agente retorna uma resposta com um bloco ```echart``` contendo JSON de configuração válido para Apache ECharts

#### Scenario: Agente usa bloco table ao ser pedido tabela
- **WHEN** o editor pede ao agente "liste os clientes em uma tabela"
- **THEN** o agente retorna uma resposta com um bloco ```table``` contendo JSON array dos dados

#### Scenario: Agente usa texto simples quando não há dados visuais
- **WHEN** o editor faz um pedido que não envolve visualização de dados
- **THEN** o agente responde normalmente em texto, sem usar blocos de artifact desnecessariamente
