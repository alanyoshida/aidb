# db-connections Specification

## Purpose

Registra como as conexões de banco de dados são cadastradas por sistema, validadas, protegidas e entregues ao agente (via MCP) e à app gerada (via credencial de ambiente). Os tipos suportados são PostgreSQL, MySQL e BigQuery.

## Requirements

### Requirement: Cadastro de conexão por sistema
O portal SHALL permitir que o dono de um sistema cadastre conexões de banco de dados (PostgreSQL, MySQL ou BigQuery) informando os campos adequados ao tipo escolhido, sem limite de conexões por sistema.

#### Scenario: Dono cadastra duas conexões
- **WHEN** o dono cadastra duas conexões distintas no mesmo sistema
- **THEN** ambas ficam disponíveis ao sistema para seleção nos pedidos ao agente

#### Scenario: Dono cadastra conexão MySQL
- **WHEN** o dono cadastra uma conexão com tipo MySQL informando as credenciais
- **THEN** a conexão é salva com tipo mysql e disponibilizada ao agente via MCP

### Requirement: Teste de conexão antes de salvar
O portal SHALL testar a conectividade e as credenciais antes de confirmar o cadastro de uma conexão, e SHALL informar o motivo relatado pelo driver quando o teste falhar, sem expor a senha.

#### Scenario: Conexão válida
- **WHEN** o dono salva uma conexão cujas credenciais acessam o banco informado
- **THEN** o portal confirma o cadastro após teste bem-sucedido

#### Scenario: Conexão inválida
- **WHEN** o dono tenta salvar uma conexão com host inacessível ou credenciais erradas
- **THEN** o portal recusa o cadastro informando que o teste falhou, junto do motivo relatado pelo driver, incluindo host e porta quando o driver os informar

#### Scenario: Senha não aparece na mensagem de erro
- **WHEN** o driver inclui a senha no texto do erro que motivou a falha
- **THEN** o portal remove a senha antes de exibir a mensagem ao usuário

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

### Requirement: Agente acessa bancos MySQL via MCP
O portal SHALL disponibilizar conexões MySQL ao agente com as mesmas ferramentas de leitura disponíveis para PostgreSQL (listar tabelas, descrever tabela, consulta de leitura).

#### Scenario: Agente inspeciona tabelas de banco MySQL
- **WHEN** um editor pede ao agente que analise as tabelas de uma conexão MySQL cadastrada
- **THEN** o agente consegue listar e descrever o schema usando essa conexão

#### Scenario: Escrita bloqueada em MySQL via MCP
- **WHEN** o agente tenta executar uma query de escrita em uma conexão MySQL via MCP
- **THEN** a operação é recusada pelo gate, da mesma forma que em conexões PostgreSQL

### Requirement: App gerada recebe credenciais de banco conforme tipo
O portal SHALL gerar a variável de ambiente `DATABASE_URL_<NOME>` com o scheme correto para o tipo da conexão (`postgresql://` para PostgreSQL, `mysql://` para MySQL, `bigquery://` com `credentials_base64` para BigQuery).

#### Scenario: App recebe URL com scheme mysql
- **WHEN** a app gerada inicia no container de um sistema com conexão MySQL
- **THEN** recebe `DATABASE_URL_<NOME>=mysql://...` nas variáveis de ambiente

#### Scenario: App recebe URL com scheme bigquery
- **WHEN** a app gerada inicia no container de um sistema com conexão BigQuery
- **THEN** recebe `DATABASE_URL_<NOME>=bigquery://...` com as credenciais da Service Account codificadas em `credentials_base64`

### Requirement: Remoção de conexão
O portal SHALL permitir que o dono remova uma conexão do sistema, cessando imediatamente seu provisionamento ao agente e à app.

#### Scenario: Remoção reverte provisionamento
- **WHEN** o dono remove uma conexão ativa
- **THEN** o agente passa a não ter mais acesso ao banco correspondente nas próximas sessões

### Requirement: Estado de saúde monitorado por conexão
O portal SHALL verificar periodicamente a conectividade de cada conexão de banco cadastrada nos sistemas ativos e manter um estado de saúde (`healthy`, `degraded`, `unknown`) atualizado.

#### Scenario: Conexão saudável após verificação
- **WHEN** o portal verifica uma conexão e consegue conectar e executar uma query simples
- **THEN** o estado da conexão passa a ser `healthy` e o horário da última verificação é atualizado

#### Scenario: Conexão degradada após verificação
- **WHEN** o portal verifica uma conexão e não consegue conectar dentro do timeout
- **THEN** o estado da conexão passa a ser `degraded` e o horário da última verificação é atualizado

### Requirement: Estado de saúde visível na interface
O portal SHALL exibir o estado de saúde de cada conexão na página do sistema, com indicação visual distinta para cada estado.

#### Scenario: Badge saudável
- **WHEN** um editor abre a aba de conexões de um sistema
- **THEN** cada conexão exibe um indicador de estado que reflete o último resultado da verificação

#### Scenario: Conexão nunca verificada
- **WHEN** uma conexão foi cadastrada mas ainda não passou pelo ciclo de verificação
- **THEN** seu estado aparece como desconhecido, não como erro

### Requirement: Conexões degradadas visíveis ao admin
O portal SHALL permitir que administradores consultem um resumo das conexões degradadas em todos os sistemas, para diagnóstico operacional.

#### Scenario: Admin identifica conexões com problema
- **WHEN** um admin acessa a área de administração
- **THEN** consegue ver quais sistemas têm conexões em estado degradado, com nome do sistema e da conexão

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

### Requirement: Configuração do agente isolada do workspace
O portal SHALL gravar o arquivo de configuração do agente (incluindo as connection strings dos bancos) em um diretório separado, fora do workspace acessível ao agente, de forma que o conteúdo do workspace não exponha credenciais de banco de dados.

#### Scenario: opencode.json não está no workspace
- **WHEN** o agente lista ou lê os arquivos do workspace de um sistema com conexões cadastradas
- **THEN** o arquivo de configuração do agente (opencode.json) não está presente no workspace e as connection strings não são acessíveis por navegação de arquivos no workspace
