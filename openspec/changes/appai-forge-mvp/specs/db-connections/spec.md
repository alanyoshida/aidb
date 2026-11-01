# Spec Delta

## Purpose

Registra como as conexões de banco de dados são cadastradas por sistema, validadas, protegidas e entregues ao agente (via MCP) e à app gerada (via credencial de ambiente). No MVP o único tipo suportado é PostgreSQL.

## ADDED Requirements

### Requirement: Cadastro de conexão PostgreSQL por sistema
O portal SHALL permitir que o dono de um sistema cadastre conexões PostgreSQL informando nome, host, porta, banco, usuário e senha, sem limite de conexões por sistema.

#### Scenario: Dono cadastra duas conexões
- **WHEN** o dono cadastra duas conexões distintas no mesmo sistema
- **THEN** ambas ficam disponíveis ao sistema para seleção nos pedidos ao agente

### Requirement: Teste de conexão antes de salvar
O portal SHALL testar a conectividade e as credenciais antes de confirmar o cadastro de uma conexão.

#### Scenario: Conexão válida
- **WHEN** o dono salva uma conexão cujas credenciais acessam o banco informado
- **THEN** o portal confirma o cadastro após teste bem-sucedido

#### Scenario: Conexão inválida
- **WHEN** o dono tenta salvar uma conexão com host inacessível ou credenciais erradas
- **THEN** o portal recusa o cadastro informando que o teste falhou

### Requirement: Credenciais protegidas em repouso e na interface
O portal SHALL armazenar senhas de conexões cifradas e nunca exibi-las de volta, nem registrá-las em logs ou eventos do agente.

#### Scenario: Edição de conexão não revela senha
- **WHEN** o dono abre uma conexão cadastrada para edição
- **THEN** o campo de senha não retorna o valor salvo

#### Scenario: Eventos do agente sem segredos
- **WHEN** o agente executa operações usando uma conexão e os eventos são exibidos no chat
- **THEN** nenhum evento contém a senha ou connection string completa

### Requirement: Provisão da conexão ao agente e à app
O portal SHALL disponibilizar cada conexão ativa de um sistema ao agente como ferramenta de acesso ao banco (MCP) e à app gerada como credencial de ambiente.

#### Scenario: Agente inspeciona o banco
- **WHEN** um editor pede ao agente do sistema que analise as tabelas de uma conexão cadastrada
- **THEN** o agente consegue listar e descrever o schema usando essa conexão

#### Scenario: App gerada conecta ao banco
- **WHEN** a app gerada inicia no container do sistema
- **THEN** recebe as credenciais das conexões do sistema por variáveis de ambiente

### Requirement: Remoção de conexão
O portal SHALL permitir que o dono remova uma conexão do sistema, cessando imediatamente seu provisionamento ao agente e à app.

#### Scenario: Remoção reverte provisionamento
- **WHEN** o dono remove uma conexão ativa
- **THEN** o agente passa a não ter mais acesso ao banco correspondente nas próximas sessões
