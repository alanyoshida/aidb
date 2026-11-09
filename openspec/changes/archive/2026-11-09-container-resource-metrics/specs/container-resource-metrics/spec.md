# Spec Delta

## Purpose

Dá visibilidade de uso de CPU, memória e quantidade de processos de cada container de sistema contra os limites configurados, via dashboard, sem exigir nenhuma instrumentação no código do portal.

## ADDED Requirements

### Requirement: Visibilidade de uso de recursos por sistema
Para cada sistema com container ativo, a plataforma SHALL expor o uso de CPU, memória e quantidade de processos daquele container, junto com o respectivo limite configurado, de forma consultável por sistema.

#### Scenario: Sistema com container ativo
- **WHEN** um sistema tem um container ativo e consome CPU, memória ou processos
- **THEN** o uso correspondente fica disponível, identificado pelo sistema a que pertence, junto com o limite configurado daquele recurso

#### Scenario: Sistema sem container ativo
- **WHEN** um sistema não tem container ativo (arquivado ou em erro)
- **THEN** nenhum dado de uso de recurso é exibido para aquele sistema

### Requirement: Observabilidade de métricas opcional no deploy
A infraestrutura de coleta e visualização de uso de recursos SHALL ser opcional na implantação, e sua ausência SHALL NOT impedir ou degradar o funcionamento normal do portal, do broker ou dos sistemas provisionados.

#### Scenario: Deploy sem a infraestrutura de métricas
- **WHEN** o ambiente é implantado sem a infraestrutura de métricas habilitada
- **THEN** o portal, o broker e os sistemas provisionados continuam operando normalmente, sem erros relacionados à ausência dela

#### Scenario: Deploy com a infraestrutura de métricas
- **WHEN** o ambiente é implantado com a infraestrutura de métricas habilitada
- **THEN** o uso de CPU, memória e processos de cada sistema passa a ser coletado e fica disponível para visualização

### Requirement: Visualização compartilhada entre observabilidade de execução e de recursos
A interface de visualização SHALL ficar disponível ao habilitar qualquer uma das infraestruturas opcionais de observabilidade (rastreamento de execução ou uso de recursos), isoladamente ou em conjunto, sem duplicar a interface.

#### Scenario: Só a observabilidade de execução habilitada
- **WHEN** o ambiente sobe só a infraestrutura de rastreamento de execução (traços/logs)
- **THEN** a interface de visualização fica disponível, mesmo sem a infraestrutura de uso de recursos habilitada

#### Scenario: Só a observabilidade de uso de recursos habilitada
- **WHEN** o ambiente sobe só a infraestrutura de uso de recursos
- **THEN** a interface de visualização fica disponível, mesmo sem a infraestrutura de rastreamento de execução habilitada

#### Scenario: As duas infraestruturas habilitadas
- **WHEN** o ambiente sobe as duas infraestruturas opcionais ao mesmo tempo
- **THEN** existe apenas uma instância da interface de visualização, não duas
