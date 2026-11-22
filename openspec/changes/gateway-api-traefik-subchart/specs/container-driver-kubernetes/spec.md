# Spec Delta

## ADDED Requirements

### Requirement: Modo de roteamento escolhido pela instalação
O driver Kubernetes SHALL publicar a rota `/apps/{slug}` de cada sistema no modo de roteamento
configurado para a instalação: `ingressroute`, o padrão, com os objetos de rota do Traefik usados
até esta versão, ou `gateway`, pela Gateway API. Um modo desconhecido SHALL impedir o portal de
subir, com mensagem que nomeie os modos aceitos.

#### Scenario: Modo padrão publica como antes
- **GIVEN** uma instalação sem modo de roteamento configurado
- **WHEN** um sistema é provisionado pelo driver Kubernetes
- **THEN** a rota do sistema é publicada com os mesmos objetos de rota do Traefik da versão
  anterior, e a app responde em `/apps/{slug}`

#### Scenario: Modo gateway publica pela Gateway API
- **GIVEN** uma instalação com o modo de roteamento `gateway`
- **WHEN** um sistema é provisionado pelo driver Kubernetes
- **THEN** a rota do sistema é publicada pela Gateway API, e a app responde em `/apps/{slug}`

#### Scenario: Modo desconhecido
- **WHEN** o portal sobe com um modo de roteamento que não é `ingressroute` nem `gateway`
- **THEN** o portal não sobe, e a mensagem diz quais modos são aceitos

### Requirement: Rota de sistema publicada pela Gateway API da instalação
No modo de roteamento `gateway`, o driver Kubernetes SHALL publicar a rota `/apps/{slug}` de cada
sistema como rota padrão da Gateway API, ligada ao `Gateway` configurado para a instalação, sem
usar objetos de rota próprios de um controlador de entrada. Só a etapa de autenticação da rota
SHALL poder referenciar uma extensão do controlador.

#### Scenario: Rota ligada ao Gateway da instalação
- **GIVEN** uma instalação com o modo de roteamento `gateway`
- **WHEN** um sistema é provisionado pelo driver Kubernetes
- **THEN** existe uma rota da Gateway API para `/apps/{slug}` ligada ao `Gateway` da instalação, e
  nenhum objeto de rota próprio do controlador de entrada é criado para o sistema

#### Scenario: Gateway existente informado na instalação
- **GIVEN** uma instalação com o modo de roteamento `gateway`, configurada para usar um `Gateway`
  que já existia no cluster
- **WHEN** um sistema é provisionado pelo driver Kubernetes
- **THEN** a rota do sistema fica ligada a esse `Gateway`, e a app responde em `/apps/{slug}`

### Requirement: Rota da app não capturada pela rota do portal
Em qualquer modo de roteamento, quando a rota do próprio portal estiver publicada num host, o
driver Kubernetes SHALL publicar a rota de cada sistema de modo que as requisições a
`/apps/{slug}` nesse host cheguem à app do sistema, e não ao portal.

#### Scenario: App e portal no mesmo host
- **GIVEN** a rota do portal publicada no host `aidb.exemplo.com`, em qualquer um dos dois modos
- **WHEN** um usuário com acesso ao sistema abre `aidb.exemplo.com/apps/{slug}`
- **THEN** quem responde é a app do sistema, e as demais páginas desse host continuam chegando ao
  portal

### Requirement: Autenticação da app preservada nos dois modos de roteamento
Em qualquer modo de roteamento, a rota de cada sistema SHALL manter o comportamento de acesso
definido pela capability `app-serving`: verificação da sessão em cada requisição, inclusive
WebSocket, retorno ao endereço pedido depois do login, e identidade injetada pelo portal, nunca a
enviada pelo cliente.

#### Scenario: Sem sessão, volta ao caminho pedido depois do login
- **WHEN** um usuário sem sessão abre `/apps/{slug}/relatorios` de um sistema provisionado pelo
  driver Kubernetes, em qualquer um dos dois modos
- **THEN** é levado ao login e, depois de entrar com acesso ao sistema, chega a
  `/apps/{slug}/relatorios`

#### Scenario: WebSocket da app passa pela verificação
- **WHEN** a app de um sistema provisionado pelo driver Kubernetes abre uma conexão WebSocket a
  partir de uma sessão com acesso ao sistema, em qualquer um dos dois modos
- **THEN** a conexão é estabelecida, e sem sessão válida ela é recusada

#### Scenario: Identidade forjada descartada
- **WHEN** um cliente envia a `/apps/{slug}` uma identidade forjada junto da requisição, em
  qualquer um dos dois modos
- **THEN** a app recebe só a identidade emitida pelo portal para aquela sessão

### Requirement: Troca de modo de roteamento sem reprovisionamento
Ao subir com um modo de roteamento diferente do usado na publicação anterior, o portal SHALL
republicar a rota de cada sistema ativo no modo novo e remover os objetos de rota do outro modo,
nos dois sentidos, sem exigir que o sistema seja reprovisionado nem reiniciar o Pod dele.

#### Scenario: De ingressroute para gateway
- **GIVEN** um sistema ativo publicado no modo `ingressroute`
- **WHEN** o portal sobe com o modo `gateway`
- **THEN** a app do sistema responde em `/apps/{slug}` pela rota da Gateway API, o Pod do sistema
  não é recriado, e os objetos do modo `ingressroute` deixam de existir

#### Scenario: De gateway de volta para ingressroute
- **GIVEN** um sistema ativo publicado no modo `gateway`
- **WHEN** o portal sobe com o modo `ingressroute`
- **THEN** a app do sistema responde em `/apps/{slug}` pelos objetos de rota do Traefik, o Pod do
  sistema não é recriado, e a rota da Gateway API do sistema deixa de existir

### Requirement: Remoção da rota apaga os objetos dos dois modos
Ao remover a rota de um sistema, o driver Kubernetes SHALL apagar os objetos de rota do sistema
dos dois modos de roteamento, tratando como sucesso a ausência de qualquer um deles.

#### Scenario: Sistema publicado num modo só é removido
- **GIVEN** um sistema cuja rota existe só no modo `ingressroute`
- **WHEN** a rota do sistema é removida, com qualquer modo configurado
- **THEN** os objetos de rota do sistema deixam de existir, e a ausência dos objetos do modo
  `gateway` não causa erro
