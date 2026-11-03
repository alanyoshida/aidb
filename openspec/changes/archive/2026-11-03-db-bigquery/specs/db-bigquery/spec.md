# db-bigquery Specification

## Purpose

Define o comportamento observável de conexões BigQuery no portal AIDB: como a credencial é fornecida, validada, protegida e entregue ao agente e à app gerada, diferenciando-se das conexões TCP (Postgres/MySQL) por usar Service Account JSON como credencial e project/dataset como localização.

## Requirements

### Requirement: Cadastro de conexão BigQuery via Service Account JSON

O portal SHALL permitir cadastrar uma conexão BigQuery informando nome, GCP project ID, dataset e Service Account JSON; o campo de senha convencional NÃO é exibido para conexões BigQuery.

#### Scenario: Dono cadastra conexão BigQuery com credencial válida
- **WHEN** o dono informa project ID, dataset e um Service Account JSON com acesso ao dataset
- **THEN** o portal confirma o cadastro após teste bem-sucedido
- **AND** exibe o service account email (extraído do JSON) como identificador da credencial

#### Scenario: Service Account JSON inválido é recusado
- **WHEN** o dono informa um JSON malformado ou sem permissão no dataset
- **THEN** o portal recusa o cadastro informando que o teste de conexão falhou

### Requirement: Service Account JSON protegido como credencial sensível

O portal SHALL armazenar o Service Account JSON cifrado em repouso e nunca retorná-lo na interface, em logs ou em eventos do agente; apenas o service account email é exibido.

#### Scenario: Edição não revela o JSON
- **WHEN** o dono abre uma conexão BigQuery cadastrada para edição
- **THEN** o campo de Service Account JSON não retorna o conteúdo salvo

### Requirement: Provisão ao agente como ferramenta MCP de leitura

O portal SHALL disponibilizar uma conexão BigQuery ao agente como ferramenta MCP de leitura com as mesmas operações de conexões SQL: `list_tables`, `describe_table`, `read_query`; escritas são recusadas pelo gate.

#### Scenario: Agente lista tabelas de um dataset BigQuery
- **WHEN** o agente invoca `list_tables` em uma conexão BigQuery
- **THEN** recebe a lista de tabelas do dataset cadastrado

#### Scenario: Escrita recusada via MCP
- **WHEN** o agente tenta executar INSERT ou UPDATE via `read_query`
- **THEN** a ferramenta recusa com mensagem de gate: apenas leitura é permitida

### Requirement: Provisão à app gerada via DATABASE_URL com credentials_base64

O portal SHALL disponibilizar cada conexão BigQuery à app gerada como variável de ambiente `DATABASE_URL_<NOME>` no formato `bigquery://<project>/<dataset>?credentials_base64=<b64>`, compatível com `sqlalchemy-bigquery`.

#### Scenario: App gerada conecta ao BigQuery
- **WHEN** a app gerada inicia no container do sistema com uma conexão BigQuery cadastrada
- **THEN** recebe `DATABASE_URL_<NOME>=bigquery://<project>/<dataset>?credentials_base64=...`
- **AND** consegue conectar ao dataset usando `sqlalchemy-bigquery` com essa URL
