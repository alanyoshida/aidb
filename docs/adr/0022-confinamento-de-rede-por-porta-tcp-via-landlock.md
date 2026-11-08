# 0022 — Confinamento de rede por porta TCP via Landlock

* Status: aceito (o corte de escopo "443/80 continuam abertos" fechado pelo [ADR 0024](0024-proxy-http-s-de-saida-obrigatorio-por-sistema.md))
* Data: 2026-11-08
* Decidida em: change `agent-network-perimeter` (design D1–D4), etapa 5 do roadmap de confinamento
* Estende: [ADR 0019](0019-sandbox-seccomp-landlock-no-supervisor.md) (sandbox seccomp+Landlock)

## Contexto

O ADR 0019 confinou o agente por **filesystem**: Landlock nega qualquer caminho fora dos
`readable_paths`/`writable_paths` do perfil. Isso nunca tocou rede. O ADR 0020 (broker de
inferência) e a etapa 4 (gate de banco no data plane) colocaram credenciais atrás de proxies, mas
nenhum dos dois é a única rota: um agente confinado em `sandboxed` ainda alcança qualquer
`host:porta` da rede do container, inclusive o Postgres/MySQL real por fora do proxy de gate,
bastando descobrir o endereço (DNS interno do Docker, um erro que vaze o host). Fechar essa rota
com o mesmo mecanismo já em produção — sem eBPF, sem iptables, sem daemon privilegiado — é a
etapa 5.

## Decisão

O supervisor instala uma **segunda camada de Landlock**, de rede, empilhada por cima da de
filesystem já existente: `LANDLOCK_ACCESS_NET_CONNECT_TCP`/`BIND_TCP` (ABI 4+), que nega conexão
TCP de saída e escuta em qualquer porta fora de uma lista explícita, **agnóstica de endereço** — a
mesma regra vale para `127.0.0.1:porta` e para `host-real:porta`, e é essa propriedade que fecha o
bypass.

A lista de portas liberadas é **calculada por sistema**, não fixa no perfil: o `agent_port` de
cada conexão do manifesto do proxy de gate de banco (dinâmico — varia com o número de conexões do
sistema), a porta do broker de inferência quando habilitado, e a porta do próprio harness (para
escuta). Entra no mesmo `agent-profile.json` que já carrega `readable_paths`/`writable_paths`,
sem canal novo. Além dessas, 53 (DNS por TCP) fica **sempre** liberada. 443/80 (TLS/HTTP) também
ficavam sempre liberadas por decisão de escopo — **revertido pelo ADR 0024**: saíram da lista
estática, substituídas pela porta de um proxy HTTP(S) de saída obrigatório, com allow-list por
host calculada por sistema.

Validado por spike real antes de comprometer a abordagem (dentro de um container com a identidade
`sandboxed` de verdade): uma porta de loopback liberada conecta; uma não liberada nega com
`PermissionError`, não `ConnectionRefusedError` (prova que é o Landlock barrando antes da rede,
mesmo havendo um listener real nela); a camada de filesystem continua valendo exatamente igual
depois do segundo `landlock_restrict_self`.

## Alternativas consideradas

- **iptables/nftables no container** — exige `NET_ADMIN`, incompatível com `cap_drop: ALL` já em
  produção desde o ADR 0018; reintroduziria privilégio que o confinamento inteiro existe para
  evitar.
- **eBPF** — exige capability de kernel e carregamento privilegiado; fora do orçamento de
  complexidade do produto (mesma razão descartada nas etapas anteriores).
- **Negar 443 e forçar proxy HTTP(S) para pip/npm/LLM direto** — a leitura literal do roadmap
  também pedia isso. Descartada **desta** change: exige construir uma peça de infraestrutura nova
  (proxy com CONNECT tunneling) e decidir o que fazer com a chamada direta ao provedor sem o
  broker; virou a change futura separada prevista aqui — ver ADR 0024, que fecha exatamente isso.

## Consequências

- O agente confinado em `sandboxed` não alcança mais o Postgres/MySQL real por fora do proxy de
  gate, mesmo descobrindo o endereço — o bypass que as etapas 3/4 deixavam aberto fecha.
- Adicionar uma nova origem de tráfego de saída no futuro (nova integração, novo provedor atrás de
  porta própria) exige lembrar de abrir a porta no cálculo do perfil — mesmo custo de manutenção já
  aceito para `readable_paths` desde o ADR 0019.
- ~~Exfiltração via porta 443 (LLM, pacotes) continua possível~~ — fechado pelo ADR 0024 pro
  acesso direto a qualquer host; exfiltração **pelo prompt** (conteúdo do workspace mandado pro LLM
  pelo canal legítimo) continua irredutível, como o roadmap já registrava.
- A app gerada continua sem nenhum Landlock (nem filesystem, nem rede agora) — não muda com esta
  change; confiná-la teria valor de segurança questionável, já que o agente escreve o código dela.
- Hosts com ABI de Landlock entre 1 e 3 (filesystem funciona, rede não) degradam silenciosamente
  para só-filesystem — aceito por não existir no parque atual (produção está em ABI 8).
