# container-driver-kubernetes Specification

## Purpose

Define o comportamento do driver de provisionamento Kubernetes: como ele materializa, num
cluster, os mesmos sistemas que o driver Docker provisiona hoje, de forma observável pelo portal
exatamente como um sistema provisionado por Docker.

## Requirements

### Requirement: Pod único por sistema com containers compartilhando rede
O driver Kubernetes SHALL provisionar, para cada sistema, um único Pod contendo o container do
agente e os sidecars de gate de banco e de proxy HTTP(S) de saída desse sistema, compartilhando o
mesmo network namespace do Pod.

#### Scenario: Sidecar alcança o agente por loopback
- **WHEN** um sidecar do Pod de um sistema abre uma conexão de rede num endereço loopback
- **THEN** alcança o processo do container do agente do mesmo Pod

#### Scenario: Containers do Pod sobem juntos, sem depender de ordem
- **WHEN** o Pod de um sistema é criado
- **THEN** o container do agente e os dois sidecars sobem como parte do mesmo Pod, sem exigir que
  um exista primeiro para que o outro descubra seu endereço

### Requirement: Armazenamento persistente de workspace e config
O driver Kubernetes SHALL vincular o workspace e o diretório de configuração de cada sistema a
armazenamento persistente que sobrevive à recriação do Pod, com a mesma durabilidade que o bind
mount de host tem hoje no driver Docker.

#### Scenario: Workspace sobrevive à recriação do Pod
- **WHEN** o Pod de um sistema é recriado, por reprovisionamento ou por reconciliação
- **THEN** os arquivos gravados no workspace antes da recriação continuam presentes depois, sem
  perda

### Requirement: App acessível de fora do cluster sem exposição além do necessário
O driver Kubernetes SHALL rotear o acesso externo a `/apps/{slug}` de cada sistema até o Pod
correspondente, e SHALL manter as demais portas do Pod (harness do agente, sidecars) inacessíveis
de fora do cluster.

#### Scenario: App alcançável pelo caminho publicado
- **WHEN** um editor com acesso ao sistema abre `/apps/{slug}` com o sistema provisionado pelo
  driver Kubernetes
- **THEN** a app responde normalmente, como ocorre no driver Docker

#### Scenario: Harness e sidecars não alcançáveis de fora do cluster
- **WHEN** alguém de fora do cluster tenta conectar direto na porta do harness do agente ou de um
  dos sidecars de um sistema
- **THEN** a tentativa falha, porque só a porta da app é roteada para fora do cluster

### Requirement: Limites de recursos mapeados para o Pod
O driver Kubernetes SHALL mapear os limites padrão de CPU, memória e disco configurados para a
plataforma nos limites de recursos do Pod de cada sistema, com a quantidade de processos sendo
melhor-esforço, sem garantia de bloqueio rígido por container.

#### Scenario: Limite de CPU e memória aplicado
- **WHEN** um sistema é provisionado pelo driver Kubernetes
- **THEN** o Pod resultante tem limites de CPU e memória equivalentes aos limites padrão
  configurados para a plataforma

#### Scenario: Quantidade de processos sem bloqueio garantido
- **WHEN** um processo dentro do container do agente tenta abrir muito mais processos filhos do
  que o limite padrão configurado
- **THEN** o driver Kubernetes não garante bloquear essa tentativa da mesma forma rígida que o
  driver Docker bloqueia hoje — limitação conhecida e documentada, não uma falha silenciosa

### Requirement: Reconciliação do estado dos Pods
O driver Kubernetes SHALL, ao iniciar e periodicamente, reconciliar o estado real dos Pods de
sistema com o estado registrado no portal, corrigindo divergências da mesma forma que o driver
Docker já faz para containers.

#### Scenario: Pod ausente é recriado
- **WHEN** a reconciliação do driver Kubernetes encontra um sistema ativo sem Pod correspondente
  no cluster
- **THEN** o driver recria o Pod daquele sistema

### Requirement: Paridade observável entre drivers de provisionamento
O portal SHALL apresentar um sistema provisionado pelo driver Kubernetes com o mesmo comportamento
observável, definido pelas capabilities `container-lifecycle` e `app-serving`, que um sistema
provisionado pelo driver Docker — independentemente de qual driver está ativo.

#### Scenario: Sistema ativo e acessível igual nos dois drivers
- **WHEN** um sistema é provisionado com o driver Kubernetes ativo
- **THEN** ele fica ativo, acessível em `/apps/{slug}` e reconciliável exatamente como um sistema
  provisionado com o driver Docker ativo

#### Scenario: Troca de driver imperceptível ao editor do sistema
- **WHEN** o administrador da plataforma muda a configuração do driver de provisionamento ativo
- **THEN** editores dos sistemas já existentes não percebem diferença no comportamento do portal
