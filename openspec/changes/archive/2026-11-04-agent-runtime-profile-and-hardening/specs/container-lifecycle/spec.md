# Spec Delta

## ADDED Requirements

### Requirement: Identidade de execução reduzida do container de sistema
O portal SHALL provisionar containers de sistema com identidade de execução reduzida: usuário não-root, sem nenhuma capability do kernel e sem possibilidade de escalada de privilégio, de modo que o agente opere com o menor poder suficiente para gerar e servir a app.

#### Scenario: Container novo roda sem root e sem capabilities
- **WHEN** um sistema novo é provisionado
- **THEN** o processo do agente no container roda com usuário não-root, sem capabilities do kernel e sem poder adquirir privilégio por binário com setuid

#### Scenario: Agente escreve no workspace e serve a app
- **WHEN** o agente gera a app de um sistema novo e o supervisor a sobe
- **THEN** o workspace é gravável pelo agente, a app atende na porta esperada e os checkpoints git do sistema continuam funcionando

#### Scenario: Identidade reduzida sobrevive à recriação
- **WHEN** o container de um sistema novo é recriado por reconciliação ou por reprovisionamento
- **THEN** ele volta com a mesma identidade de execução reduzida

### Requirement: Modo de execução fixado por sistema
O portal SHALL registrar, na criação de cada sistema, o modo de execução do seu container, e SHALL manter esse modo imutável pelo resto da vida do sistema. Sistemas criados antes da existência da identidade reduzida SHALL continuar rodando no modo com que foram criados, sem exigir migração de dono do workspace.

#### Scenario: Sistema existente preserva seu modo
- **WHEN** o container de um sistema criado antes desta mudança é recriado por reconciliação ou reprovisionamento
- **THEN** ele volta a subir no modo de execução original e o agente continua acessando o workspace existente

#### Scenario: Sistema novo nasce com identidade reduzida
- **WHEN** um sistema é criado após esta mudança
- **THEN** seu modo de execução é o reduzido e fica registrado no sistema

#### Scenario: Modo visível para o admin
- **WHEN** um admin consulta um sistema
- **THEN** o modo de execução do container daquele sistema é consultável, de modo que seja possível distinguir os sistemas que ainda rodam no modo antigo

## MODIFIED Requirements

### Requirement: Limites de recursos padrão
O portal SHALL aplicar a cada container de sistema os limites padrão configurados (CPUs, memória, disco e quantidade de processos) e impedir a criação que exceda a quantidade máxima de sistemas simultâneos configurada.

#### Scenario: Limites aplicados
- **WHEN** um container de sistema é criado
- **THEN** ele fica sujeito aos limites de CPU, memória, disco e quantidade de processos padrão da plataforma

#### Scenario: Teto de simultâneos atingido
- **WHEN** a criação de um novo sistema excederia o máximo de containers simultâneos
- **THEN** o portal informa a limitação e não provisiona até haver capacidade
