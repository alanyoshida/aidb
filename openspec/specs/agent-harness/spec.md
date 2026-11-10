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
O portal SHALL transmitir em tempo real, durante a execução do agente, os eventos do seu trabalho, exibindo-os conforme a visibilidade definida para cada tipo de evento.

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
O portal SHALL manter o mesmo identificador de sessão do harness em uso ao longo de múltiplos pedidos dentro da mesma sessão de conversa, de forma que o agente retenha o contexto das mensagens anteriores, qualquer que seja o harness do perfil do sistema.

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

### Requirement: Detalhe técnico da execução atrás do modo debug
O chat SHALL tratar os comandos executados e os arquivos alterados como detalhe técnico, exibindo-os somente quando o editor liga o modo debug, de modo que a leitura da conversa com o agente não seja dominada por eles.

#### Scenario: Detalhe oculto por padrão
- **WHEN** o editor acompanha uma execução com o modo debug desligado
- **THEN** o chat não exibe os comandos executados nem os arquivos alterados, mantendo visíveis as mensagens do agente e os marcadores de transição da execução

#### Scenario: Detalhe visível com debug ligado
- **WHEN** o editor liga o modo debug
- **THEN** o chat passa a exibir os comandos executados e os arquivos alterados daquela execução

#### Scenario: Alternar o filtro não perde histórico
- **WHEN** o editor liga e desliga o modo debug durante ou após uma execução
- **THEN** o conteúdo já recebido continua disponível, sem que o chat precise recarregar ou refazer a execução
