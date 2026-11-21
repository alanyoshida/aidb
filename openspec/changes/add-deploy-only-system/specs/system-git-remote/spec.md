# Spec Delta

## ADDED Requirements

### Requirement: Manifesto de conexões gravado a cada checkpoint
Em um sistema com repositório remoto ativo, o portal SHALL gravar, a cada checkpoint, um manifesto no repositório com o nome e o tipo de cada conexão de banco cadastrada no sistema, sem nenhuma credencial, para que o portal de produção confira as conexões antes de implantar.

#### Scenario: Manifesto acompanha o checkpoint
- **WHEN** um sistema com repositório ativo tem as conexões `vendas` (PostgreSQL) e `estoque` (MySQL) e um checkpoint é criado
- **THEN** o commit do checkpoint contém o manifesto com essas duas conexões e seus tipos

#### Scenario: Nenhuma credencial no manifesto
- **WHEN** o manifesto é gravado
- **THEN** ele não contém host, porta, usuário, senha nem qualquer outro dado da conexão além de nome e tipo

#### Scenario: Conexão nova
- **WHEN** o editor cadastra uma conexão e um checkpoint é criado em seguida
- **THEN** o manifesto do checkpoint inclui a conexão nova

#### Scenario: Sistema sem repositório
- **WHEN** um sistema não tem repositório remoto ativo
- **THEN** nenhum manifesto é gravado no workspace
