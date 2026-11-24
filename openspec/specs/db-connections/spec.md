# db-connections Specification

## Purpose

Registra como as conexões de banco de dados são cadastradas por sistema, validadas, protegidas e entregues ao agente (via MCP) e à app gerada (via credencial de ambiente). Os tipos suportados são PostgreSQL, MySQL e BigQuery.

## Requirements

### Requirement: Teste de conexão antes de salvar
O portal SHALL testar a conectividade e as credenciais antes de confirmar o cadastro de uma conexão no catálogo ou a alteração de seu endereço ou credenciais, e SHALL informar o motivo relatado pelo driver quando o teste falhar, sem expor a senha.

#### Scenario: Conexão válida
- **WHEN** um DB Manager salva uma conexão cujas credenciais acessam o banco informado
- **THEN** o portal confirma o cadastro após teste bem-sucedido

#### Scenario: Conexão inválida
- **WHEN** um DB Manager tenta salvar uma conexão com host inacessível ou credenciais erradas
- **THEN** o portal recusa o cadastro informando que o teste falhou, junto do motivo relatado pelo driver, incluindo host e porta quando o driver os informar

#### Scenario: Senha não aparece na mensagem de erro
- **WHEN** o driver inclui a senha no texto do erro que motivou a falha
- **THEN** o portal remove a senha antes de exibir a mensagem ao usuário

#### Scenario: Edição com credencial inválida é recusada
- **WHEN** um DB Manager altera a senha de uma conexão existente para um valor que o banco não aceita
- **THEN** o portal recusa a alteração e a conexão continua com a credencial anterior

### Requirement: Credenciais protegidas em repouso e na interface
O portal SHALL armazenar senhas de conexões cifradas e nunca exibi-las de volta, nem registrá-las em logs ou eventos do agente.

#### Scenario: Edição de conexão não revela senha
- **WHEN** um DB Manager abre uma conexão do catálogo para edição
- **THEN** o campo de senha não retorna o valor salvo

#### Scenario: Eventos do agente sem segredos
- **WHEN** o agente executa operações usando uma conexão e os eventos são exibidos no chat
- **THEN** nenhum evento contém a senha ou connection string completa

### Requirement: Provisão da conexão ao agente e à app
O portal SHALL disponibilizar cada conexão ativa de um sistema ao agente como ferramenta de acesso ao banco (MCP) e à app gerada como credencial de ambiente, identificada pelo alias escolhido na ativação. Conexões do catálogo não autorizadas para o sistema, ou autorizadas e não ativadas, SHALL NOT ser entregues.

#### Scenario: Agente inspeciona o banco
- **WHEN** um editor pede ao agente do sistema que analise as tabelas de uma conexão ativa
- **THEN** o agente consegue listar e descrever o schema usando essa conexão

#### Scenario: App gerada conecta ao banco
- **WHEN** a app gerada inicia no container do sistema
- **THEN** recebe as credenciais das conexões ativas do sistema por variáveis de ambiente

#### Scenario: Ferramenta do agente leva o alias
- **WHEN** o dono ativa uma conexão do catálogo com o alias `vendas`
- **THEN** a ferramenta de acesso ao banco entregue ao agente é identificada por `vendas`, não pelo nome da conexão no catálogo

#### Scenario: Conexão não ativada não é entregue
- **WHEN** uma conexão está autorizada para o sistema mas não foi ativada
- **THEN** o agente não tem ferramenta para ela e a app não recebe variável de ambiente correspondente

### Requirement: Agente acessa bancos MySQL via MCP
O portal SHALL disponibilizar conexões MySQL ao agente com as mesmas ferramentas de leitura disponíveis para PostgreSQL (listar tabelas, descrever tabela, consulta de leitura).

#### Scenario: Agente inspeciona tabelas de banco MySQL
- **WHEN** um editor pede ao agente que analise as tabelas de uma conexão MySQL cadastrada
- **THEN** o agente consegue listar e descrever o schema usando essa conexão

#### Scenario: Escrita bloqueada em MySQL via MCP
- **WHEN** o agente tenta executar uma query de escrita em uma conexão MySQL via MCP
- **THEN** a operação é recusada pelo gate, da mesma forma que em conexões PostgreSQL

### Requirement: App gerada recebe credenciais de banco conforme tipo
O portal SHALL gerar a variável de ambiente `DATABASE_URL_<ALIAS>`, a partir do alias da conexão ativa no sistema, com o scheme correto para o tipo da conexão (`postgresql://` para PostgreSQL, `mysql://` para MySQL, `bigquery://` com `credentials_base64` para BigQuery).

#### Scenario: App recebe URL com scheme mysql
- **WHEN** a app gerada inicia no container de um sistema com uma conexão MySQL ativa
- **THEN** recebe `DATABASE_URL_<ALIAS>=mysql://...` nas variáveis de ambiente

#### Scenario: App recebe URL com scheme bigquery
- **WHEN** a app gerada inicia no container de um sistema com uma conexão BigQuery ativa
- **THEN** recebe `DATABASE_URL_<ALIAS>=bigquery://...` com as credenciais da Service Account codificadas em `credentials_base64`

#### Scenario: Mesma conexão com aliases diferentes
- **WHEN** a mesma conexão do catálogo está ativa no sistema X com o alias `vendas` e no sistema Y com o alias `erp`
- **THEN** a app de X recebe `DATABASE_URL_VENDAS` e a app de Y recebe `DATABASE_URL_ERP`

### Requirement: Estado de saúde monitorado por conexão
O portal SHALL verificar periodicamente a conectividade de cada conexão do catálogo, uma vez por conexão independentemente de quantos sistemas a usam, e manter um estado de saúde (`healthy`, `degraded`, `unknown`) atualizado.

#### Scenario: Conexão saudável após verificação
- **WHEN** o portal verifica uma conexão e consegue conectar e executar uma query simples
- **THEN** o estado da conexão passa a ser `healthy` e o horário da última verificação é atualizado

#### Scenario: Conexão degradada após verificação
- **WHEN** o portal verifica uma conexão e não consegue conectar dentro do timeout
- **THEN** o estado da conexão passa a ser `degraded` e o horário da última verificação é atualizado

#### Scenario: Conexão ainda não autorizada é verificada
- **WHEN** uma conexão do catálogo não está autorizada para nenhum sistema
- **THEN** seu estado de saúde é verificado e mantido da mesma forma

### Requirement: Estado de saúde visível na interface
O portal SHALL exibir o estado de saúde de cada conexão no catálogo e, para as conexões autorizadas, na página do sistema, com indicação visual distinta para cada estado.

#### Scenario: Badge saudável
- **WHEN** um editor abre a aba de conexões de um sistema
- **THEN** cada conexão autorizada exibe um indicador de estado que reflete o último resultado da verificação

#### Scenario: Conexão nunca verificada
- **WHEN** uma conexão foi cadastrada mas ainda não passou pelo ciclo de verificação
- **THEN** seu estado aparece como desconhecido, não como erro

#### Scenario: Estado no catálogo
- **WHEN** um DB Manager abre o catálogo
- **THEN** cada conexão exibe o indicador de estado de saúde

### Requirement: Contexto da conexão exposto ao agente
O portal SHALL incluir a descrição da conexão e o modo de acesso vigente no sistema na configuração entregue ao agente, de forma que o agente receba esse contexto sem instrução manual do editor.

#### Scenario: Agente recebe contexto da conexão
- **WHEN** o agente inicia uma sessão em um sistema com conexões ativas que possuem descrição cadastrada
- **THEN** as ferramentas MCP correspondentes exibem a descrição como parte do seu nome ou documentação

#### Scenario: Agente sabe que a DDL está liberada
- **WHEN** o agente inicia uma sessão em um sistema com uma conexão ativa em `schema_admin`
- **THEN** a ferramenta correspondente indica que alterações de estrutura estão liberadas naquela conexão

#### Scenario: Agente sabe que a conexão é somente-leitura
- **WHEN** o agente inicia uma sessão em um sistema com uma conexão ativa em `read_only`
- **THEN** a ferramenta correspondente indica que a conexão é somente-leitura

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

### Requirement: Catálogo de conexões gerido pelo DB Manager
O portal SHALL manter um catálogo único de conexões de banco (PostgreSQL, MySQL ou BigQuery), no qual somente quem gere o catálogo (DB Manager ou admin) cadastra conexões, informando nome, descrição opcional e os campos adequados ao tipo. O nome SHALL ser único no catálogo. Uma conexão do catálogo não pertence a nenhum sistema.

#### Scenario: DB Manager cadastra conexão
- **WHEN** um DB Manager cadastra uma conexão PostgreSQL com credenciais válidas
- **THEN** a conexão passa a existir no catálogo, sem estar disponível para nenhum sistema até ser autorizada

#### Scenario: DB Manager cadastra conexão MySQL
- **WHEN** um DB Manager cadastra uma conexão com tipo MySQL informando as credenciais
- **THEN** a conexão é salva no catálogo com tipo mysql

#### Scenario: Dono de sistema não cadastra conexão
- **WHEN** um editor que não é DB Manager nem admin tenta cadastrar uma conexão de banco
- **THEN** o portal recusa com mensagem de permissão insuficiente, e a página do sistema não oferece o cadastro

#### Scenario: Nome repetido no catálogo
- **WHEN** um DB Manager tenta cadastrar uma conexão com o nome de outra já existente no catálogo
- **THEN** o portal recusa informando que o nome já está em uso

#### Scenario: Catálogo compartilhado entre DB Managers
- **WHEN** um DB Manager abre o catálogo
- **THEN** vê e pode gerir todas as conexões, inclusive as cadastradas por outro DB Manager

### Requirement: Edição de conexão do catálogo
O portal SHALL permitir que quem gere o catálogo edite nome, descrição, endereço e credenciais de uma conexão, e a alteração de endereço ou credenciais SHALL passar a valer na hora para todos os sistemas em que a conexão está ativa. O tipo da conexão SHALL NOT ser alterável depois do cadastro.

#### Scenario: Troca de senha alcança todos os sistemas
- **WHEN** um DB Manager troca a senha de uma conexão ativa nos sistemas X e Y
- **THEN** os dois sistemas passam a usar a nova senha sem ação dos donos

#### Scenario: Edição lista os sistemas afetados
- **WHEN** um DB Manager vai salvar a alteração de endereço ou credenciais de uma conexão ativa em sistemas
- **THEN** o portal mostra os sistemas afetados antes de aplicar

#### Scenario: Tipo não é editável
- **WHEN** um DB Manager abre uma conexão PostgreSQL para edição
- **THEN** o tipo não pode ser alterado

### Requirement: Descrição da conexão no catálogo
O portal SHALL permitir que quem gere o catálogo informe uma descrição textual ao cadastrar ou editar uma conexão, exibida a quem gere o catálogo e aos donos dos sistemas autorizados. O modo de acesso não é atributo da conexão: é definido por sistema, conforme a capability `db-connection-access`.

#### Scenario: Descrição visível ao dono
- **WHEN** um DB Manager cadastra uma conexão com descrição e a autoriza para o sistema X
- **THEN** a aba de conexões de X exibe a descrição junto do nome

#### Scenario: Cadastro sem descrição
- **WHEN** um DB Manager cadastra uma conexão sem preencher a descrição
- **THEN** a conexão é salva sem descrição

### Requirement: Dados da conexão restritos a quem gere o catálogo
O portal SHALL exibir a quem gerencia um sistema, para cada conexão autorizada, somente nome, descrição, tipo, estado de saúde, teto e, quando ativa, alias e modo vigente. Host, porta, nome do banco, usuário e identificador da credencial SHALL ser visíveis apenas a quem gere o catálogo.

#### Scenario: Dono não vê o endereço do banco
- **WHEN** o dono do sistema X abre a aba de conexões
- **THEN** nenhuma conexão exibe host, porta, nome do banco ou usuário

#### Scenario: DB Manager vê o endereço
- **WHEN** um DB Manager abre uma conexão no catálogo
- **THEN** vê host, porta, nome do banco e usuário, sem a senha

#### Scenario: Dono não vê o catálogo
- **WHEN** um editor que não é DB Manager nem admin tenta abrir o catálogo de conexões
- **THEN** o portal recusa o acesso, e ele só vê as conexões autorizadas para os próprios sistemas

### Requirement: Exclusão de conexão do catálogo
O portal SHALL permitir que quem gere o catálogo exclua uma conexão. Quando a conexão estiver autorizada para algum sistema, o portal SHALL listar os sistemas afetados e exigir confirmação, e a exclusão SHALL revogar todas as autorizações na hora.

#### Scenario: Exclusão de conexão sem uso
- **WHEN** um DB Manager exclui uma conexão que não está autorizada para nenhum sistema
- **THEN** a conexão é removida do catálogo

#### Scenario: Exclusão de conexão em uso pede confirmação
- **WHEN** um DB Manager pede a exclusão de uma conexão autorizada para os sistemas X e Y
- **THEN** o portal mostra X e Y como afetados e só exclui após confirmação

#### Scenario: Exclusão revoga o acesso
- **WHEN** um DB Manager confirma a exclusão de uma conexão ativa no sistema X
- **THEN** o agente e a app de X deixam de receber essa conexão imediatamente

### Requirement: Conexões degradadas visíveis a quem gere o catálogo
O portal SHALL permitir que quem gere o catálogo (DB Manager ou admin) consulte um resumo das conexões do catálogo em estado degradado, para diagnóstico operacional.

#### Scenario: DB Manager identifica conexões com problema
- **WHEN** um DB Manager abre a área do catálogo de conexões
- **THEN** consegue ver quais conexões estão em estado degradado, com o nome de cada uma e os sistemas para os quais está autorizada

#### Scenario: Admin identifica conexões com problema
- **WHEN** um admin abre a área do catálogo de conexões
- **THEN** vê o mesmo resumo de conexões degradadas
