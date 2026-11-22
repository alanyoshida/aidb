## MODIFIED Requirements

### Requirement: Reconciliação do estado dos Pods
O driver Kubernetes SHALL, ao iniciar e periodicamente, reconciliar o estado real dos Pods de
sistema com o estado registrado no portal, corrigindo divergências da mesma forma que o driver
Docker já faz para containers. Um Pod que diverge da configuração vigente do portal (sem o
container auxiliar `git`, ou com imagem ou Secrets de pull diferentes dos configurados) SHALL ser
tratado como ausente e recriado, preservando o workspace e o repositório do sistema.

#### Scenario: Pod ausente é recriado
- **WHEN** a reconciliação do driver Kubernetes encontra um sistema ativo sem Pod correspondente
  no cluster
- **THEN** o driver recria o Pod daquele sistema

#### Scenario: Pod divergente da configuração é recriado
- **WHEN** a reconciliação do driver Kubernetes encontra o Pod de um sistema ativo sem o container
  `git`, ou com imagem ou Secrets de pull diferentes da configuração atual do portal
- **THEN** o driver recria o Pod daquele sistema com a configuração atual
- **AND** o workspace e o histórico de checkpoints do sistema continuam os mesmos
