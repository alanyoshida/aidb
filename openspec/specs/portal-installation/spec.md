# portal-installation Specification

## Purpose

Define como uma instalação do portal se identifica e se isola das outras, e como uma instalação de produção é empacotada para ser instalada fora da stack de testes.

## Requirements

### Requirement: Identidade da instalação fixada no primeiro boot

Cada instalação do portal SHALL ter um identificador próprio, gerado no primeiro boot e gravado no banco do portal. O identificador SHALL ser o mesmo em todos os boots seguintes da mesma instalação, e duas instalações com bancos diferentes SHALL ter identificadores diferentes.

#### Scenario: Primeiro boot grava o identificador

- **WHEN** o portal sobe pela primeira vez com um banco vazio
- **THEN** a instalação passa a ter um identificador gravado no banco

#### Scenario: Reinício mantém o identificador

- **GIVEN** uma instalação que já subiu uma vez
- **WHEN** o portal reinicia
- **THEN** o identificador da instalação é o mesmo de antes

#### Scenario: Banco de antes desta versão ganha identificador

- **GIVEN** um banco de uma versão anterior, sem identificador da instalação
- **WHEN** o portal sobe depois da atualização
- **THEN** a instalação passa a ter um identificador, e os sistemas e usuários existentes continuam como estavam

### Requirement: Containers identificados com a instalação

Sob o driver Docker, todo container que o portal cria para um sistema (o do sistema e os sidecars) SHALL carregar o identificador da instalação e o identificador do sistema.

#### Scenario: Container de sistema leva a instalação

- **WHEN** o portal provisiona um sistema sob o driver Docker
- **THEN** o container do sistema e os sidecars dele carregam o identificador desta instalação e o do sistema

### Requirement: Provisionamento não adota container de outro dono

Ao provisionar ou recriar um sistema, se já existir um container com o nome que o sistema usaria e esse container pertencer a outro sistema ou a outra instalação, o portal SHALL recusar o provisionamento, deixar o sistema em erro com o motivo e SHALL NOT remover, parar nem reaproveitar aquele container. Um container sem identificador de instalação (criado antes desta versão) SHALL ser tratado como deste portal só se o identificador de sistema dele for o do sistema em questão.

#### Scenario: Nome ocupado por container de outra instalação

- **GIVEN** um container com o nome do sistema "vendas", criado por outra instalação
- **WHEN** este portal provisiona o seu sistema "vendas"
- **THEN** o provisionamento é recusado, o sistema fica em erro explicando que o nome está em uso por outra instalação, e o outro container continua rodando

#### Scenario: Container antigo do próprio sistema

- **GIVEN** um container sem identificador de instalação cujo identificador de sistema é o do sistema "vendas" deste portal
- **WHEN** o portal recria o sistema "vendas"
- **THEN** o container é substituído normalmente e o novo leva o identificador desta instalação

### Requirement: Portal de produção exige host Docker próprio

Sob o driver Docker e com papel de produção, o portal SHALL recusar subir quando o host Docker tiver containers gerenciados de outra instalação: com outro identificador de instalação ou, sem identificador, com um identificador de sistema que não existe no banco deste portal. A mensagem SHALL listar os containers encontrados e pedir um host próprio. Um portal de desenvolvimento SHALL subir normalmente nesse caso.

#### Scenario: Produção num host com containers de homologação

- **GIVEN** um host Docker com containers de sistema criados por um portal de homologação
- **WHEN** um portal de produção sobe nesse host sem a exceção
- **THEN** o portal não sobe, e a mensagem lista os containers da outra instalação e pede um host próprio

#### Scenario: Produção num host só dela

- **GIVEN** um host Docker só com containers desta instalação
- **WHEN** o portal de produção sobe
- **THEN** o portal sobe normalmente

#### Scenario: Portal de desenvolvimento não é bloqueado

- **GIVEN** um host Docker com containers de outra instalação
- **WHEN** um portal de desenvolvimento sobe
- **THEN** o portal sobe normalmente

### Requirement: Exceção de host compartilhado só para testes

Uma configuração de exceção, documentada como só para testes e desligada por padrão, SHALL permitir que o portal de produção suba num host Docker com containers de outra instalação, registrando um aviso a cada subida.

#### Scenario: Exceção ligada na stack de testes

- **GIVEN** um host Docker com containers de outra instalação e a exceção ligada
- **WHEN** o portal de produção sobe
- **THEN** o portal sobe e registra um aviso de que o host é compartilhado

### Requirement: Chart Helm instala um portal de produção

O chart Helm do portal SHALL aceitar como valores o papel da instalação, o endereço do portal visto pelo GitLab para o webhook e os parâmetros de implantação (intervalo da consulta periódica, prazo e intervalo das checagens de saúde), e SHALL passá-los ao portal como as configurações correspondentes. Com o papel padrão, o resultado SHALL ser o mesmo de antes desta versão, exceto pelo endereço interno do portal e pelo controlador de entrada (requisitos seguintes).

#### Scenario: Valores de produção chegam ao portal

- **WHEN** o chart é renderizado com papel de produção, endereço de webhook e intervalo de consulta definidos
- **THEN** o portal recebe o papel de produção, o endereço de webhook e o intervalo de consulta

#### Scenario: Instalação de desenvolvimento não muda

- **WHEN** o chart é renderizado com os valores padrão
- **THEN** o papel é desenvolvimento e o resultado é o mesmo da versão anterior do chart, exceto pelo endereço interno do portal com o nome completo do Service e pelo controlador de entrada

### Requirement: Endereço interno do portal alcançável de outros namespaces

O chart SHALL passar ao portal um endereço interno com o nome completo do Service no cluster, para que o forwardAuth das rotas `/apps/<slug>`, chamado pelo Traefik a partir do namespace dele, alcance o portal.

#### Scenario: App de sistema pela rota do Traefik

- **GIVEN** um portal instalado pelo chart e um sistema provisionado pelo driver Kubernetes
- **WHEN** um usuário com sessão abre `/apps/<slug>` pela entrada do Traefik
- **THEN** a app responde, e sem sessão o usuário é mandado ao login

### Requirement: Migrações aplicadas antes de o portal subir no cluster

O chart SHALL oferecer, desligada por padrão, a aplicação das migrações do banco com a imagem do portal que vai subir, antes de o portal começar a atender. O exemplo de valores de produção SHALL deixá-la ligada.

#### Scenario: Instalação nova de produção

- **WHEN** o chart é instalado com os valores de produção num banco vazio
- **THEN** as migrações são aplicadas até a mais recente antes de o portal subir

#### Scenario: Atualização sem migração pendente

- **GIVEN** uma instalação com o banco na migração mais recente
- **WHEN** o chart é atualizado
- **THEN** a etapa de migração não muda nada e o portal sobe normalmente

### Requirement: Guardas do chart para produção

Com papel de produção, o chart SHALL recusar renderizar, explicando o motivo, quando o admin de demonstração estiver ligado ou quando os segredos não vierem de um Secret criado fora do Helm.

#### Scenario: Produção com admin de demonstração é recusada

- **WHEN** o chart é renderizado com papel de produção e o admin de demonstração ligado
- **THEN** a renderização falha explicando que produção não pode semear o admin de demonstração

#### Scenario: Produção sem Secret externo é recusada

- **WHEN** o chart é renderizado com papel de produção sem `secrets.existingSecret`
- **THEN** a renderização falha explicando que produção exige um Secret criado fora do Helm

### Requirement: Rota do próprio portal no chart

O chart SHALL oferecer, desligada por padrão, uma rota de entrada para o próprio portal, no modo de roteamento da instalação, com host configurável e TLS opcional, para que usuários e o webhook do GitLab alcancem o portal. No modo `ingressroute`, os entrypoints SHALL ser configuráveis; no modo `gateway`, a rota SHALL ficar ligada ao `Gateway` da instalação. Em qualquer modo, a rota SHALL NOT capturar o tráfego das rotas `/apps/{slug}` dos sistemas no mesmo host.

#### Scenario: Rota ligada

- **WHEN** o chart é renderizado com a rota do portal ligada, um host e o modo `ingressroute` (padrão)
- **THEN** existe uma rota daquele host para o serviço do portal, com prioridade menor que a das rotas de sistema

#### Scenario: Rota ligada no modo gateway

- **WHEN** o chart é renderizado com a rota do portal ligada, um host e o modo `gateway`
- **THEN** existe uma rota daquele host para o serviço do portal, ligada ao `Gateway` da instalação, e o portal recebe esse host para as rotas dos sistemas

#### Scenario: Rota ligada com TLS

- **WHEN** o chart é renderizado com a rota do portal ligada, um host e um Secret TLS, em qualquer um dos dois modos
- **THEN** aquele host é atendido por HTTPS com o certificado do Secret

#### Scenario: Rota ligada sem host é recusada

- **WHEN** o chart é renderizado com a rota do portal ligada e sem host
- **THEN** a renderização falha explicando que o host é obrigatório

#### Scenario: Rota desligada por padrão

- **WHEN** o chart é renderizado com os valores padrão
- **THEN** nenhuma rota para o próprio portal é criada

### Requirement: Compose do portal de produção

O projeto SHALL fornecer um arquivo compose para um portal de produção sob o driver Docker, com só o banco do portal, o Traefik e o portal, sem broker de inferência, LiteLLM, banco de demonstração ou observabilidade. Nele o papel SHALL ser produção, a chave secreta e a senha do banco SHALL ser obrigatórias (o compose recusa subir sem elas), o admin de demonstração SHALL estar desligado, e o endereço do webhook, o host público e a porta do Traefik SHALL ser configuráveis.

#### Scenario: Compose sobe um portal de produção

- **GIVEN** a chave secreta, a senha do banco e o admin de emergência definidos
- **WHEN** o compose de produção sobe
- **THEN** o portal responde na saúde, o papel é produção, criar sistema com agente é recusado e o admin de emergência consegue entrar

#### Scenario: Compose sem chave secreta não sobe

- **WHEN** o compose de produção sobe sem a chave secreta definida
- **THEN** o compose recusa subir explicando que a variável é obrigatória

### Requirement: Controlador de entrada instalado pelo chart por padrão
O chart Helm do portal SHALL instalar, por padrão, o controlador de entrada (Traefik), capaz de
atender os dois modos de roteamento, e, no modo `gateway`, um `Gateway` para as rotas do portal e
dos sistemas. Um valor do chart SHALL desligar essa instalação; no modo `gateway`, o chart SHALL
então ligar as rotas a um `Gateway` existente, informado nos valores.

#### Scenario: Valores padrão instalam o controlador sem Gateway
- **WHEN** o chart é renderizado com os valores padrão
- **THEN** o resultado inclui o controlador de entrada e nenhum `Gateway`

#### Scenario: Modo gateway com controlador cria o Gateway
- **WHEN** o chart é renderizado com o modo `gateway` e o controlador ligado
- **THEN** o resultado inclui um `Gateway` que aceita as rotas do portal e as rotas dos sistemas no
  namespace dos sistemas

#### Scenario: Modo gateway sem controlador usa Gateway existente
- **WHEN** o chart é renderizado com o modo `gateway`, o controlador desligado e o nome e o
  namespace de um `Gateway` existente
- **THEN** o resultado não inclui controlador nem `Gateway`, e as rotas do chart e as que o driver
  cria ficam ligadas ao `Gateway` informado

#### Scenario: Modo gateway sem controlador nem Gateway informado é recusado
- **WHEN** o chart é renderizado com o modo `gateway`, o controlador desligado e sem `Gateway`
  existente informado
- **THEN** a renderização falha explicando que é preciso informar o `Gateway` a usar

#### Scenario: Modo ingressroute sem controlador
- **WHEN** o chart é renderizado com o modo `ingressroute` e o controlador desligado
- **THEN** o resultado não inclui controlador nem `Gateway`, e nenhum `Gateway` existente é exigido

### Requirement: Modo de roteamento escolhido no chart
O chart SHALL aceitar o modo de roteamento da instalação, `ingressroute` (padrão) ou `gateway`, e
SHALL passá-lo ao portal. Um valor diferente desses SHALL fazer a renderização falhar com mensagem
que nomeie os modos aceitos.

#### Scenario: Modo padrão
- **WHEN** o chart é renderizado com os valores padrão
- **THEN** o portal recebe o modo de roteamento `ingressroute`

#### Scenario: Modo gateway escolhido
- **WHEN** o chart é renderizado com o modo de roteamento `gateway`
- **THEN** o portal recebe o modo de roteamento `gateway`

#### Scenario: Modo inválido
- **WHEN** o chart é renderizado com um modo de roteamento que não é `ingressroute` nem `gateway`
- **THEN** a renderização falha, e a mensagem diz quais modos são aceitos
