# Spec Delta

## ADDED Requirements

### Requirement: Portal alcança o harness de cada sistema pela rede interna do cluster
Quando o driver de provisionamento ativo é Kubernetes e o portal roda dentro do cluster, o
driver SHALL expor a porta do harness do agente de cada sistema por um endereço alcançável pelo
portal através da rede interna do cluster.

#### Scenario: Portal conversa com o harness do sistema
- **WHEN** o portal, rodando dentro do cluster, envia um pedido ao harness de um sistema
  provisionado pelo driver Kubernetes
- **THEN** o harness responde, incluindo o streaming de eventos da execução, exatamente como
  ocorre com um sistema provisionado pelo driver Docker

### Requirement: Persistência dos dados operacionais do portal quando o driver é Kubernetes
Quando o driver de provisionamento ativo é Kubernetes, os dados operacionais do próprio portal
(sistemas, checkpoints, uso de tokens e demais registros da plataforma) SHALL persistir através
de recriações do processo do portal, com a mesma durabilidade que esses dados já têm hoje fora do
cluster.

#### Scenario: Dados do portal sobrevivem à recriação do processo
- **WHEN** o processo do portal é recriado, rodando dentro do cluster com o driver Kubernetes
  ativo
- **THEN** os sistemas, checkpoints e demais registros da plataforma continuam presentes depois,
  sem perda

## MODIFIED Requirements

### Requirement: Paridade observável entre drivers de provisionamento
O portal SHALL apresentar um sistema provisionado pelo driver Kubernetes com o mesmo comportamento
observável, definido pelas capabilities `container-lifecycle`, `app-serving` e `agent-harness`,
que um sistema provisionado pelo driver Docker — independentemente de qual driver está ativo.

#### Scenario: Sistema ativo e acessível igual nos dois drivers
- **WHEN** um sistema é provisionado com o driver Kubernetes ativo
- **THEN** ele fica ativo, acessível em `/apps/{slug}` e reconciliável exatamente como um sistema
  provisionado com o driver Docker ativo

#### Scenario: Troca de driver imperceptível ao editor do sistema
- **WHEN** o administrador da plataforma muda a configuração do driver de provisionamento ativo
- **THEN** editores dos sistemas já existentes não percebem diferença no comportamento do portal

#### Scenario: Chat com o agente funciona igual nos dois drivers
- **WHEN** um editor conversa com o agente de um sistema provisionado com o driver Kubernetes
  ativo
- **THEN** o chat, o streaming de eventos, a interrupção de execução e os checkpoints funcionam
  exatamente como definido pela capability `agent-harness`, igual a um sistema provisionado com o
  driver Docker ativo
