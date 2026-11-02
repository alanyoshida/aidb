# destructive-gate Specification

## Purpose

Impede operações SQL destrutivas contra os bancos das conexões: o classificador canônico distingue operação normal, confirmável e bloqueada; o agente tem DDL recusado e DML em massa sujeito a aprovação no chat; a app gerada confirma operações em massa na própria interface; toda decisão fica auditada.

## Requirements

### Requirement: Classificação canônica de statements SQL
O portal SHALL classificar statements SQL com parser estrutural (sqlglot) em três classes — `normal` (DML escopado a linhas, ex.: DELETE/UPDATE por chave), `confirmável` (DELETE/UPDATE sem WHERE restritivo, sem LIMIT, ou afetando tabela inteira) e `bloqueada` (DDL: DROP, TRUNCATE, ALTER, CREATE, e múltiplas statements das quais qualquer uma seja bloqueada ou confirmável) — e essa classificação SHALL ser a mesma usada pelo gate do agente e pela app gerada.

#### Scenario: DELETE por PK é normal
- **WHEN** a statement é `DELETE FROM clientes WHERE id = 3`
- **THEN** a classificação é `normal` e não gera pedido de confirmação

#### Scenario: DELETE sem WHERE é confirmável
- **WHEN** a statement é `DELETE FROM clientes`
- **THEN** a classificação é `confirmável`

#### Scenario: DROP é bloqueado mesmo com comentários e CTEs
- **WHEN** a statement é `WITH x AS (SELECT 1) /* limpeza */ DROP TABLE clientes`
- **THEN** a classificação é `bloqueada`, independentemente de comentários, CTEs ou caixa alta/baixa

### Requirement: Gate do agente sobre SQL destrutivo
O portal SHALL interceptar os pedidos de permissão do harness do agente relacionados a execução de SQL (comandos de banco via bash e ferramentas MCP de escrita), classificar com o classificador canônico e responder automaticamente: `bloqueada` SHALL ser recusada sem intervenção; `confirmável` SHALL aguardar decisão do editor; `normal` SHALL ser liberada sem atrito.

#### Scenario: Agente pede TRUNCATE e é recusado automaticamente
- **WHEN** o agente tenta executar `TRUNCATE TABLE clientes` via bash ou MCP
- **THEN** o portal recusa o pedido do harness, o agente é informado da recusa e a operação não executa

#### Scenario: Agente pede DELETE em massa e o editor decide
- **WHEN** o agente tenta executar `DELETE FROM clientes WHERE cidade = 'São Paulo'` (sem escopo de linha)
- **THEN** o chat exibe o SQL e botões aprovar/recusar, a execução aguarda a decisão, e apenas após aprovação o harness prossegue

### Requirement: Aprovação no chat com registro
O portal SHALL exibir no chat os pedidos de operação `confirmável` vindos do agente — com o SQL e a conexão de destino — e SHALL permitir que o próprio editor que conduz a sessão aprove ou recuse; cada decisão SHALL ser registrada com autor, SQL, conexão, decisão e timestamp.

#### Scenario: Editor aprova DELETE em massa
- **WHEN** o editor aprova o pedido de `DELETE FROM clientes WHERE cidade = 'São Paulo'`
- **THEN** o harness recebe a aprovação, a statement executa, e a decisão fica registrada com o editor como autor

#### Scenario: Editor recusa e o agente continua
- **WHEN** o editor recusa o pedido
- **THEN** a statement não executa, o agente é notificado da recusa e a sessão continua

### Requirement: Gate na app gerada
Toda app gerada SHALL acessar o banco por meio da camada de acesso a dados do template da plataforma, que classifica toda statement com o classificador canônico: `confirmável` SHALL exigir confirmação explícita na interface (diálogo com a SQL e a contagem estimada de linhas afetadas) antes de executar, e `bloqueada` SHALL ser recusada com mensagem clara.

#### Scenario: App confirma exclusão em massa
- **WHEN** um usuário da app dispara uma operação classificada como `confirmável`
- **THEN** a app exibe diálogo com a SQL e a contagem estimada de linhas e só executa após confirmação

#### Scenario: App recusa DDL
- **WHEN** a app tenta executar uma statement classificada como `bloqueada`
- **THEN** a operação é recusada com mensagem clara e nada é enviado ao banco

### Requirement: Auditoria das decisões do gate
O portal SHALL registrar toda decisão do gate — aprovada, recusada pelo editor ou bloqueada automaticamente — com autor (quando houver), SQL, conexão, classificação e timestamp, e SHALL exibir esse histórico na página do sistema para editores e admins.

#### Scenario: Histórico visível na página do sistema
- **WHEN** um editor abre a página do sistema após uma aprovação e um bloqueio
- **THEN** o histórico do gate lista ambos os eventos com SQL, decisão, autor e data

### Requirement: Guidelines e template obrigatórios para apps geradas
As guidelines da plataforma SHALL exigir que toda app gerada use a camada de acesso a dados do template (com o classificador canônico) para qualquer acesso ao banco, e o provisionamento SHALL garantir que a dependência do classificador esteja disponível na app.

#### Scenario: App gerada após a change usa o gate
- **WHEN** o agente gera uma nova app após esta mudança
- **THEN** a app contém a camada do template e operações confirmáveis nela disparam confirmação
