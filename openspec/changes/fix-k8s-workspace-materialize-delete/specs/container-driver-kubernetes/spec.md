# Spec Delta

## ADDED Requirements

### Requirement: Escrita no workspace sem caminho local acessível ao portal
O driver Kubernetes SHALL expor um mecanismo para que o portal escreva arquivos no workspace de um
sistema sem depender de um caminho local montado — já que, ao contrário do bind mount do driver
Docker, a PVC do workspace só é visível de dentro do cluster.

#### Scenario: Guidelines chegam ao workspace real do sistema
- **WHEN** o portal materializa AGENTS.md e os templates canônicos para um sistema provisionado
  pelo driver Kubernetes
- **THEN** os arquivos aparecem no workspace real que o agente do sistema vê, e não num caminho
  local do processo do portal

#### Scenario: Container do agente ainda não está pronto
- **WHEN** o portal tenta escrever no workspace de um sistema cujo Pod ou container do agente
  ainda não está em execução
- **THEN** o portal aguarda a prontidão do container ou refaz a tentativa, em vez de falhar a
  execução silenciosamente ou descartar a escrita sem registrar o problema

### Requirement: Remoção do armazenamento persistente do workspace na exclusão definitiva
O driver Kubernetes SHALL remover, via API do Kubernetes, o armazenamento persistente do workspace
de um sistema quando esse sistema é definitivamente excluído, para que a exclusão não deixe
armazenamento órfão no cluster.

#### Scenario: Exclusão definitiva remove a PVC do workspace
- **WHEN** um administrador exclui definitivamente um sistema provisionado pelo driver Kubernetes
- **THEN** a PVC do workspace desse sistema deixa de existir no cluster

#### Scenario: Arquivamento e reprovisionamento preservam a PVC
- **WHEN** um sistema provisionado pelo driver Kubernetes é arquivado, removido por
  `driver.remove()`, ou reprovisionado
- **THEN** a PVC do seu workspace continua existindo, sem perda de conteúdo
