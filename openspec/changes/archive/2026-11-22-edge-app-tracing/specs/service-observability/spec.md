# Spec Delta

## ADDED Requirements

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
