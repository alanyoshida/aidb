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

### D6 — Globs de SQL somem no enforcing; `reply_gate` fica (revisado na task 7.1)

Revisão da decisão original: `reply_gate` **não sai** do `HarnessPort`. Ele não é exclusivo do gate de SQL — é o mecanismo genérico com que o portal responde a *qualquer* `permission.asked` do opencode, inclusive tipos não-SQL (ex.: `external_directory`, acesso a diretório fora do workspace, com cobertura de teste própria). Removê-lo quebraria esse caminho, que esta change não toca.

O que de fato muda com o enforcing: `write_opencode_config` gera `permission.bash` sem os globs de SQL (só `"*": "allow"`) quando `APPAIFORGE_DB_GATE_MODE=enforce` — em sombra, os globs continuam (D5, cinto-e-suspensório). `gate.extract_sql` e a classificação de SQL em `_handle_gate_request` seguem existindo: são o que sustenta o caminho "antigo" da comparação do spike S5 (task 6.2) enquanto o sistema estiver em sombra; em enforcing eles ficam inertes (opencode nunca pergunta sobre bash SQL, então o branch nunca dispara), não precisam ser fisicamente removidos.

### D7 — Credenciais entregues ao sidecar no provisionamento

`provision_system` passa a criar o sidecar junto do container do sistema, com os segredos das conexões no env **do sidecar** (não do sistema). `refresh_connections` recria ambos — mesma reentrância que a reconciliação já garante. O MCP server recebe o DSN de loopback como argumento (sem senha), e `DATABASE_URL_<NOME>` idem.

## Risks / Trade-offs

- **Framing do wire protocol é onde moram os bugs sutis**: mensagens truncadas, pipelining de Parse/Bind/Execute, conexão segurada por minutos aguardando humano. Mitigação: spike de framing + modo sombra + testes de integração com clientes reais (`psql`, `asyncpg`, driver MySQL).
- ~~**Autenticação MySQL `caching_sha2_password`** exige troca RSA no primeiro auth — mais complexa que SCRAM. Se o spike mostrar custo alto, o enforcing inicial cobre Postgres e MySQL fica em sombra até destravar.~~ Fechado pelo spike MySQL: custo baixo, RSA-OAEP em Python puro funcionou de primeira — enforcing cobre os dois bancos juntos.
- **Query segurada por aprovação humana segura a conexão**: pool da app gerada pode esgotar se muitas statements confirmáveis penderem. Mitigação: timeout com erro claro + a app já tem o gate próprio (dbgate) como primeira linha.
- **Falso-positivo**: a heurística de WHERE restritivo já existe e é estável, mas o sombra existe exatamente para medir antes de bloquear (S5).
- **Superfície de rotação**: segredos agora vivem no sidecar — trocar credencial de conexão recria sidecar e sistema (reconciliação cobre; mesmo padrão do refresh atual).
- **Não resolve ainda**: quem descobrir o endereço real do banco contorna o proxy — fechado só na etapa 5 (Landlock por porta). Aceito e registrado no roadmap.

## Open Questions

- S5: quanto falso-positivo o modo sombra revela? Fecha com o período de comparação desta etapa.
- ~~S8~~ ✅ fechado (2026-11-07) — ver abaixo.

## Spike S8 — proxy Postgres em Python asyncio (2026-11-07, postgres:16-alpine)

Proxy minimal em stdlib puro (~250 linhas) validado contra Postgres real:

- **SCRAM-SHA-256 upstream funciona em Python puro** (hashlib/hmac/pbkdf2), com a assinatura do servidor verificada no `server-final`. Fallbacks md5 e cleartext implementados no mesmo caminho.
- **Framing**: os dois bugs clássicos apareceram no spike — o campo `length` inclui a si mesmo (ReadyForQuery com length 4 em vez de 5 corrompe o stream) e o auth code fica em `msg[5:9]`, não em `msg[1:5]` (que é o length). Ambos corrigidos; o parsing de startup params é pares `\x00`, não `k=v`.
- **SSLRequest/GSSENCRequest** respondidos com `N`: psql com `sslmode=prefer` aceita e segue em plaintext em loopback.
- **Injeção de credencial**: o cliente conecta com qualquer usuário e sem senha; o proxy sobrescreve `user` nos params do startup upstream (achado: sem isso, 28P01 — a auth usa o usuário do startup, não o do SCRAM).
- **Hold/release**: statement segurada 3s no handler de `Q` executou intacta após liberação (`DELETE 1`, 3.4s total) — mensagens pipelined esperam no buffer do reader sem corromper framing.
- **Extended protocol (asyncpg)**: `fetch` e `INSERT` com parâmetros `$1/$2` passam; o `Parse` carrega o texto SQL — a classificação de produção acontece no `Parse`, e o bloqueio ali exige descartar `Bind/Describe/Execute` até o `Sync` antes do `ReadyForQuery` (máquina de estado pequena). Detalhe: `asyncpg.execute()` sem parâmetros usa **simple query**, então os dois caminhos precisam de classificação.
- **ErrorResponse sintética** (`S`/`V`/`C`/`M`, SQLSTATE 42501) é aceita pelo psql (`ERROR: ...`) e mapeada pelo asyncpg para `InsufficientPrivilegeError`.

## Spike MySQL — proxy MySQL em Python asyncio (2026-11-07, mysql:8.4)

Proxy minimal (handshake de servidor fixo em `mysql_native_password`, auth upstream real) validado contra MySQL 8.4 real com dois usuários — `caching_sha2_password` (padrão do 8.4) e `mysql_native_password` (plugin explícito, exige `--mysql-native-password=ON` no servidor):

- **`caching_sha2_password` upstream funciona em Python puro**, nos dois caminhos: fast auth (hash já em cache no servidor, só compara scramble) e full auth (RSA-OAEP-SHA1 com a chave pública que o servidor manda sob pedido — implementado sem dependência nova, só `hashlib`/`pow`).
- **`mysql_native_password` upstream funciona** via `AuthSwitchRequest` (o handshake inicial anuncia o plugin default do servidor; se a conta usar outro, o servidor troca depois de ver o `user` na handshake response).
- **Bug de framing encontrado no `AuthSwitchRequest`**: o campo de scramble é `string<EOF>` (vai até o fim do pacote), mas o servidor manda 21 bytes em vez de 20 — um `\x00` extra depois do scramble real. Usar os 21 bytes no HMAC gera assinatura errada e o upstream recusa com `Access denied ... (using password: YES)`, mensagem enganosa (parece senha errada, é framing). Corrigido truncando para os 20 bytes esperados; confirmado contra o `scramble_native_password` do PyMySQL, que trunca da mesma forma (`message[:SCRAMBLE_LENGTH]`).
- **Hold/release em `COM_QUERY`**: `DELETE FROM t` segurado 3s no handler, liberado e executado intacto (`rowcount=1`, 3.0s round-trip) — mesmo padrão do Postgres, sem corromper o framing de sequência (`seq` do pacote precisa ser respeitado no relay).
- **`ErrorResponse` sintética** (`ERR` packet, errno 1142 `ER_TABLEACCESS_DENIED_ERROR`, SQLSTATE 42000) é aceita pelo cliente (PyMySQL mapeia para `OperationalError` com a mensagem do proxy) sem fechar a conexão — igual ao caminho Postgres.
- **`COM_STMT_PREPARE` (protocolo binário/estendido)** carrega o texto SQL (`DELETE FROM t WHERE id = ?`) e seu framing passa intacto pelo relay (testado com cliente raw, já que PyMySQL não implementa o protocolo binário): resposta `COM_STMT_PREPARE_OK` com `stmt_id`/contagem de params/colunas, seguida dos pacotes de definição — mesmo achado do Postgres `Parse`: a classificação de produção acontece no `PREPARE`, e `COM_STMT_EXECUTE` só referencia o `stmt_id` já classificado (sem SQL novo a inspecionar).

**Decisão sobre o risco registrado**: o custo do `caching_sha2_password` (RSA no primeiro auth) **não é alto** — a implementação em Python puro funcionou de primeira sem biblioteca nova. Risco das "Trade-offs" fechado: o enforcing desta etapa cobre MySQL junto com Postgres, sem precisar deixá-lo em sombra até destravar.
