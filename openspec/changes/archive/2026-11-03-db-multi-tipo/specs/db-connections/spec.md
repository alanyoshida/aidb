# Spec Delta

## MODIFIED Requirements

### Requirement: Cadastro de conexão PostgreSQL por sistema
O portal SHALL permitir que o dono de um sistema cadastre conexões de banco de dados informando nome, tipo (`PostgreSQL` ou `MySQL`), host, porta, banco, usuário e senha, sem limite de conexões por sistema.

#### Scenario: Dono cadastra duas conexões
- **WHEN** o dono cadastra duas conexões distintas no mesmo sistema
- **THEN** ambas ficam disponíveis ao sistema para seleção nos pedidos ao agente

#### Scenario: Dono cadastra conexão MySQL
- **WHEN** o dono cadastra uma conexão com tipo MySQL informando as credenciais
- **THEN** a conexão é salva com tipo mysql e disponibilizada ao agente via MCP

## ADDED Requirements

### Requirement: Agente acessa bancos MySQL via MCP
O portal SHALL disponibilizar conexões MySQL ao agente com as mesmas ferramentas de leitura disponíveis para PostgreSQL (listar tabelas, descrever tabela, consulta de leitura).

#### Scenario: Agente inspeciona tabelas de banco MySQL
- **WHEN** um editor pede ao agente que analise as tabelas de uma conexão MySQL cadastrada
- **THEN** o agente consegue listar e descrever o schema usando essa conexão

#### Scenario: Escrita bloqueada em MySQL via MCP
- **WHEN** o agente tenta executar uma query de escrita em uma conexão MySQL via MCP
- **THEN** a operação é recusada pelo gate, da mesma forma que em conexões PostgreSQL

### Requirement: App gerada recebe credenciais de banco conforme tipo
O portal SHALL gerar a variável de ambiente `DATABASE_URL_<NOME>` com o scheme correto para o tipo da conexão (`postgresql://` para PostgreSQL, `mysql://` para MySQL).

#### Scenario: App recebe URL com scheme mysql
- **WHEN** a app gerada inicia no container de um sistema com conexão MySQL
- **THEN** recebe `DATABASE_URL_<NOME>=mysql://...` nas variáveis de ambiente
