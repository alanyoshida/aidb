# db-connections — Delta (db-bigquery)

## Changed Requirements

### Requirement: Cadastro de conexão por sistema (era: "PostgreSQL por sistema")

**BEFORE**: O portal SHALL permitir que o dono de um sistema cadastre conexões PostgreSQL informando nome, host, porta, banco, usuário e senha, sem limite de conexões por sistema.

**AFTER**: O portal SHALL permitir que o dono de um sistema cadastre conexões de banco de dados (PostgreSQL, MySQL ou BigQuery) informando os campos adequados ao tipo escolhido, sem limite de conexões por sistema.
