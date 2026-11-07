# Design

## Context

Etapa 2 (ADR 0019, change `agent-sandbox-seccomp-landlock`) já aplica Landlock de **filesystem** no
processo do agente, via `sandbox.apply_landlock()`, chamada de dentro do `preexec_fn` do
`afsupervisor` antes do `exec` do `opencode serve` — nunca no supervisor (PID 1), nunca na app
gerada. Landlock também cobre **porta TCP** (`LANDLOCK_ACCESS_NET_BIND_TCP`/`CONNECT_TCP`, ABI 4+;
o host de produção está em ABI 8) de forma agnóstica de endereço — a mesma regra vale para
`127.0.0.1:porta` e para `qualquer-host:porta`. É essa propriedade que fecha o bypass: o agente
pode descobrir o endereço real de um banco de produção (DNS interno do Docker, erro que vaze o
host), mas Landlock nega a porta antes de a tentativa de conexão sair do processo, não importa o
endereço.

## Goals / Non-Goals

**Goals:**
- O agente confinado em `sandboxed` só consegue abrir conexão TCP de saída para as portas do seu
  próprio proxy de gate de banco (uma por conexão cadastrada, dinâmico) e, quando aplicável, a porta
  do broker de inferência.
- O confinamento de rede empilha sobre o de filesystem já em produção sem alterá-lo.
- Sistemas `legacy`/`reduced` continuam exatamente como estão.

**Non-Goals:**
- Fechar a porta 443 (acesso direto a provedor de LLM e a registros de pacote) — decisão de escopo
  registrada no proposal.md, não lacuna esquecida.
- Confinar a app gerada — ela já roda sem nenhum Landlock (nem de filesystem) desde a etapa 2; esta
  change não muda isso.
- IPv6, UDP ou qualquer protocolo além de TCP — Landlock de rede só cobre TCP; DNS (UDP 53) e
  qualquer tráfego UDP não são afetados nem precisam de regra.

## Decisions

### D1 — Segunda camada de `landlock_restrict_self`, não um ruleset combinado

`apply_sandbox()` chama `apply_landlock()` (filesystem, inalterado) e, em seguida, uma nova
`apply_landlock_net()` — dois `landlock_create_ruleset`/`landlock_restrict_self` em sequência, não
um único ruleset com `handled_access_fs` e `handled_access_net` juntos. Landlock empilha restrições
(cada `restrict_self` intersecta com as já instaladas); duas chamadas simples preservam
`apply_landlock()` como está (usado isoladamente pelos testes existentes) e isolam o código de rede
num módulo novo, sem reescrever o que já está validado em produção.

**Verificado por spike real** (ABI 8, dentro de um container com a identidade `sandboxed` de
verdade — usuário não-root, `cap_drop: ALL`, `no-new-privileges`): uma porta de loopback liberada
conecta normalmente; uma porta não liberada nega com `PermissionError` (não
`ConnectionRefusedError` — confirma que é o Landlock barrando antes da pilha de rede, não a ausência
de um listener); um `bind` numa porta não liberada também nega. Empilhando a camada de rede por cima
da de filesystem já aplicada (mesmo perfil de produção, via `sandbox.apply_landlock()`): a regra de
filesystem (`/etc/passwd` negado, `/workspace` gravável) continua valendo exatamente igual depois do
segundo `restrict_self` — as duas camadas convivem sem uma enfraquecer a outra.

### D2 — Lista de portas calculada por sistema, entregue pelo mesmo canal do perfil

`provisioning.py` já calcula `db_connections_manifest(system.id)` (portas `agent_port`/`app_port`
por conexão, etapa 4) e já grava `readable_paths`/`writable_paths` em `agent-profile.json`
(`write_agent_profile`). A lista de portas de rede do agente (`connect_tcp_ports`) é computada no
mesmo lugar, a partir do mesmo manifesto — `agent_port` de cada entrada (nunca `app_port`: esse é da
app gerada, que não está confinada) — mais a porta do broker (`inference_broker_url`, só quando
`inference_broker_enabled`) — e entra no mesmo arquivo, lido pelo mesmo supervisor que já lê
`readable_paths`. Nenhum canal novo, nenhuma env var nova.

`bind_tcp_ports` fica só com `harness_port` (4096): o agente confinado nunca precisa abrir uma porta
de escuta além da do próprio `opencode serve` — a porta da app (8080) é aberta pelo processo da app
gerada, que corre fora do `preexec_fn` de confinamento (D4 do design da etapa 2, inalterado aqui).

### D3 — Minimo de ABI 4 verificado em runtime, degradação silenciosa e só nesse ponto

Direitos de rede do Landlock exigem ABI 4+; filesystem funciona a partir do ABI 1.
`decide_execution_mode()` (etapa 2) já exige `landlock_abi() > 0` para escolher `sandboxed` — um
host hipotético com ABI 1-3 teria filesystem confinado mas não rede. Em vez de recusar
`sandboxed` inteiro por causa disso (penalizaria o filesystem, que funciona), `apply_landlock_net()`
usa o mesmo padrão de `_fs_access_bits(abi)`: um `_net_access_bits(abi)` que devolve `0` abaixo do
ABI 4, e quem chama pula a camada de rede nesse caso (com aviso em stderr, mesmo canal de log do
supervisor) em vez de falhar o boot do harness. Não tem tratamento de fail-closed de produção
dedicado para esse sub-caso: o host de produção atual está em ABI 8, e o ganho de uma flag nova só
para uma combinação de kernel hoje inexistente no parque não paga o custo de manutenção.

### D4 — 443/80/53 sempre liberados, independente do broker

Fixo no perfil (não calculado por sistema): 443 e 80 (TLS/HTTP — provedor de LLM direto quando o
broker está desligado, `pip`/`npm`/`uv`) e 53 (DNS por TCP — fallback raro de respostas grandes; UDP
53 nunca passa por Landlock de rede de qualquer forma, TCP é defensivo). Ficam liberados
incondicionalmente, não só quando o broker está desligado: simplifica o perfil (sem ramificação por
config) e não reabre nada que o escopo desta change promete fechar — nem o Postgres/MySQL real nem
o broker escutam nessas portas.

## Risks / Trade-offs

- **Lista de portas errada tranca o próprio agente fora do seu banco**: se `db_connections_manifest`
  mudar de forma e a lista de portas sair diferente do que o sidecar realmente escuta, o agente
  (MCP, bash) perde acesso ao banco de verdade — fail-closed na direção errada. Mitigação: o teste de
  integração real (task de aceitação) cobre exatamente "conectar no `agent_port` do manifesto
  funciona" como parte do mesmo cenário que confirma "conectar na porta real do Postgres falha".
- **Adicionar uma nova origem de tráfego de saída no futuro** (nova integração, novo provedor) exige
  lembrar de abrir a porta aqui — mesmo custo de manutenção já aceito para `readable_paths` desde a
  etapa 2.
- **Host com ABI de Landlock entre 1 e 3**: ver D3 — degrada silenciosamente para só-filesystem,
  aceito por não existir no parque atual.
