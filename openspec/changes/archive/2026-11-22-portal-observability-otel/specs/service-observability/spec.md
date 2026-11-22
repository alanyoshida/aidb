# Spec Delta

## Purpose

Define o que o portal e o broker expõem a um APM: traços automáticos de requisições, banco e chamadas de saída, métricas de aplicação e a identificação de cada serviço, e o que fica de fora da telemetria (ruído e dados sensíveis).

## ADDED Requirements

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
