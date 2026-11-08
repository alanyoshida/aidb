# Proposal

## Why

O confinamento de rede da etapa 5 (`agent-sandbox`, ADR 0022) libera as portas 443 e 80 por decisão
de escopo: são a saída usada pelo agente para falar direto com o provedor de LLM (quando o broker da
etapa 3 está desligado — hoje o padrão) e para `pip`/`npm`/`uv`. Isso deixa um canal de saída aberto
e não auditável para qualquer host na internet — diferente do banco (etapa 4) e do broker (etapa 3),
que já forçam a credencial por um proxy, a 443/80 não força nada: o agente alcança qualquer
`host:443` ou `host:80`, não só os que ele legitimamente precisa. Esta change fecha esse canal: toda
saída HTTP(S) do agente passa a atravessar um proxy obrigatório, que só libera `CONNECT` para os
destinos calculados para aquele sistema — o mesmo padrão já usado pelo proxy de banco (etapa 4) e
pelas regras de porta do Landlock (etapa 5), aplicado agora a 443/80.

## What Changes

- **Sidecar de proxy HTTP(S) por sistema** (`https-proxy`, nome provisório): novo container por
  sistema, `network_mode: container:<id>` do sistema (mesmo padrão do `dbgate`), escutando em porta
  própria de loopback. Implementa `CONNECT` (HTTPS) e proxy HTTP simples (`GET`/`POST` absolutos),
  sem decriptar TLS — é um relay às cegas por `host:porta`, nunca um MITM.
- **Allow-list de destino calculada por sistema**, não estática: o host do provedor de LLM
  configurado para aquele sistema (resolvido o mesmo jeito que o `litellm_sync` já resolve — nativo
  tem host conhecido, customizado usa `base_url`) quando o broker está desligado, OU o host:porta do
  broker quando está ligado — nunca os dois ao mesmo tempo, já que o `ANTHROPIC_BASE_URL`/equivalente
  do agente já aponta pra um ou pra outro (etapa 3). Mais uma lista estática, igual para todo sistema,
  de hosts de registro de pacote (`pypi.org`, `files.pythonhosted.org`, `registry.npmjs.org` — a
  confirmar a lista completa no design).
- **443 e 80 saem da lista estática do perfil do agente**: só a porta do novo proxy entra no
  `connect_tcp_ports` calculado por sistema (`provisioning.write_agent_profile`), junto das portas
  já calculadas do proxy de banco e do broker. Nenhuma outra porta de saída HTTP(S) continua liberada.
- **`HTTP_PROXY`/`HTTPS_PROXY` forçadas no ambiente do container do sistema**, apontando pro
  loopback do novo sidecar — ferramenta que ignora essas variáveis simplesmente falha ao tentar
  conectar direto (443/80 negadas pelo Landlock): fail-closed aceitável, mesmo tratamento já previsto
  no roadmap original da etapa 5.
- **Dois controles por sistema, no editor** (pedido do operador, se somam à allow-list calculada
  acima): um toggle **"acesso à internet"** — desligado, a allow-list do proxy fica vazia (nenhum
  destino externo passa; o broker continua alcançável do mesmo jeito de sempre, porque ele nunca
  passou por este proxy — é uma porta liberada à parte no Landlock, não um `CONNECT` externo); e um
  toggle **"modo restrito"** — ligado, a allow-list do proxy vira **só** a lista de domínios
  cadastrada pelo editor numa aba nova do sistema, substituindo por completo a lista calculada
  (provedor/broker + registros de pacote). A lista de domínios do modo restrito vem **pré-populada**
  com os registros de pacote mais usados (PyPI, npm — mesma lista base da tarefa de levantamento),
  editável pelo editor do sistema a partir daí.
- **Fora de escopo**: decriptar e inspecionar o conteúdo HTTPS (seria MITM, quebra verificação de
  certificado de SDKs que fazem pinning); a exfiltração **pelo prompt** continua irredutível (o
  endpoint do LLM é um destino legítimo e o agente pode mandar conteúdo do workspace por ele) — essa
  change fecha o canal de saída pra qualquer host, não o que passa dentro do canal legítimo.

## Capabilities

### New Capabilities

- `https-forward-proxy`: sidecar por sistema que intercepta toda saída HTTP(S) do container do
  agente, libera `CONNECT`/proxy HTTP só para os destinos calculados para aquele sistema (provedor
  de LLM configurado, host:porta do broker quando habilitado, registros de pacote), e recusa
  qualquer outro destino sem nunca decriptar o tráfego. Inclui os dois controles por sistema (acesso
  à internet, modo restrito) e a lista de domínios customizada do modo restrito, editável pelo
  editor do sistema numa aba nova.

### Modified Capabilities

- `agent-sandbox`: o requirement *Confinamento de rede por porta TCP* deixa de liberar 443/80 na
  lista estática do perfil — a lista calculada por sistema passa a incluir só a porta do novo proxy
  (além das já calculadas de banco e broker), fechando o único canal de saída que a etapa 5 tinha
  deixado aberto por decisão de escopo.

## Impact

- **Base image**: novo processo do proxy HTTP(S) no sidecar (Python asyncio, mesma convenção do
  `dbproxy` da etapa 4 — sem toolchain novo).
- `portal/appaiforge/provisioning.py` — novo sidecar provisionado junto do sistema; cálculo do
  destino permitido (provedor de LLM ou broker) e da porta do proxy somada ao `connect_tcp_ports`;
  `HTTP_PROXY`/`HTTPS_PROXY` no ambiente do container do sistema.
- `portal/appaiforge/agent_profiles.py` — 443/80 saem de `connect_tcp_ports` estático do perfil
  `opencode`.
- `portal/appaiforge/services/litellm_sync.py` (ou módulo novo ao lado) — resolução do host real do
  provedor de LLM configurado, reaproveitada do que o `litellm_sync` já sabe pra configurar o
  LiteLLM, exposta pro cálculo da allow-list do proxy.
- `portal/appaiforge/models.py` — dois campos por sistema (`internet_enabled`, `restricted_network`,
  nomes a confirmar no design) e uma tabela nova para os domínios cadastrados do modo restrito.
- `portal/appaiforge/ui/system_detail.py` — aba nova para a lista de domínios, mesmo nível de acesso
  da aba Conexões (editor do sistema); os dois toggles na aba de Configurações existente.
- Specs: nova `https-forward-proxy`; delta em `agent-sandbox`.
- Testes: unitário do relay `CONNECT` (igual aos do `dbproxy`: framing, allow-list, recusa);
  integração com Docker real (conectar no provedor configurado funciona pelo proxy, conectar direto
  na 443 falha pelo Landlock; internet desligada recusa tudo externo mas o broker continua
  funcionando; modo restrito só libera os domínios cadastrados); verificação de que `pip`/`npm`
  continuam funcionando com a lista pré-populada do modo restrito.
