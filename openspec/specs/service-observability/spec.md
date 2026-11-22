# service-observability Specification

## Purpose

Define o que o portal e o broker expõem a um APM: traços automáticos de requisições, banco e chamadas de saída, métricas de aplicação e a identificação de cada serviço, e o que fica de fora da telemetria (ruído e dados sensíveis).

## Requirements

### Requirement: Traço de cada requisição HTTP recebida
O portal e o broker SHALL produzir um span de servidor para cada requisição HTTP recebida, com método, rota e status da resposta. Quando a requisição trouxer um contexto de traço W3C (`traceparent`), o span SHALL continuar esse traço. Sem endpoint de traços configurado, nada é exportado.

#### Scenario: Requisição a uma rota do portal
- **WHEN** um cliente faz uma requisição a uma rota HTTP do portal e o endpoint de traços está configurado
- **THEN** um span de servidor com o método, a rota e o status da resposta é exportado ao Collector

#### Scenario: Requisição que chega com traceparent
- **WHEN** uma requisição chega ao portal ou ao broker com um cabeçalho `traceparent` válido
- **THEN** o span de servidor dessa requisição pertence ao mesmo traço e tem como pai o span indicado no cabeçalho

#### Scenario: Chamada do broker ao portal
- **WHEN** o broker consulta o portal durante uma requisição de inferência
- **THEN** o span de servidor do portal aparece no mesmo traço da requisição recebida pelo broker

### Requirement: Caminhos internos fora dos traços
As requisições ao health check e aos caminhos internos da interface (arquivos estáticos e conexão em tempo real da UI) SHALL NOT gerar spans.

#### Scenario: Health check
- **WHEN** um orquestrador consulta o health check do portal
- **THEN** nenhum span é exportado para essa requisição

#### Scenario: Assets e websocket da interface
- **WHEN** o navegador carrega arquivos estáticos ou mantém a conexão em tempo real da interface do portal
- **THEN** nenhum span é exportado para essas requisições

### Requirement: Consultas ao banco do próprio portal nos traços
As consultas que o portal e o broker fazem ao banco do próprio portal SHALL aparecer como spans filhos da operação em curso, com o texto parametrizado da consulta. Consultas a bancos cadastrados pelos usuários SHALL NOT ser instrumentadas por esta capability.

#### Scenario: Consulta durante uma requisição
- **WHEN** uma requisição ao portal consulta o banco do portal
- **THEN** a consulta aparece como span filho do span da requisição, sem os valores dos parâmetros

#### Scenario: Consulta a uma conexão de usuário
- **WHEN** o portal executa uma consulta numa conexão de banco cadastrada por um usuário
- **THEN** nenhum span de banco desta capability é gerado para essa consulta

### Requirement: Chamadas HTTP de saída nos traços
As chamadas HTTP de saída do portal e do broker SHALL aparecer como spans de cliente filhos da operação em curso, e SHALL propagar o contexto de traço ao destino.

#### Scenario: Chamada de saída durante uma requisição
- **WHEN** o portal ou o broker faz uma chamada HTTP de saída durante uma requisição
- **THEN** um span de cliente filho do span da requisição é exportado, e a chamada leva o cabeçalho `traceparent`

### Requirement: Trabalho em segundo plano sem requisição de origem não gera traço solto
Uma consulta ao banco ou chamada HTTP de saída feita sem nenhuma operação em curso (tarefas periódicas, reconciliação, ações da interface em tempo real) SHALL NOT gerar um traço próprio só com ela.

#### Scenario: Consulta feita pela reconciliação periódica
- **WHEN** a reconciliação periódica consulta o banco do portal fora de qualquer requisição ou execução do agente
- **THEN** nenhum traço é exportado só com essa consulta

#### Scenario: Atualização periódica da página depois da requisição
- **WHEN** uma página do portal aberta no navegador consulta o banco periodicamente, depois de a requisição que a carregou ter terminado
- **THEN** essas consultas não são anexadas ao traço daquela requisição nem geram traço próprio

#### Scenario: Span raiz da execução do agente continua
- **WHEN** uma execução do agente começa numa linha de execução em segundo plano
- **THEN** o span raiz da execução continua sendo exportado normalmente

### Requirement: Query string fora da telemetria
Os spans HTTP de servidor e de cliente SHALL NOT conter a query string da URL. Cabeçalhos e corpos de requisição e de resposta SHALL NOT ser registrados.

#### Scenario: Retorno do login OIDC
- **WHEN** o provedor OIDC redireciona ao portal com `code` e `state` na query string
- **THEN** o span dessa requisição não contém a query string nem os valores de `code` e `state`

#### Scenario: Requisição com cabeçalho de autorização
- **WHEN** uma requisição com cabeçalho `Authorization` ou cookie de sessão é instrumentada
- **THEN** nenhum cabeçalho aparece nos atributos do span

### Requirement: Métricas de aplicação por OTLP
O portal e o broker SHALL exportar métricas de aplicação por OTLP quando um endpoint de métricas estiver configurado por variável de ambiente: duração e contagem de requisições HTTP, uso do pool de conexões do banco e uso de CPU e memória do processo. Sem esse endpoint, nenhuma métrica é exportada e nada muda no funcionamento.

#### Scenario: Endpoint de métricas configurado
- **WHEN** o endpoint de métricas está configurado e o portal atende requisições
- **THEN** métricas de duração de requisição HTTP, de pool do banco e de CPU e memória do processo chegam periodicamente ao Collector

#### Scenario: Endpoint de métricas ausente
- **WHEN** o endpoint de métricas não está configurado
- **THEN** o portal e o broker funcionam normalmente, sem tentar exportar métricas e sem erros relacionados

### Requirement: Identificação do serviço na telemetria
Todo traço, métrica e log exportado SHALL carregar o nome do serviço (portal ou broker), a versão da aplicação e um identificador da instância do processo. O ambiente de implantação e a versão SHALL poder ser definidos pela variável padrão `OTEL_RESOURCE_ATTRIBUTES`, que prevalece sobre os valores padrão.

#### Scenario: Portal e broker distinguíveis
- **WHEN** portal e broker exportam telemetria para o mesmo Collector
- **THEN** os dados de cada um chegam com nomes de serviço diferentes e com o identificador da instância que os emitiu

#### Scenario: Ambiente definido pelo operador
- **WHEN** o operador define `OTEL_RESOURCE_ATTRIBUTES=deployment.environment=producao,service.version=1.8.0`
- **THEN** a telemetria exportada carrega esse ambiente e essa versão, em vez da versão padrão do pacote

### Requirement: Collectors de exemplo recebem métricas
Os Collectors dos perfis de observabilidade de exemplo SHALL aceitar métricas OTLP e encaminhá-las ao backend do perfil: ao APM Server, no perfil Elastic, e a um alvo que o Prometheus raspa, no perfil Grafana.

#### Scenario: Perfil Elastic
- **WHEN** o perfil Elastic está de pé e o portal exporta métricas
- **THEN** as métricas do portal ficam disponíveis no Kibana, associadas ao serviço do portal

#### Scenario: Perfil Grafana
- **WHEN** o perfil Grafana e o Prometheus estão de pé e o portal exporta métricas
- **THEN** as métricas do portal ficam disponíveis para consulta no Prometheus

### Requirement: Destino Elastic configurável no perfil de exemplo
O Collector do perfil Elastic SHALL enviar ao APM Server do próprio compose por padrão, e SHALL aceitar, por variável de ambiente, o endereço de um APM Server externo, sem mudar o portal nem o broker.

#### Scenario: Elastic externo
- **WHEN** o operador define o endereço de um APM Server externo e sobe só o Collector do perfil Elastic
- **THEN** os traços, métricas e logs do portal e do broker chegam a esse APM Server externo

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

### Requirement: Cada app como um serviço a partir da borda
Com o tracing da borda ligado, cada pedido a `/apps/<slug>` SHALL produzir uma transação no serviço de nome igual ao slug da app, com método, status e duração. Isso SHALL valer em todos os modos de roteamento da instalação, a partir do caminho original do pedido, sem depender do nome dos routers.

#### Scenario: Pedido a uma app no Docker
- **WHEN** um usuário acessa `/apps/crm/clientes` numa instalação com o driver Docker
- **THEN** o APM mostra uma transação no serviço `crm`, com o método, o status e a duração do pedido

#### Scenario: Mesmo pedido no Kubernetes
- **WHEN** o mesmo pedido chega por uma instalação Kubernetes, no modo `ingressroute` ou no modo `gateway`
- **THEN** a transação também fica no serviço `crm`

#### Scenario: Pedido ao portal
- **WHEN** um pedido chega ao portal fora de `/apps/`
- **THEN** o span da borda continua no serviço do Traefik

#### Scenario: Mesmo nome das métricas de recursos
- **WHEN** a coleta de recursos dos Pods está ligada no Kubernetes
- **THEN** as transações da borda e as métricas de CPU e memória do Pod de uma app ficam no mesmo serviço

### Requirement: Nome de transação da app sem identificadores
O nome da transação de uma app SHALL ser o método seguido do caminho dentro da app, sem o prefixo `/apps/<slug>`. Segmentos numéricos ou com formato de identificador SHALL ser trocados por `{id}`.

#### Scenario: Caminho com identificador numérico
- **WHEN** um usuário acessa `GET /apps/crm/clientes/42`
- **THEN** a transação no serviço `crm` se chama `GET /clientes/{id}`

#### Scenario: Página inicial da app
- **WHEN** um usuário acessa `GET /apps/crm/`
- **THEN** a transação no serviço `crm` se chama `GET /`

### Requirement: Assets e websocket da interface fora da borda
Pedidos aos arquivos estáticos e à conexão em tempo real do NiceGUI, do portal ou das apps, SHALL NOT gerar spans da borda.

#### Scenario: Arquivo estático de uma app
- **WHEN** o navegador carrega `/apps/crm/_nicegui/3.18.0/static/app.js`
- **THEN** nenhum span da borda é exportado para esse pedido

#### Scenario: Websocket do portal
- **WHEN** o navegador mantém a conexão em tempo real do portal
- **THEN** nenhum span da borda é exportado para ela

### Requirement: Query string fora dos spans da borda
Os spans da borda SHALL NOT conter a query string, mesmo que a versão do Traefik não a mascare. A remoção SHALL acontecer no Collector, antes de exportar.

#### Scenario: Pedido com parâmetros
- **WHEN** um usuário acessa `/apps/crm/busca?cpf=12345678900`
- **THEN** nenhum span exportado contém `cpf=12345678900` nem um atributo de query string

### Requirement: Tracing da borda opcional no compose
No compose de desenvolvimento, o tracing do Traefik SHALL ser opcional e SHALL ficar desligado por padrão. Quando ligado, o Traefik SHALL mandar os traços ao Collector do perfil de observabilidade de pé.

#### Scenario: Padrão do compose
- **WHEN** o compose sobe sem a configuração de tracing da borda
- **THEN** o Traefik não tenta exportar traços

#### Scenario: Borda ligada
- **WHEN** o operador escolhe a configuração com tracing e um perfil de observabilidade está de pé
- **THEN** os pedidos às apps chegam ao backend do perfil como transações no serviço de cada app

### Requirement: Mesmo tratamento da borda nos Collectors
Os Collectors de exemplo do compose e o Collector do chart SHALL aplicar o mesmo tratamento aos spans da borda: filtro de assets, remoção da query string, nome da transação e serviço por app.

#### Scenario: Troca de backend
- **WHEN** o operador troca o perfil de observabilidade de Elastic para Grafana
- **THEN** cada app continua aparecendo como um serviço próprio, com os mesmos nomes de transação
