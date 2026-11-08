# 0021 — Gate de SQL no data plane via sidecar proxy de wire protocol

* Status: aceito (D3 — hold/aprovação de `confirmável` — substituída por [0023](0023-confirmavel-recusado-direto-sem-pedir-aprovacao.md); D1/D2/D4–D7 continuam)
* Data: 2026-11-07
* Decidida em: change `db-proxy-gate-data-plane` (design D1–D7, etapa 4 do roadmap de confinamento)
* Substitui parcialmente: [0017](0017-gate-de-operacoes-destrutivas-com-classificador-sql.md) — só o **gatilho** do
  gate do agente (interceptação por permissão de bash no control plane); o classificador, as classes
  normal/confirmável/bloqueada, a auditoria em `GateDecision` e o MCP somente-leitura continuam

## Contexto

O ADR 0017 colocou o gate no **control plane**: o `opencode.json` pede permissão (`ask`) para
padrões de bash que parecem SQL, o portal recebe `permission.asked`, classifica com o `sqlgate`
canônico e decide. Isso cobre o agente, mas tem três lacunas estruturais, não corrigíveis por mais
regex: a extração de SQL por regex sobre string de comando (`gate.extract_sql`) tem falso-negativo
estrutural (SQL multi-linha, heredoc, escaping); a app gerada nunca passou por aqui (depende da
camada própria `dbgate.py`, sem imposição externa); e a credencial real da conexão continua visível
no ambiente/cmdline do container do sistema (`DATABASE_URL_<NOME>`, argumento do MCP).

A etapa 3 (broker de inferência, ADR 0020) deixou o padrão de sidecar com token de serviço pronto.
Dois fatos do roadmap são vinculantes para a etapa 4: o agente deve receber um **DSN de loopback**, e
a etapa 5 (Landlock por porta) exige que o único destino alcançável em loopback seja o proxy — ambos
só funcionam com o gate no mesmo network namespace do container do sistema.

## Decisão

O gate de SQL destrutivo passa a viver no **data plane**: um sidecar por sistema
(`network_mode: container:<id>` do sistema, D1) implementa o protocolo de fio do Postgres e do MySQL
em Python asyncio (D2), terminando a autenticação do cliente (trust em loopback) e abrindo a conexão
upstream com a credencial real (SCRAM-SHA-256/md5/cleartext no Postgres; `mysql_native_password`/
`caching_sha2_password` no MySQL). Toda statement (`Q`/`Parse` no Postgres; `COM_QUERY`/
`COM_STMT_PREPARE` no MySQL) é classificada com o **mesmo** classificador canônico do ADR 0017
antes de repassar ao banco real — `bloqueada` nunca chega ao upstream, `confirmável` segura a
conexão e consulta o portal (D3, mesmo padrão de token de serviço do broker; **revisado pelo ADR
0023** — em enforce, `confirmável` passa a ser recusada direto, igual a `bloqueada`, sem segurar
nem consultar ninguém), `normal` passa direto.

Dois listeners por conexão (porta do agente, porta da app gerada) atribuem a origem sem mudança de
schema — o campo `origin` do `GateDecision` já existia (D4). As credenciais reais só existem no env
do sidecar; o container do sistema recebe DSNs de loopback sem usuário/senha, tanto no
`DATABASE_URL_<NOME>` da app quanto no argumento do MCP (D7).

Rollout por flag: `APPAIFORGE_DB_GATE_MODE=shadow` (default) classifica e audita sem bloquear nada —
os globs de `permission.bash` do ADR 0017 continuam ativos como gate de verdade, e a change
`gate_comparison.py`/CLI `compare-gate-decisions` mede concordância/discordância entre os dois
caminhos (spike S5) antes de qualquer decisão de trocar o default. Em `enforce`, os globs de SQL
somem do `permission.bash` (só `"*": "allow"`) e o sidecar passa a ser o gate de verdade; `reply_gate`
e `gate.extract_sql` continuam existindo nos dois modos — não são exclusivos do gate de SQL
(`reply_gate` responde a qualquer `permission.asked`, inclusive não-SQL) e ficam inertes em enforce
em vez de removidos (D6).

## Alternativas consideradas

- **Proxy compartilhado entre sistemas** (a leitura literal do roadmap, "no mesmo sidecar da etapa
  3") — descartada: DSN de loopback só existe dentro do netns de cada sistema, e um proxy
  compartilhado exigiria a identidade viajar no DSN (host:porta + user/database), devolvendo ao
  cliente a escolha da credencial — exatamente o que o D7 fecha.
- **Proxy como processo do `afsupervisor`** dentro do container do sistema — compartilharia o netns,
  mas acoplaria o ciclo de vida do gate ao supervisor (ADR 0003) e divergiria do modelo de pod com
  sidecar já planejado para a etapa 8.
- **`pg-proto` em Rust** — introduziria toolchain nova no repo contra a convenção; fica como upgrade
  path se o framing em Python (validado nos spikes S8/MySQL) mostrar custo em produção.
- **Enforcing direto, sem período de sombra** — descartada: falso-positivo da heurística de WHERE
  precisa ser medido com uso real antes de travar statements de verdade (spike S5, tasks 6.2/7.3).

## Consequências

- O gate deixa de depender de reconhecer SQL dentro de texto de bash — passa a inspecionar o
  protocolo real, cobrindo também a app gerada (antes só a camada própria `dbgate.py` fazia isso) e
  qualquer ferramenta que fale o protocolo, não só `psql`.
- Credencial real das conexões sai do container do sistema; só o sidecar a guarda. Rotação de
  credencial agora recria sidecar e sistema (reconciliação cobre, mesmo padrão do refresh atual).
- Modo sombra mantém dois gates simultâneos (globs do ADR 0017 + proxy) até o spike S5 mostrar
  falso-positivo aceitável — custo de manutenção temporário, aceito para rollout seguro (tasks 6.2/7.3
  seguem em aberto, dependem de uso real, não de mais código).
- O proxy ainda é contornável por quem descobrir o endereço real do banco — fechado só na etapa 5
  (Landlock por porta). Aceito e registrado no roadmap, igual ao design.
- BigQuery (HTTPS) não passa pelo proxy — segue pelo broker da etapa 3, fora do escopo deste ADR.
