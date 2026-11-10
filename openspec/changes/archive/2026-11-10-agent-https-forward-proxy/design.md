# Design

## Context

Ver `proposal.md` (Why) para a motivação. Estado atual verificado no código:

- `agent_profiles.py` libera `connect_tcp_ports: [443, 80, 53]` estaticamente no perfil `opencode`,
  somado em `provisioning.write_agent_profile` às portas calculadas por sistema (proxy de banco da
  etapa 4, broker da etapa 3 quando habilitado) — `provisioning.py:294-317`.
- O destino real de 443 varia com a configuração do sistema, não é um host fixo: com o broker
  desligado (`INFERENCE_BROKER_ENABLED=false`, hoje o padrão), o `ANTHROPIC_BASE_URL`/equivalente do
  agente aponta pro provedor de LLM nativo (`catalog.py` PRESETS: `openrouter`, `anthropic`,
  `openai`, `glm`/`zhipuai`) ou pro `base_url` de um provedor OpenAI-compatible cadastrado pelo
  admin; com o broker ligado, aponta pro broker (host:porta interno, etapa 3). Qual dos dois está em
  uso já é resolvido hoje, na configuração que `provisioning`/`write_opencode_config` geram — esta
  change não mexe nisso, só usa o resultado pra calcular o destino permitido no proxy.
- Nem todo provedor nativo tem o host hoje registrado em algum lugar do portal: `catalog._DEFAULT_MODELS_URL`
  só cobre `openrouter`/`openai` (usado pra listar modelos, não pra rede); `anthropic` nativo não
  aparece em lugar nenhum com host explícito — os modelos vêm hardcoded no preset (`catalog.py:24-26`),
  sem fetch de lista. `glm`/`zhipuai` sem `base_url` cai no `settings.glm_base_url`
  (`https://api.z.ai/...`, já configurado). Provedor OpenAI-compatible sempre tem `base_url` explícito.
- O proxy de banco da etapa 4 (`base-image/dbproxy/pg_proxy.py`/`mysql_proxy.py`) já estabelece o
  padrão de sidecar por sistema em Python asyncio, sem toolchain novo — este proxy segue a mesma
  convenção, mas fala HTTP (`CONNECT`), não um protocolo de banco.

## Goals / Non-Goals

**Goals:**
- Toda saída HTTP(S) do container do agente passa por um proxy que só libera `CONNECT`/requisição
  HTTP pra um destino (`host:porta`) numa lista calculada para aquele sistema.
- 443/80 saem da lista estática de portas liberadas do perfil `opencode`; só a porta do novo proxy
  entra, calculada junto das demais (banco, broker) em `provisioning.write_agent_profile`.
- A decisão "fala com o broker ou com o provedor direto" continua exatamente onde já está hoje
  (configuração do `ANTHROPIC_BASE_URL`/equivalente) — o proxy não decide isso, só relay cego pro
  destino que o cliente pediu, se estiver na allow-list.
- `pip`/`npm`/`uv` continuam funcionando atrás do proxy, via `HTTP_PROXY`/`HTTPS_PROXY`.
- O editor do sistema controla, por sistema: se o proxy libera saída externa nenhuma (toggle
  "internet habilitada") e se a allow-list vira só uma lista de domínios cadastrada por ele (toggle
  "modo restrito") — pedido do operador, ver D6/D7.

**Non-Goals:**
- MITM/inspeção de conteúdo HTTPS: o proxy nunca decripta TLS, só abre o túnel `CONNECT` cego. Ver
  decisão D3 e riscos.
- Fechar a exfiltração **pelo prompt** (mandar dado do workspace pro LLM pelo canal legítimo) —
  continua irredutível, mesmo limite já registrado na etapa 5.
- Proxy compartilhado entre sistemas — mesmo racional do D1 da etapa 4 (DSN/destino de loopback só
  existe dentro do netns de cada sistema).
- Resolver DNS pelo agente: com `HTTP_PROXY`/`HTTPS_PROXY`, é o proxy quem resolve o hostname do
  `CONNECT`, não o agente. A porta 53 TCP do perfil estático não muda nesta change (ver Open
  Questions).

## Decisions

### D1 — Sidecar por sistema, Python asyncio, convenção do proxy de banco

Mesmo padrão da etapa 4: container próprio por sistema, `network_mode: container:<id>`, porta de
loopback dedicada, Python asyncio na base-image. Protocolo bem mais simples que o wire protocol de
banco: a primeira linha de uma requisição HTTP absoluta (`GET http://host/path HTTP/1.1`) ou um
`CONNECT host:443 HTTP/1.1` — não precisa enquadrar mensagens binárias nem terminar autenticação de
cliente nenhuma (o proxy não é o destino, só o túnel).

### D2 — Allow-list **padrão** de `host:porta` calculada por sistema, nunca por IP

(Esta é a allow-list quando os dois toggles da D6/D7 estão nos valores padrão — internet habilitada,
modo restrito desligado. D6/D7 substituem o resultado desta decisão, não a complementam.)

A allow-list funciona por **hostname**, não IP — o `CONNECT` do cliente já carrega o hostname, e
resolver antes de comparar abriria brecha a DNS rebinding (o host resolve pra um IP permitido na
hora da checagem e pra outro na hora de conectar). Calculada em `provisioning.py`, mesmo lugar que já
calcula `connect_tcp_ports`:

- **Provedor de LLM**: quando o broker está desligado para o sistema, o host do provedor nativo
  configurado (`openrouter.ai`, `api.anthropic.com`, `api.openai.com`) de um mapa pequeno e novo
  (`provider_id -> host`, só hostnames públicos, não segredo nenhum) ou o host de `base_url` quando
  é `glm`/`zhipuai` (cai em `settings.glm_base_url`) ou um provedor OpenAI-compatible cadastrado.
  Quando o broker está ligado, não entra host de provedor nenhum — o cliente nem aponta pra lá.
- **Broker de inferência**: quando habilitado, o host:porta do broker (mesmo valor que já define
  `connect_tcp_ports` hoje via `_broker_connect_port`) — mutuamente exclusivo com a entrada acima,
  porque o `ANTHROPIC_BASE_URL` do agente só aponta pra um dos dois por vez.
- **Registros de pacote**: lista estática, igual para todo sistema — `pypi.org`, `files.pythonhosted.org`,
  `registry.npmjs.org`. Confirmado por spike (task 1.2, 2026-11-08): `pip install`, `npm install` e
  `uv pip install` de um pacote comum (`requests`, `left-pad`, `httpx`) atrás de um proxy-auditor que
  loga todo `CONNECT` tocaram **só** esses três hosts, nenhum CDN/mirror extra — `pip`/`npm`/`uv`
  resolvem tudo pelo registro principal pra esse caso comum. Não cobre instalação direto de git
  (`pip install git+https://...`), que tocaria `github.com`/`codeload.github.com` — fora do escopo
  medido; se aparecer em uso real, soma-se à lista (risco já registrado abaixo).
- Porta sempre 443 pros três grupos acima (HTTPS); porta 80 não entra na allow-list por padrão —
  nenhum dos destinos conhecidos precisa dela; reavaliar se um caso real aparecer.

### D3 — Relay cego por `host:porta`, nunca MITM

O proxy nunca decripta TLS. Pra `CONNECT`, ele resolve o host, confere contra a allow-list, abre uma
conexão TCP crua pro destino e relay dos bytes nos dois sentidos sem olhar o conteúdo — o handshake
TLS acontece fim-a-fim entre o cliente (SDK do LLM, `pip`, `npm`) e o destino real. Decriptar exigiria
instalar uma CA própria no container do agente e terminar TLS duas vezes, o que quebraria qualquer
SDK que faça certificate pinning e adicionaria complexidade sem necessidade: a allow-list por host já
resolve o problema que esta change propõe (saída só pros destinos legítimos), sem precisar ver o
conteúdo.

### D4 — `HTTP_PROXY`/`HTTPS_PROXY` no ambiente; sem variável por ferramenta

`provisioning.py` injeta `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` (vazio ou loopback) no ambiente do
container do sistema, apontando pro sidecar — convenção universal que `curl`, `pip`, `npm`, `uv` e o
SDK HTTP do opencode já respeitam por padrão. Ferramenta que ignora essas variáveis tenta conectar
direto em 443/80 e falha pelo Landlock (D5) — fail-closed aceito, mesmo tratamento já previsto no
texto original da etapa 5 no roadmap.

### D5 — 443/80 saem do perfil estático; só a porta do proxy entra

`agent_profiles.py` remove 443/80 de `connect_tcp_ports` do perfil `opencode`. `provisioning.write_agent_profile`
passa a somar a porta do novo sidecar à lista calculada por sistema, no mesmo ponto onde já soma a
porta do proxy de banco e do broker. Sem essa porta liberada, nem o proxy HTTP(S) seria alcançável —
o Landlock nega por padrão qualquer porta fora da lista calculada (ADR 0022).

### D6 — Toggle "internet habilitada": desligado, allow-list do proxy fica vazia

Campo booleano por sistema (`internet_enabled`, default `true` — preserva o comportamento padrão
desta change pra quem não mexer). Desligado, o proxy não calcula allow-list nenhuma — todo `CONNECT`/
requisição HTTP é recusado, qualquer destino. Isto **não** afeta o broker de inferência nem o proxy
de banco: nenhum dos dois passa por este proxy HTTP(S) — ambos são portas liberadas à parte no
Landlock (D5, e a etapa 4), alcançadas direto pelo cliente configurado pra isso. "Desligar a
internet" neste proxy é exatamente "não liberar nenhum destino externo", sem precisar de um caso
especial pro broker — ele já nunca esteve "na internet" do ponto de vista deste proxy.

#### Alternativas consideradas
- **Desligar também libera a porta do broker explicitamente, como caso especial** — descartada:
  redundante, o broker já não é alcançado por este proxy em nenhum estado do toggle.

### D7 — Toggle "modo restrito": allow-list vira só a lista de domínios cadastrada

Campo booleano por sistema (`restricted_network`, default `false`). Ligado, a allow-list do proxy
(D2) é **inteiramente substituída** pela lista de domínios cadastrados pelo editor para aquele
sistema (porta 443) — nem provedor de LLM, nem broker (isto é irrelevante, ver D6 — broker não passa
por aqui), nem registros de pacote padrão entram a menos que estejam na lista. `internet_enabled=false`
tem prioridade: se a internet está desligada, o modo restrito não importa, a allow-list continua
vazia.

**Lista pré-populada** (pedido do operador): ao ligar o modo restrito pela primeira vez — ou ao criar
o sistema, armazenada desde já — a lista de domínios vem com os registros de pacote mais usados já
cadastrados (mesma lista base da D2/tarefa de levantamento: PyPI, npm). O editor edita dali: remove o
que não quiser, adiciona o que precisar. Pré-popular evita que ligar o modo restrito quebre
`pip`/`npm` no primeiro uso sem avisar.

Nova tabela (`AllowedDomain` ou nome a definir): `system_id`, `domain`, auditoria básica (quem
cadastrou, quando) — mesmo padrão de outras configurações por sistema (`DbConnection`).

#### Alternativas consideradas
- **Lista do modo restrito se soma à allow-list padrão, em vez de substituir** — descartada por
  pedido explícito do operador ("vai liberar *somente* a lista") — modo restrito é pra quem quer
  controle total, não um adicional sobre o automático.
- **Lista nasce vazia, sem pré-popular** — descartada: quebraria `pip`/`npm` no primeiro uso do modo
  restrito sem nenhum aviso, pior experiência que começar com o que já é conhecido como necessário.

### D8 — Edição da lista de domínios: mesmo nível de acesso da aba Conexões

A aba nova de domínios (por sistema) segue o RBAC que a aba Conexões já usa — o editor do sistema
cadastra/edita/remove domínios do seu próprio sistema; não é uma política só de admin global, porque
a allow-list já é por sistema em toda esta change (D2, D6, D7) e não faria sentido esse uma peça
exigir um papel diferente das outras.

## Spike — relay `CONNECT` em asyncio (2026-11-08)

Proxy minimal (~50 linhas, só `CONNECT`, allow-list fixa de teste) validado contra um host HTTPS
real (`httpbin.org`):

- **Relay cego funciona ponta a ponta com TLS real**: `curl -x http://127.0.0.1:<porta> https://httpbin.org/get`
  completou o handshake TLS 1.3 inteiro (Client Hello, Server Hello, Certificate, Finished) com o
  certificado real de `httpbin.org` e ALPN `h2` — o proxy nunca viu nem precisou ver o conteúdo, só
  relayou os bytes crus nos dois sentidos depois do `200 Connection Established`. Resposta JSON
  íntegra confirmada do lado do cliente.
- **Recusa de destino fora da allow-list funciona e é limpa**: `CONNECT example.com:443` com
  `example.com` fora da allow-list de teste recebeu `403 Forbidden` do proxy, sem nenhuma tentativa
  de conexão com o destino real — confirmado pelo client (`curl: CONNECT tunnel failed, response 403`).
- **Framing do `CONNECT` é trivial**: primeira linha (`CONNECT host:porta HTTP/1.1`), consumir
  headers até a linha em branco, responder `200 Connection Established` e só então começar o relay —
  nenhuma surpresa de enquadramento como as do wire protocol de banco (etapa 4); não há pipelining
  nem mensagens binárias a decodificar.
- Confirma D1 (sidecar asyncio) e D3 (relay cego, nunca MITM) sem ajuste.

**Achado real na implementação (task 2.2)**: o primeiro relay fechava a conexão upstream inteira
(`writer.close()`) assim que o lado cliente→upstream esgotava (EOF), cortando a resposta que ainda
estava a caminho pela outra metade da mesma conexão TCP — pego por um teste com servidor de eco real
em loopback (`test_connect_permitido_faz_relay_cego_ate_o_destino`), não óbvio no spike manual
porque lá o round-trip local mascarava a corrida. Corrigido com *half-close* (`write_eof()`, não
`close()`) em cada pump isolado; o socket só fecha de verdade depois que as duas direções terminam.

## Achado real de teste de integração (2026-11-08) — corrida entre dois toggles

Teste de integração com Docker real (`test_https_proxy.py`) pegou uma corrida genuína: ligar dois
controles em sequência rápida (ex.: `internet_enabled=False` e, logo depois, `restricted_network=True`)
dispara duas threads de `_refresh_sidecar_async`, cada uma tentando recriar o **mesmo** nome de
container do sidecar ao mesmo tempo — uma removia o container que a outra tinha acabado de criar,
e a criação da segunda batia um `409 Conflict` do Docker. Corrigido com um lock por sistema
(`network_policy._sidecar_lock`) serializando o refresh: quem espera a vez sempre lê o estado mais
recente do sistema (não um snapshot de quando a thread foi disparada), então a fila nunca aplica um
resultado desatualizado — só evita as duas threads mexerem no Docker ao mesmo tempo.

## Risks / Trade-offs

- **Allow-list por hostname, não por IP**: correto contra DNS rebinding (D2), mas significa que o
  proxy resolve o host de novo na hora de conectar, não reaproveita a resolução feita na checagem —
  dois lookups por conexão, custo aceitável pro volume esperado (agente não abre uma taxa alta de
  conexões HTTP(S) novas).
- **Lista de registros de pacote incompleta na primeira versão**: `pip`/`npm`/`uv` podem tocar hosts
  além dos óbvios (mirrors, CDN de um pacote específico, `github.com` para instalação via git).
  Mitigação: medir em uso real antes de travar — mesmo padrão de rollout por modo sombra/enforcing já
  usado na etapa 4, aplicado aqui à allow-list de pacotes.
- **Provedor nativo sem host documentado em nenhum lugar hoje** (Anthropic): introduzir um mapa
  `provider_id -> host` novo, só com hostnames públicos — nenhum segredo, mas é conhecimento que
  precisa ficar certo e ser mantido se um provedor nativo novo for adicionado ao catálogo.
- **Fail-closed de ferramenta que ignora proxy env**: aceito (D4), mas pode gerar um erro confuso pra
  quem não sabe que a saída agora é forçada — vale uma mensagem clara na auditoria/logs do sidecar,
  não só um `ECONNREFUSED` genérico.
- **Não resolve exfiltração pelo prompt**: aceito e já registrado como limite irredutível na etapa 5.
- **Editor pode travar o próprio sistema sem querer**: desligar "internet habilitada" sem broker
  ligado deixa o sistema sem LLM nenhum (nem direto, nem broker — o broker só é alcançável se
  configurado à parte); ligar "modo restrito" sem revisar a lista pré-populada pode faltar um host
  que o sistema específico precisa. Mitigação: UI mostra o estado efetivo claramente (ex.: avisar se
  desligar a internet com o broker também desligado), e os erros do proxy recusando um destino saem
  claros nos logs/auditoria, não como falha silenciosa.

## Implementação (task 5.4) — reaproveita `provision_system`, sem mecanismo novo

`refresh_connections`/`set_provider` já chamam `provision_system`, que recria os dois sidecars (banco
e HTTP(S)) com config fresca a cada vez — incluindo a allow-list, recalculada do zero a cada chamada
de `network_policy.final_https_allowlist`. Os handlers da UI (4.4) e `services/network_policy.py`
só precisam chamar essa mesma função depois de mudar `internet_enabled`/`restricted_network`/a lista
de domínios — nenhum mecanismo de "recalcular e empurrar pro sidecar vivo" precisou ser construído.
Troca do provedor já reprovisiona (`_reprovision_async`); troca do broker é env var global do
processo do portal, se propaga na próxima vez que cada sistema for reprovisionado (mesmo padrão já
aceito pelo `db_gate_mode` da etapa 4).

## Migration Plan

Mesmo padrão da etapa 4/5: sidecar novo sobe junto do sistema no provisionamento; sistemas já
existentes pegam o sidecar e a allow-list na próxima reconciliação/reprovisionamento (não é uma
migração de dado, é infraestrutura recriada). Sem modo sombra necessário aqui — diferente do gate de
banco (que tinha falso-positivo de classificação de SQL a medir), a allow-list por host é
determinística a partir da configuração do sistema (provedor/broker), sem heurística a calibrar; se
a lista de pacotes faltar um host, aparece na hora como erro de instalação, não como um bloqueio
silencioso de produção.
