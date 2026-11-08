# 0024 — Proxy HTTP(S) de saída obrigatório por sistema, com allow-list por host

* Status: aceito
* Data: 2026-11-08
* Decidida em: change `agent-https-forward-proxy` (design D1–D8), fechando a parte cortada de escopo
  da etapa 5
* Estende: [ADR 0022](0022-confinamento-de-rede-por-porta-tcp-via-landlock.md) (Landlock por porta
  TCP) — usa o mesmo mecanismo, agora também em 443/80
* Relacionada: [ADR 0020](0020-broker-de-inferencia-com-litellm.md) (de onde vem a resolução
  broker-vs-provedor que este proxy só consome, nunca decide)

## Contexto

O ADR 0022 fechou o bypass dos proxies de banco e do broker, mas deixou 443 e 80 abertos por
decisão de escopo explícita: são a saída do agente para o provedor de LLM direto (quando o broker
da etapa 3 está desligado — hoje o padrão) e para `pip`/`npm`/`uv`. Esse canal nunca foi auditado
nem restrito — o agente confinado em `sandboxed` alcançava qualquer `host:443`/`host:80` na
internet, não só os que legitimamente precisava. Diferente do banco (etapa 4) e do broker (etapa
3), que já forçam a credencial por um proxy, 443/80 não forçavam nada.

## Decisão

Toda saída HTTP(S) do container do agente passa a atravessar um **proxy obrigatório por sistema**
(sidecar, `network_mode: container:<id>` — mesmo padrão do proxy de banco da etapa 4), que só libera
`CONNECT`/requisição HTTP para um destino (`host:porta`) numa **allow-list calculada por sistema**,
nunca por IP (evita DNS rebinding: a checagem usa o hostname que o cliente pediu, a resolução
acontece só na hora de abrir a conexão real). O proxy nunca decripta nem inspeciona TLS — é um relay
às cegas, validado por spike real contra um host HTTPS real (handshake TLS 1.3 completo passa
intacto pelo túnel).

A allow-list padrão de um sistema é: o host do provedor de LLM configurado (resolvido por um mapa
novo `provider_id -> host` para os nativos sem host documentado em lugar nenhum hoje, como
Anthropic) quando o broker está desligado, **ou** o host:porta do broker quando está ligado — nunca
os dois, porque o `ANTHROPIC_BASE_URL`/equivalente do agente só aponta pra um dos dois por vez (essa
decisão já é tomada na etapa 3; o proxy só relay cego pro que o cliente pedir, se estiver permitido)
— mais os registros de pacote usados pela plataforma, confirmados por spike real (`pip`/`npm`/`uv`
instalando um pacote comum tocam só `pypi.org`, `files.pythonhosted.org`, `registry.npmjs.org`,
nenhum CDN extra).

443 e 80 saem da lista estática de portas liberadas do perfil do agente (`agent_profiles.py`); só a
porta do novo proxy entra, calculada junto das já calculadas do proxy de banco e do broker. Validado
por teste real: aplicar o perfil escrito de um sistema via `apply_landlock_net` permite conectar na
porta do proxy e nega `PermissionError` pra qualquer host direto em 443.

**Dois controles por sistema, pedido do operador**: um toggle "internet habilitada" (default
ligado) — desligado, a allow-list do proxy fica vazia, sem afetar o broker (que nunca passou por
este proxy, é uma porta liberada à parte no Landlock); e um toggle "modo restrito" (default
desligado) — ligado, a allow-list do proxy vira **só** a lista de domínios cadastrada pelo editor
numa aba nova, substituindo por completo a allow-list padrão. A lista do modo restrito nasce
pré-populada com os registros de pacote mais usados (na criação do sistema e na primeira vez que o
modo restrito é ligado, idempotente), pra não quebrar `pip`/`npm` no primeiro uso sem aviso.

## Alternativas consideradas

- **MITM com CA própria no agente** para decidir roteamento por conteúdo — descartada: quebraria
  qualquer SDK com certificate pinning e adicionaria complexidade sem necessidade; a allow-list por
  host já resolve "só os destinos legítimos" sem precisar ver o conteúdo (D3).
- **O proxy decide broker-vs-provedor sozinho** — avaliada e descartada: pra HTTPS, o proxy só vê o
  `CONNECT host:porta` que o cliente pede, num túnel cego — não pode trocar o destino sem MITM. Essa
  decisão já é tomada antes (configuração do endpoint do agente, etapa 3); o proxy só valida contra
  a allow-list.
- **Lista do modo restrito se soma à padrão, em vez de substituir** — descartada por pedido explícito
  do operador: modo restrito é controle total, não um adicional.
- **Lista do modo restrito nasce vazia** — descartada: quebraria `pip`/`npm` no primeiro uso sem
  aviso nenhum.

## Consequências

- O único canal de saída HTTP(S) do agente passa a ser auditável e restrito por destino — fecha o
  único corte de escopo que a etapa 5 (ADR 0022) tinha deixado registrado.
- Ferramenta que ignora `HTTP_PROXY`/`HTTPS_PROXY` falha ao tentar conectar direto (fail-closed
  aceito, mesmo tratamento já previsto no roadmap original da etapa 5).
- Editor pode travar o próprio sistema sem querer (internet desabilitada sem broker ligado = sem LLM
  nenhum; modo restrito sem revisar a lista = pacote faltando) — aceito, mesma classe de risco de
  qualquer config que o editor controla; os erros do proxy saem claros, não como bloqueio silencioso.
- Refresh dos dois controles e da lista de domínios recria só o sidecar do proxy (leve, sem
  interromper sessão do agente) — diferente de trocar conexão de banco ou provedor, que ainda recria
  o container do sistema inteiro.
- Não resolve exfiltração **pelo prompt** — o endpoint do LLM é um destino legítimo e o agente pode
  mandar conteúdo do workspace por ele; limite já aceito como irredutível desde a etapa 5.
