## MODIFIED Requirements

### Requirement: App gerada recebe credenciais de banco conforme tipo
O portal SHALL gerar a variável de ambiente `DATABASE_URL_<NOME>` com o scheme correto para o tipo da conexão (`postgresql://` para PostgreSQL, `mysql://` para MySQL, `bigquery://` com `credentials_base64` para BigQuery).

#### Scenario: App recebe URL com scheme mysql
- **WHEN** a app gerada inicia no container de um sistema com conexão MySQL
- **THEN** recebe `DATABASE_URL_<NOME>=mysql://...` nas variáveis de ambiente

#### Scenario: App recebe URL com scheme bigquery
- **WHEN** a app gerada inicia no container de um sistema com conexão BigQuery
- **THEN** recebe `DATABASE_URL_<NOME>=bigquery://...` com as credenciais da Service Account codificadas em `credentials_base64`
