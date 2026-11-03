# Spec Delta

## ADDED Requirements

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
