# Spec Delta

## MODIFIED Requirements

### Requirement: Manifesto de conexões gravado a cada checkpoint
Em um sistema com repositório remoto ativo, o portal SHALL gravar, a cada checkpoint, um manifesto no repositório com o alias e o tipo de cada conexão de banco ativa no sistema, sem nenhuma credencial, para que o portal de produção confira as conexões antes de implantar. O alias SHALL ocupar o campo de nome do manifesto, e conexões autorizadas mas não ativadas SHALL NOT constar nele.

#### Scenario: Manifesto acompanha o checkpoint
- **WHEN** um sistema com repositório ativo tem as conexões ativas com alias `vendas` (PostgreSQL) e `estoque` (MySQL) e um checkpoint é criado
- **THEN** o commit do checkpoint contém o manifesto com essas duas conexões e seus tipos

#### Scenario: Nenhuma credencial no manifesto
- **WHEN** o manifesto é gravado
- **THEN** ele não contém host, porta, usuário, senha, nome da conexão no catálogo nem qualquer outro dado da conexão além de alias e tipo

#### Scenario: Conexão nova
- **WHEN** o editor ativa uma conexão autorizada e um checkpoint é criado em seguida
- **THEN** o manifesto do checkpoint inclui a conexão nova

#### Scenario: Conexão não ativada fica fora
- **WHEN** uma conexão está autorizada para o sistema mas não foi ativada e um checkpoint é criado
- **THEN** o manifesto do checkpoint não a inclui

#### Scenario: Sistema sem repositório
- **WHEN** um sistema não tem repositório remoto ativo
- **THEN** nenhum manifesto é gravado no workspace
