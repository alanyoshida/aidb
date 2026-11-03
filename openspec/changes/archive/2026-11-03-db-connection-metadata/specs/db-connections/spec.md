# Spec Delta

## ADDED Requirements

### Requirement: Descrição e modo de acesso configuráveis por conexão
O portal SHALL permitir que o dono informe uma descrição textual e um modo de acesso (`read_write` ou `read_only`) ao cadastrar ou editar uma conexão, com `read_write` como padrão.

#### Scenario: Cadastro com descrição e modo read_only
- **WHEN** o dono cadastra uma conexão informando descrição e selecionando modo somente-leitura
- **THEN** a conexão é salva com esses metadados e os exibe na listagem

#### Scenario: Cadastro sem metadados mantém padrão
- **WHEN** o dono cadastra uma conexão sem preencher description ou access_mode
- **THEN** a conexão usa `read_write` como modo padrão e fica sem descrição

### Requirement: Contexto da conexão exposto ao agente
O portal SHALL incluir a descrição e o modo de acesso da conexão na configuração entregue ao agente, de forma que o agente receba esse contexto sem instrução manual do editor.

#### Scenario: Agente recebe contexto da conexão
- **WHEN** o agente inicia uma sessão em um sistema com conexões que possuem descrição cadastrada
- **THEN** as ferramentas MCP correspondentes exibem a descrição como parte do seu nome ou documentação

### Requirement: Modo somente-leitura enforçado pelo portal
O portal SHALL garantir que conexões configuradas como `read_only` não permitam operações de escrita via MCP, mesmo que o agente tente executá-las.

#### Scenario: Escrita bloqueada em conexão read_only
- **WHEN** o agente tenta executar uma query de escrita (INSERT, UPDATE, DELETE, DDL) usando uma conexão configurada como `read_only`
- **THEN** a operação é recusada com mensagem indicando que a conexão é somente-leitura

#### Scenario: Leitura permitida em conexão read_only
- **WHEN** o agente executa uma query de leitura (SELECT, EXPLAIN) em uma conexão configurada como `read_only`
- **THEN** a query é executada normalmente
