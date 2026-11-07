# Spec Delta

## Purpose

Move o gate de operações destrutivas para o data plane: um proxy por sistema intercepta toda conexão a banco cadastrado no wire protocol, guarda as credenciais reais fora do container do agente e aplica a classificação canônica independente de como a SQL foi emitida.

## ADDED Requirements

### Requirement: Credenciais de banco fora do container do sistema
O provisionamento SHALL entregar as credenciais reais das conexões apenas ao sidecar de gate de banco do sistema, e o container do sistema SHALL receber somente DSNs sem usuário nem senha apontando para portas do proxy em loopback — na variável de ambiente da app gerada e nos argumentos das ferramentas MCP.

#### Scenario: Ambiente do container não contém credencial de banco
- **WHEN** o ambiente de um container de sistema com conexões cadastradas é inspecionado
- **THEN** as variáveis `DATABASE_URL_*` e a linha de comando do MCP server contêm somente DSNs de loopback sem usuário nem senha

#### Scenario: Credencial não aparece na linha de comando do MCP
- **WHEN** os argumentos do processo do MCP server são inspecionados no container
- **THEN** nenhum argumento contém usuário ou senha de conexão

### Requirement: Proxy injeta a credencial na conexão upstream
O proxy SHALL autenticar a conexão ao banco real usando a credencial guardada nele, sem que o cliente (agente ou app gerada) precise conhecê-la.

#### Scenario: Cliente sem senha executa consulta
- **WHEN** o agente ou a app gerada abre uma conexão ao proxy sem fornecer senha
- **THEN** o proxy completa a autenticação com o banco real e a consulta executa normalmente

### Requirement: Gate sobre toda statement do wire protocol
O proxy SHALL extrair e classificar cada statement que atravessa a conexão com o classificador canônico: `normal` SHALL ser repassada; `bloqueada` SHALL ser recusada com erro de protocolo ao cliente sem tocar o banco; `confirmável` SHALL ser segurada até a decisão do editor, executando após aprovação ou devolvendo erro após recusa.

#### Scenario: DELETE em massa via arquivo é segurado
- **WHEN** o agente grava um arquivo `.sql` contendo `DELETE FROM clientes` e executa `psql -f arquivo.sql` apontando para o DSN de loopback
- **THEN** o proxy classifica a statement como confirmável e a execução aguarda a decisão do editor no chat

#### Scenario: DDL recusada por qualquer caminho
- **WHEN** uma statement `DROP TABLE` chega por qualquer cliente da conexão (MCP, psql, script Python, app gerada)
- **THEN** o proxy recusa a statement com erro de protocolo e o banco não é tocado

### Requirement: Gate independente do protocolo de permissão do agente
O gate do proxy SHALL funcionar para qualquer cliente que fale o wire protocol do banco, sem depender do harness do agente nem de um protocolo de permissão.

#### Scenario: Agente sem protocolo de permissão continua protegido
- **WHEN** um cliente que não emite pedidos de permissão (ex.: um `psql` ou script direto) envia uma statement bloqueada ou confirmável
- **THEN** o proxy aplica a mesma decisão do gate

### Requirement: Atribuição de origem na decisão do gate
O proxy SHALL distinguir a origem da conexão (agente vs app gerada) por listeners separados e SHALL propagar essa origem ao registro da decisão do gate.

#### Scenario: Decisão da app gerada registra a origem correta
- **WHEN** uma statement confirmável vem do listener da app gerada
- **THEN** a decisão registrada carrega a origem da app, distinguível das decisões originadas no agente

### Requirement: Modo sombra antes do enforcing
O proxy SHALL suportar um modo sombra em que classifica e audita cada statement mas deixa tudo executar, e um modo enforcing que aplica as decisões do gate, com o modo selecionável por configuração.

#### Scenario: Sombra audita sem bloquear
- **WHEN** o proxy está em modo sombra e recebe `DELETE FROM clientes`
- **THEN** a statement executa no banco e a classificação confirmável fica registrada

#### Scenario: Enforcing segura a mesma statement
- **WHEN** o proxy está em modo enforcing e recebe a mesma statement
- **THEN** a execução aguarda a decisão do editor e só executa após aprovação
