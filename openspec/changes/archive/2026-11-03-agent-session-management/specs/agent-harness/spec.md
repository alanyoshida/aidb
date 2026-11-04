# Spec Delta

## ADDED Requirements

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
