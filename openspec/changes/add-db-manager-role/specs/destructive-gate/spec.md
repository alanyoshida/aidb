# Spec Delta

## MODIFIED Requirements

### Requirement: Gate do agente sobre SQL destrutivo
O portal SHALL interceptar toda conexão a um banco cadastrado no data plane (proxy de wire protocol no caminho da conexão), classificar cada statement com o classificador canônico e responder automaticamente: `bloqueada` e `confirmável` SHALL ser recusadas sem intervenção humana, na hora, sem segurar a conexão; `normal` SHALL ser liberada sem atrito — independente de como a SQL foi emitida e do protocolo de permissão do agente. A única exceção é a conexão ativa em modo `schema_admin` no sistema: nela, statements `bloqueada` e `confirmável` emitidas pelo agente SHALL ser executadas; as emitidas pela app gerada SHALL continuar recusadas.

#### Scenario: Agente pede TRUNCATE e é recusado automaticamente
- **WHEN** uma conexão do container do sistema, ativa em modo `read_only` ou `read_write`, emite `TRUNCATE TABLE clientes`, por qualquer cliente (bash, MCP, script ou app)
- **THEN** o proxy recusa a statement, o cliente recebe um erro de protocolo e a operação não executa

#### Scenario: Agente pede DELETE em massa e o editor decide
- **WHEN** o agente executa `DELETE FROM clientes WHERE cidade = 'São Paulo'` (sem escopo de linha) por qualquer caminho de conexão, numa conexão que não está em modo `schema_admin`
- **THEN** o proxy recusa a statement na hora (mesmo tratamento de uma DDL), o cliente recebe um erro de protocolo, a operação não executa, e o chat mostra a recusa com a statement e o motivo — ninguém decide por ela (revisão ADR 0023: nenhum editor aprova ou recusa mais este caso)

#### Scenario: SQL escondido em arquivo não contorna o gate
- **WHEN** o agente grava um arquivo `.sql` com uma statement destrutiva e a executa com `psql -f arquivo.sql`
- **THEN** o proxy classifica e aplica a decisão do gate da mesma forma que classificaria a statement digitada diretamente

#### Scenario: Agente reestrutura tabelas em schema_admin
- **WHEN** o agente executa `DROP TABLE clientes_antiga` e `ALTER TABLE clientes ADD COLUMN cpf text` numa conexão ativa em modo `schema_admin`
- **THEN** as duas statements executam no banco

#### Scenario: DELETE em massa em schema_admin
- **WHEN** o agente executa `DELETE FROM clientes` numa conexão ativa em modo `schema_admin`
- **THEN** a statement executa no banco

#### Scenario: App continua sem DDL em schema_admin
- **WHEN** a app gerada emite `DROP TABLE clientes` numa conexão ativa em modo `schema_admin`
- **THEN** a statement é recusada, como em qualquer outro modo

#### Scenario: Rebaixamento volta a recusar
- **WHEN** a conexão deixa o modo `schema_admin` e o agente emite `DROP TABLE clientes`
- **THEN** a statement é recusada

### Requirement: Auditoria das decisões do gate
O portal SHALL registrar toda decisão do gate — aprovada, recusada pelo editor, bloqueada automaticamente ou liberada por a conexão estar em modo `schema_admin` — com autor (quando houver), SQL, conexão, classificação e timestamp, e SHALL exibir esse histórico na página do sistema para editores e admins.

#### Scenario: Histórico visível na página do sistema
- **WHEN** um editor abre a página do sistema após uma aprovação e um bloqueio
- **THEN** o histórico do gate lista ambos os eventos com SQL, decisão, autor e data

#### Scenario: DDL liberada fica no histórico
- **WHEN** o agente executa `DROP TABLE clientes_antiga` numa conexão ativa em modo `schema_admin`
- **THEN** o histórico do gate lista a statement com a classificação `bloqueada` e a indicação de que foi liberada pelo modo `schema_admin`
