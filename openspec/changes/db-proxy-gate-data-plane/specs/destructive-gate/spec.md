# Spec Delta

## MODIFIED Requirements

### Requirement: Gate do agente sobre SQL destrutivo
O portal SHALL interceptar toda conexão a um banco cadastrado no data plane (proxy de wire protocol no caminho da conexão), classificar cada statement com o classificador canônico e responder automaticamente: `bloqueada` SHALL ser recusada sem intervenção; `confirmável` SHALL aguardar decisão do editor; `normal` SHALL ser liberada sem atrito — independente de como a SQL foi emitida e do protocolo de permissão do agente.

#### Scenario: Agente pede TRUNCATE e é recusado automaticamente
- **WHEN** uma conexão do container do sistema emite `TRUNCATE TABLE clientes`, por qualquer cliente (bash, MCP, script ou app)
- **THEN** o proxy recusa a statement, o cliente recebe um erro de protocolo e a operação não executa

#### Scenario: Agente pede DELETE em massa e o editor decide
- **WHEN** o agente executa `DELETE FROM clientes WHERE cidade = 'São Paulo'` (sem escopo de linha) por qualquer caminho de conexão
- **THEN** o chat exibe o SQL e botões aprovar/recusar, a execução aguarda a decisão, e apenas após aprovação a statement é liberada

#### Scenario: SQL escondido em arquivo não contorna o gate
- **WHEN** o agente grava um arquivo `.sql` com uma statement destrutiva e a executa com `psql -f arquivo.sql`
- **THEN** o proxy classifica e aplica a decisão do gate da mesma forma que classificaria a statement digitada diretamente
