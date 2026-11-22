# Spec Delta

## ADDED Requirements

### Requirement: Collector opcional no chart
O chart Helm do portal SHALL oferecer, desligado por padrão, um OTel Collector no namespace da instalação. Ele recebe OTLP do portal e do Traefik e repassa traços, métricas e logs a um endpoint OTLP externo configurável. Desligado, o render do chart SHALL ser o mesmo de antes, sem Collector e sem variáveis OTEL no portal.

#### Scenario: Observabilidade desligada
- **WHEN** o chart é renderizado com os valores padrão
- **THEN** nenhum recurso de Collector é criado e o portal não recebe variáveis de endpoint OTEL

#### Scenario: Observabilidade ligada
- **WHEN** o operador liga a observabilidade e informa o endpoint OTLP externo
- **THEN** o chart cria o Collector e o Service dele, e o Collector repassa ao endpoint informado o que receber do portal

#### Scenario: Ligada sem destino
- **WHEN** o operador liga a observabilidade sem informar o endpoint externo nem uma configuração própria do Collector
- **THEN** o chart recusa renderizar e explica que falta o destino

### Requirement: Credencial do destino só no Collector
A credencial do destino externo (token ou API key) e a CA opcional SHALL vir de um Secret indicado pelo operador e SHALL ser entregues só ao Collector. O portal e o Traefik SHALL NOT receber essa credencial.

#### Scenario: Destino com token
- **WHEN** o operador indica um Secret com o token do APM Server
- **THEN** o Collector envia ao destino com o cabeçalho de autorização montado a partir do Secret, e nenhum outro Pod do chart referencia esse Secret

#### Scenario: Destino com CA privada
- **WHEN** o operador indica uma CA no Secret
- **THEN** o Collector valida o certificado do destino com essa CA

#### Scenario: Destino sem credencial
- **WHEN** o operador não indica Secret
- **THEN** o Collector envia ao destino sem cabeçalho de autorização

### Requirement: Portal exporta para o Collector da instalação
Com a observabilidade ligada, o chart SHALL passar ao portal os endpoints de traços, métricas e logs apontando para o Collector. O chart SHALL também passar a identificação da instalação: versão igual à tag da imagem do portal, ambiente configurável, nome do Pod e namespace.

#### Scenario: Endpoints do portal
- **WHEN** a observabilidade está ligada com o Collector do chart
- **THEN** o portal recebe os três endpoints OTLP com o endereço do Service desse Collector

#### Scenario: Versão e ambiente na telemetria
- **WHEN** a imagem do portal tem a tag `1.9.0` e o ambiente configurado é `producao`
- **THEN** a telemetria do portal chega com `service.version=1.9.0`, `deployment.environment=producao` e o nome do Pod que a emitiu

#### Scenario: Collector já existente no cluster
- **WHEN** o operador liga a observabilidade, desliga a criação do Collector e informa o endereço de um Collector existente
- **THEN** o chart não cria Collector e o portal recebe os endpoints do Collector informado

### Requirement: Traefik do chart envia traços e métricas ao Collector
O chart SHALL permitir ligar traços e métricas OTLP do Traefik do subchart, enviados ao Collector da instalação. Os traços do Traefik SHALL NOT conter os valores da query string.

#### Scenario: Requisição pela borda
- **WHEN** o tracing do Traefik está ligado e um navegador acessa o portal pela rota de entrada
- **THEN** o traço tem o span do Traefik como pai do span de servidor do portal

#### Scenario: Query string na borda
- **WHEN** uma requisição chega ao Traefik com parâmetros na query string
- **THEN** o span do Traefik não traz os valores desses parâmetros

### Requirement: Métricas de recursos dos Pods por sistema
O chart SHALL oferecer, desligada por padrão, a coleta de CPU e memória dos Pods do portal e dos sistemas a partir do kubelet de cada nó. Essas métricas SHALL identificar o sistema dono do Pod pelo slug e pelo id. A permissão de leitura das estatísticas dos nós SHALL ser criada só quando a coleta estiver ligada.

#### Scenario: Coleta desligada
- **WHEN** a observabilidade está ligada e a coleta de recursos não
- **THEN** o chart não cria coletor por nó nem permissão sobre os nós

#### Scenario: Pod de sistema
- **WHEN** a coleta está ligada e um sistema tem o Pod rodando
- **THEN** as métricas de CPU e memória desse Pod chegam ao destino com o slug e o id do sistema

#### Scenario: Pods fora da instalação
- **WHEN** a coleta está ligada e o nó roda Pods de outros namespaces
- **THEN** só as métricas dos Pods do namespace da instalação e do namespace dos sistemas chegam ao destino

### Requirement: Configuração própria do Collector
O chart SHALL aceitar uma configuração completa do Collector central fornecida pelo operador, que substitui a gerada. Isso permite outro backend ou outro pipeline sem mudar o chart, o portal ou o Traefik.

#### Scenario: Outro backend
- **WHEN** o operador fornece a própria configuração do Collector, mandando para outro backend
- **THEN** o Collector usa essa configuração, e o portal e o Traefik continuam apontando para o mesmo Service
