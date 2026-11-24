# Spec Delta

## MODIFIED Requirements

### Requirement: Conexões exigidas pela versão
Antes de implantar uma versão, o portal SHALL ler o manifesto de conexões daquela versão e SHALL recusar a implantação quando alguma conexão exigida não estiver ativa no sistema com o mesmo alias, listando as que faltam.

#### Scenario: Conexão faltando
- **WHEN** o manifesto da versão exige a conexão `vendas` e o sistema não tem conexão ativa com esse alias
- **THEN** a implantação é recusada listando `vendas` como faltante, e a versão atual continua servida

#### Scenario: Conexão autorizada mas não ativada
- **WHEN** o manifesto da versão exige a conexão `vendas` e há uma conexão autorizada para o sistema que o dono ainda não ativou
- **THEN** a implantação é recusada listando `vendas` como faltante

#### Scenario: Conexões completas
- **WHEN** todas as conexões do manifesto estão ativas no sistema com os mesmos aliases
- **THEN** a implantação segue normalmente

#### Scenario: Versão sem manifesto
- **WHEN** a versão não tem manifesto de conexões
- **THEN** a implantação segue e o portal avisa que não pôde conferir as conexões
