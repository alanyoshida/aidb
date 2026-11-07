# Design

## Context

Estado atual (verificado no código): o gate vive no control plane — `gate.evaluate()` classifica com o `sqlgate` canônico (sqlglot) e audita em `GateDecision`, mas o gatilho é o protocolo de permissão do harness (`reply_gate` em `harness/base.py`, `agent_queue.py`) e a extração de SQL é por regex sobre string de comando (`gate.extract_sql`). As credenciais das conexões entram no container do sistema em `DATABASE_URL_<NOME>` (`provisioning._connection_env`) e na **linha de comando** do MCP server (`provisioning.py:152`). A etapa 3 deixou o padrão de serviço pronto: broker compartilhado com token de serviço, endpoint interno no portal para contexto, compose com serviço adicional.

A etapa 4 move só o gatilho: classificador, decisão, UI de aprovação e auditoria ficam intactos. Dois fatos do roadmap são vinculantes: o agente recebe **DSN de loopback** e a etapa 5 torna o proxy inescapável com regras de **porta** do Landlock (`LANDLOCK_ACCESS_NET_CONNECT_TCP`) — ambos exigem o proxy no mesmo network namespace do container do sistema.

## Goals / Non-Goals

**Goals:**
- Toda conexão a banco cadastrado (Postgres/MySQL) passa por um proxy que classifica cada statement com o `sqlgate` canônico e aplica a decisão do gate.
- Credenciais reais das conexões fora do container do sistema (env e cmdline do MCP sem segredo).
- Atribuição de origem (agente vs app gerada) por listeners separados.
- Modo sombra (classifica e audita, não bloqueia) como passo obrigatório antes do enforcing, fechando o spike S5 com dados reais.
- Caso de aceitação: `psql -f arquivo.sql` com DELETE em massa — hoje passa pelos globs, no enforcing aguarda aprovação.

**Non-Goals:**
- BigQuery: HTTPS, caminho do broker da etapa 3.
- Tornar o proxy inescapável na rede: etapa 5 (Landlock por porta).
- TLS no wire protocol: os bancos alvo estão na rede interna sem TLS hoje; o proxy não muda isso.
- Protocolos além de texto classificável: COPY de dados binários e mensagens sem SQL não carregam statement a classificar.

## Decisions

### D1 — Sidecar por sistema, não serviço compartilhado

O proxy roda em container próprio **por sistema** com `network_mode: container:<id>`, escutando em portas de loopback (ex.: 15432 Postgres, 13306 MySQL). O roadmap da etapa 4 diz "no mesmo sidecar da etapa 3", mas a etapa 3 terminou com broker **compartilhado** — o que se herda é o conceito de sidecar, não a topologia. Três razões vinculantes:

1. **DSN de loopback** só existe dentro do netns do container do sistema — um proxy compartilhado exigiria DSN por host:porta e identidade viajando no startup packet (user/database), deixando a escolha da credencial ao cliente.
2. A etapa 5 restringe o egresso do agente **por porta** via Landlock — isso só funciona se o que ele pode alcançar em loopback for exatamente o proxy.
3. Landlock é por árvore de processos: o agente está confinado; o proxy, num container irmão, não — e precisa estar livre para alcançar o banco real.

**Descartada**: rodar o proxy como processo do `afsupervisor` dentro do container do sistema. Compartilharia o netns, mas acoplaria o ciclo de vida do gate ao supervisor (ADR 0003) e na etapa 8 (pod com sidecar) o mapeamento seria diferente do modelo já planejado.

### D2 — Python asyncio na base-image, sem dependência nova de toolchain

Proxy escrito em Python asyncio, convivendo com o `afsupervisor` na imagem dos sistemas. O wire protocol é simples de enquadrar: Postgres v3 — classificar no `Q` (simple query) e no `P` (Parse do protocolo estendido, que carrega o texto SQL); MySQL — `COM_QUERY` e `COM_STMT_PREPARE` (que carrega o texto; `COM_STMT_EXECUTE` referencia o id já classificado). **Descartado**: `pg-proto` (Rust) — introduziria toolchain novo no repo contra a convenção, e fica como upgrade path se o framing em Python mostrar custo.

A autenticação é **terminada no proxy**: o cliente conecta sem senha em loopback (o proxy aceita), e o proxy abre a conexão upstream com a credencial real (SCRAM-SHA-256/md5 no Postgres; `mysql_native_password`/`caching_sha2_password` no MySQL). É a parte mais pesada da implementação — mitigada pelo spike S8 (ver tasks) antes de comprometer o caminho.

### D3 — Decisão humana via portal, segurando a conexão

Statement confirmável: o proxy consulta o portal por HTTP interno com token de serviço (mesmo padrão do broker), o portal cria o pedido pendente associado ao **run/sessão ativos** (a serialização de um run por sistema dá a atribuição de graça, como na etapa 3), a UI de aprovação do chat decide, e o proxy libera a statement ou devolve erro de protocolo ao cliente. **Timeout de espera** com recusa segura: se o editor não decide, o cliente recebe erro (sem hang infinito de `psql` nem de pool da app).

### D4 — Dois listeners por sistema para atribuição de origem

O sidecar escuta duas portas por conexão: uma para o agente/MCP (origem `agente`), outra para a app gerada (origem `app`, via `DATABASE_URL_<NOME>`). O campo `origin` do `GateDecision` já existe — só passa a ser preenchido pelo listener, sem mudança de schema.

### D5 — Sombra por padrão, enforcing por flag, globs como cinto-e-suspensório

`APPAIFORGE_DB_GATE_MODE=shadow|enforce` (default `shadow`). Em sombra, os globs de `permission.bash` e o `reply_gate` continuam ativos — o sistema fica com **dois** gates e a comparação S5 mede o que cada um pega (falso-positivo e falso-negativo). O enforcing só vira padrão depois do período de comparação (decisão de operação, registrada no roadmap).

### D6 — `reply_gate` e `extract_sql` morrem com o enforcing

Com o gate no data plane, o `HarnessPort` perde `reply_gate` (o gate não depende mais do harness — requirement do spec reescrito) e `gate.extract_sql` (regex) deixa de ter chamador. A remoção entra nas tasks do enforcing, não na do sombra.

### D7 — Credenciais entregues ao sidecar no provisionamento

`provision_system` passa a criar o sidecar junto do container do sistema, com os segredos das conexões no env **do sidecar** (não do sistema). `refresh_connections` recria ambos — mesma reentrância que a reconciliação já garante. O MCP server recebe o DSN de loopback como argumento (sem senha), e `DATABASE_URL_<NOME>` idem.

## Risks / Trade-offs

- **Framing do wire protocol é onde moram os bugs sutis**: mensagens truncadas, pipelining de Parse/Bind/Execute, conexão segurada por minutos aguardando humano. Mitigação: spike de framing + modo sombra + testes de integração com clientes reais (`psql`, `asyncpg`, driver MySQL).
- **Autenticação MySQL `caching_sha2_password`** exige troca RSA no primeiro auth — mais complexa que SCRAM. Se o spike mostrar custo alto, o enforcing inicial cobre Postgres e MySQL fica em sombra até destravar (decisão registrada aqui, não cortada em silêncio).
- **Query segurada por aprovação humana segura a conexão**: pool da app gerada pode esgotar se muitas statements confirmáveis penderem. Mitigação: timeout com erro claro + a app já tem o gate próprio (dbgate) como primeira linha.
- **Falso-positivo**: a heurística de WHERE restritivo já existe e é estável, mas o sombra existe exatamente para medir antes de bloquear (S5).
- **Superfície de rotação**: segredos agora vivem no sidecar — trocar credencial de conexão recria sidecar e sistema (reconciliação cobre; mesmo padrão do refresh atual).
- **Não resolve ainda**: quem descobrir o endereço real do banco contorna o proxy — fechado só na etapa 5 (Landlock por porta). Aceito e registrado no roadmap.

## Open Questions

- S5: quanto falso-positivo o modo sombra revela? Fecha com o período de comparação desta etapa.
- S8 (novo, técnico): roundtrip completo do proxy Python — auth SCRAM + simple/extended query + segurar/liberar — contra Postgres real. Fecha antes de codar o caminho crítico.
