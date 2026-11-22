# Spec Delta

## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Chart Helm instala um portal de produção

O chart Helm do portal SHALL aceitar como valores o papel da instalação, o endereço do portal visto pelo GitLab para o webhook e os parâmetros de implantação (intervalo da consulta periódica, prazo e intervalo das checagens de saúde), e SHALL passá-los ao portal como as configurações correspondentes. Com o papel padrão, o resultado SHALL ser o mesmo de antes desta versão, exceto pelo endereço interno do portal e pelo controlador de entrada (requisitos seguintes).

#### Scenario: Valores de produção chegam ao portal

- **WHEN** o chart é renderizado com papel de produção, endereço de webhook e intervalo de consulta definidos
- **THEN** o portal recebe o papel de produção, o endereço de webhook e o intervalo de consulta

#### Scenario: Instalação de desenvolvimento não muda

- **WHEN** o chart é renderizado com os valores padrão
- **THEN** o papel é desenvolvimento e o resultado é o mesmo da versão anterior do chart, exceto pelo endereço interno do portal com o nome completo do Service e pelo controlador de entrada

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
