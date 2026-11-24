# Spec Delta

## MODIFIED Requirements

### Requirement: Gate sobre toda statement do wire protocol
O proxy SHALL classificar cada statement que atravessa a conexão com o classificador canônico e repassar as `normal`. As `bloqueada` e `confirmável` SHALL ser recusadas na hora, com erro de protocolo ao cliente, sem tocar o banco e sem esperar decisão humana (ADR 0023), salvo quando chegam pelo listener de origem agente de uma conexão ativa em modo `schema_admin`, que SHALL repassá-las.

#### Scenario: DELETE em massa via arquivo é recusado direto, sem pedir decisão
- **WHEN** o agente grava um arquivo `.sql` contendo `DELETE FROM clientes` e executa `psql -f arquivo.sql` apontando para o DSN de loopback de uma conexão que não está em modo `schema_admin`
- **THEN** o proxy classifica a statement como confirmável e a recusa na hora — o cliente recebe erro de protocolo, o banco não é tocado e nenhuma decisão humana é solicitada

#### Scenario: DDL recusada por qualquer caminho
- **WHEN** uma statement `DROP TABLE` chega por qualquer cliente (MCP, psql, script Python, app gerada) de uma conexão que não está em modo `schema_admin`
- **THEN** o proxy recusa a statement com erro de protocolo e o banco não é tocado

#### Scenario: Listener do agente repassa DDL em schema_admin
- **WHEN** uma statement `DROP TABLE` chega pelo listener de origem agente de uma conexão ativa em modo `schema_admin`
- **THEN** o proxy repassa a statement ao banco e registra a decisão como liberada

#### Scenario: Listener da app recusa DDL em schema_admin
- **WHEN** uma statement `DROP TABLE` chega pelo listener de origem app de uma conexão ativa em modo `schema_admin`
- **THEN** o proxy recusa a statement com erro de protocolo e o banco não é tocado

#### Scenario: Modo ausente equivale a read_write
- **WHEN** o proxy recebe a configuração de uma conexão sem indicação de modo
- **THEN** trata a conexão como `read_write` e recusa statements `bloqueada` e `confirmável` nas duas origens
