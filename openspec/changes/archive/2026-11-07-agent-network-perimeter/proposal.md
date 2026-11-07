# Proposal

## Why

As etapas 3 e 4 colocaram a credencial de LLM atrás de um broker e a credencial de banco atrás de
um proxy de wire protocol, mas nenhuma das duas é a única rota disponível: o Landlock de filesystem
da etapa 2 não toca rede, então um agente confinado em `sandboxed` ainda alcança qualquer `host:porta`
na rede do container — inclusive o Postgres/MySQL real, direto, por fora do proxy da etapa 4, bastando
descobrir o endereço (DNS interno do Docker, ou um erro que vaze o host). Fechar essa rota com o
mesmo mecanismo já em produção (Landlock, auto-imposto, sem privilégio, sem eBPF/iptables) é a etapa
5 do roadmap de confinamento.

## What Changes

- **Landlock por porta TCP** (`LANDLOCK_ACCESS_NET_CONNECT_TCP`/`BIND_TCP`, ABI 4+) empilhado sobre
  o ruleset de filesystem já existente (mesma técnica: regras declaradas, `landlock_restrict_self`,
  irrevogável, herdado por toda a árvore de processos do agente) — validado por spike real: as regras
  valem em loopback, e um segundo `landlock_restrict_self` com `handled_access_net` não derruba o
  ruleset de filesystem já instalado pela etapa 2.
- **Lista de portas liberadas calculada por sistema**, não fixa no perfil estático: as portas
  `agent_port` de cada conexão Postgres/MySQL do manifesto do proxy de gate (etapa 4, dinâmicas —
  variam com o número de conexões do sistema), a porta do broker de inferência quando habilitado
  (etapa 3), e a porta do próprio harness (`bind`, para o `opencode serve` aceitar conexão).
- **Fora de escopo nesta change** (decisão de operação, não lacuna esquecida): a porta 443 continua
  aberta — acesso direto a provedor de LLM (quando o broker está desligado, hoje o padrão) e a
  registros de pacote (pip/npm/uv) seguem como estão. O roadmap também propõe negar 443 e forçar um
  proxy HTTP(S) para esse tráfego; isso exige construir uma peça de infraestrutura nova (proxy com
  CONNECT tunneling) e decidir o que fazer com a chamada direta ao provedor sem o broker — fica para
  uma change futura separada. Deixar 443 aberto não reabre o bypass que esta change fecha: nem o
  Postgres/MySQL real nem o broker escutam em 443, e a exfiltração via LLM por 443 já é um limite
  aceito no roadmap ("irredutível"), não algo que esta etapa prometia fechar.

## Capabilities

### Modified Capabilities

- `agent-sandbox`: ganha um requirement de confinamento de rede — o agente confinado em `sandboxed`
  só alcança as portas TCP explicitamente liberadas para o seu sistema (proxy de gate de banco +
  broker, quando aplicável), com qualquer outra porta negada pelo kernel antes de chegar à rede.

## Impact

- `base-image/afsupervisor/sandbox.py`: novo suporte a regras de rede do Landlock
  (`LANDLOCK_RULE_NET_PORT`, `LANDLOCK_ACCESS_NET_*`), aplicadas como uma segunda camada empilhada
  sobre a de filesystem já existente.
- `base-image/afsupervisor/supervisor.py`: `apply_sandbox` (chamado só para o processo do agente,
  nunca para o supervisor nem para a app gerada — mesmo desenho da etapa 2) passa a receber também
  as portas de rede do perfil.
- `portal/appaiforge/provisioning.py`: calcula a lista de portas por sistema (manifesto do proxy de
  gate + broker) e grava em `agent-profile.json`, ao lado de `readable_paths`/`writable_paths`.
- `openspec/specs/agent-sandbox/spec.md`: novo requirement de confinamento de rede.
- Testes: `@pytest.mark.sandbox` real (mesmo padrão da etapa 2) confirmando porta liberada conecta e
  porta não liberada é negada pelo kernel (não só recusada pela rede); integração real tentando
  conectar direto no Postgres do stack, por fora do proxy, de dentro de um sistema `sandboxed`.
