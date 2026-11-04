# Spec Delta

## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Streaming do trabalho em tempo real
O portal SHALL transmitir em tempo real, durante a execução do agente, os eventos do seu trabalho, exibindo-os conforme a visibilidade definida para cada tipo de evento.

#### Scenario: Acompanhamento ao vivo
- **WHEN** o agente está executando um pedido
- **THEN** o editor vê os eventos chegando progressivamente no chat até a conclusão
