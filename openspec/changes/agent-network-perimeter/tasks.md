# Tasks

## 1. Landlock de rede (`sandbox.py`)

- [x] 1.1 Implementar `apply_landlock_net(connect_tcp_ports, bind_tcp_ports)` via ctypes (`LANDLOCK_RULE_NET_PORT`, `LANDLOCK_ACCESS_NET_BIND_TCP`/`CONNECT_TCP`), com `_net_access_bits(abi)` mascarando pelo ABI mínimo (4) no mesmo padrão de `_fs_access_bits`; listas vazias não instalam nenhuma regra (nenhuma porta liberada, mas também não falha)
- [x] 1.2 `apply_sandbox()` chama `apply_landlock` (filesystem, inalterado) e em seguida `apply_landlock_net` a partir das novas chaves do perfil; ABI abaixo de 4 pula a camada de rede com aviso em stderr, sem derrubar o boot do harness
  - revisão: testes existentes que chamam `apply_sandbox()` fora de um fork (`test_apply_sandbox_*`) tiveram que passar a mockar `apply_landlock_net` também — sem isso, rodariam o `landlock_restrict_self` de rede de verdade no próprio processo do pytest (ABI 8 neste host) e derrubariam a rede dele pro resto da sessão, de forma irrevogável.

## 2. Cálculo e entrega das portas por sistema

- [x] 2.1 `provisioning.py`: computar `connect_tcp_ports` (o `agent_port` — nunca `app_port` — de cada entrada do manifesto do proxy de gate, mais a porta de `inference_broker_url` quando `inference_broker_enabled`) e `bind_tcp_ports` (`harness_port`); gravar em `agent-profile.json` ao lado de `readable_paths`/`writable_paths`
- [x] 2.2 Perfil estático (`agent_profiles.py`) declara as portas sempre liberadas (443, 80, 53 — TLS/HTTP direto e DNS por TCP) combinadas com as dinâmicas na montagem do profile

## 3. Testes de aceitação

- [x] 3.1 `@pytest.mark.sandbox` real (mesmo padrão da etapa 2): porta liberada conecta; porta não liberada nega com `PermissionError` (não `ConnectionRefusedError` — prova que é o Landlock, não a ausência de um listener); `bind` numa porta não liberada nega; confinamento de filesystem da etapa 2 continua valendo depois da segunda camada
  - revisão: feita junto da task 1.1 como o próprio spike obrigatório virado teste (`test_apply_landlock_net_real_restringe_porta_tcp_sem_enfraquecer_fs`, `portal/tests/unit/test_sandbox.py`)
- [x] 3.2 Integração real: sistema `sandboxed` com conexão Postgres real cadastrada — de dentro do container, conectar no `agent_port` do proxy de gate funciona; conectar direto na porta real do Postgres (contornando o proxy) falha
  - revisão: `tests/integration/test_network_perimeter.py` — lê o `agent-profile.json` real escrito pelo provisionamento e aplica o `apply_landlock_net` de produção com ele dentro do container; a porta real do Postgres é alcançável na rede (mesmo gateway Docker do proxy) e mesmo assim negada, provando que é o Landlock barrando, não a rede

## 4. Documentação e decisão

- [x] 4.1 Registrar o ADR da etapa 5 (confinamento de rede por porta via Landlock), referenciando os ADRs 0019 (sandbox) e 0021 (gate no data plane) e o `Não resolve ainda` sobre a porta 443
- [x] 4.2 Atualizar a linha da etapa 5 no `docs/roadmap-confinamento-do-agente.md` com o status, os artefatos entregues e o corte de escopo (proxy HTTP(S) fica para uma change futura)
- [x] 4.3 `README.md`: seção "Segurança" ganha o confinamento de rede (portas liberadas por sistema, o que fica fora — 443/80/53)
