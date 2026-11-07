# Proposal

## Why

O gate de operações destrutivas hoje vive no **control plane do agente**: o portal intercepta os pedidos de permissão do harness (`reply_gate`) e extrai SQL de strings de comando por regex (`gate.extract_sql`). Isso só protege o que o agente declara — contornável sem malícia por `psql -f arquivo.sql`, heredoc, `python -c "import asyncpg; ..."` ou qualquer binário que fale o protocolo do banco. A etapa 4 do roadmap de confinamento move o gate para o **data plane**: um proxy de wire protocol (Postgres/MySQL) intercepta toda conexão a um banco cadastrado, classifica cada statement com o classificador canônico e segura statements confirmáveis até a aprovação no chat. Com o gatilho no protocolo, o gate passa a valer independente de **como** a SQL foi emitida e de **qual** agente está rodando — a etapa que destrava o multi-agente (etapa 7).

## What Changes

- **Sidecar de gate de banco por sistema** (`dbgate` proxy): novo container por sistema compartilhando o network namespace do container do agente, escutando em portas próprias de loopback. As credenciais reais das conexões saem do container do sistema e passam a viver só no sidecar, que as injeta na conexão upstream.
- **DSN sem senha no container**: `DATABASE_URL_<NOME>` e o DSN do MCP server passam a apontar para as portas do proxy em loopback, sem usuário/senha reais — nada a exfiltrar do env nem da linha de comando do MCP.
- **Gate no wire protocol**: o proxy classifica cada statement com o classificador canônico (`sqlgate`) — `normal` executa, `bloqueada` é recusada na hora (erro de protocolo ao cliente), `confirmável` é segurada até decisão do editor no chat. O `gate.evaluate()`, a UI de aprovação e a auditoria (`GateDecision`) ficam intactos; muda só o gatilho.
- **Atribuição de origem**: listeners separados (agente vs app gerada) mapeiam direto no campo `origin` que o `GateDecision` já tem.
- **Modo sombra primeiro**: o proxy nasce classificando e auditando sem bloquear nada; o modo enforcing vem atrás de flag e só vira padrão após o período de comparação com o gate atual (spike S5 — medir falso-positivo antes de bloquear).
- **`reply_gate` sai do `HarnessPort`** quando o enforcing estiver ativo: com o gate no data plane, o protocolo de permissão do harness deixa de ser fronteira de segurança (os globs de `permission.bash` ficam como cinto-e-suspensório até o fim do período de sombra).
- **BigQuery fora**: é HTTPS e vai pelo caminho HTTP do broker da etapa 3, não pelo wire proxy.

## Capabilities

### New Capabilities

- `db-gate-proxy`: sidecar por sistema que guarda as credenciais reais das conexões, recebe conexões de loopback sem senha do container do agente/app, classifica cada statement do wire protocol com o classificador canônico e aplica a decisão do gate (bloqueio, espera de aprovação humana ou passagem), com modo sombra e atribuição de origem.

### Modified Capabilities

- `destructive-gate`: o requirement *Gate do agente sobre SQL destrutivo* deixa de depender do protocolo de permissão do harness e passa a valer para toda conexão a um banco cadastrado — o gate funciona para qualquer agente, inclusive um sem protocolo de permissão.

## Impact

- **Base image**: novo processo do proxy no sidecar (Python asyncio, coerente com o `afsupervisor`), falando wire protocol Postgres (`Q`/`P`) e MySQL (`COM_QUERY`).
- `portal/appaiforge/provisioning.py` — criação do sidecar por sistema, `DATABASE_URL_<NOME>` e args do MCP apontando para loopback, segredos fora do env do container do sistema.
- `portal/appaiforge/harness/base.py` e `harness/opencode.py` — remoção do `reply_gate` quando o enforcing estiver ativo.
- `portal/appaiforge/gate.py` — ganha o caminho de decisão vinda do proxy (mesma função de classificação/auditoria); `gate.extract_sql` (regex) morre com o enforcing.
- `portal/appaiforge/services/connections.py` — segredos das conexões entregues ao sidecar, não mais ao container do sistema.
- Specs: reescrita do requirement em `destructive-gate`; nova `db-gate-proxy`.
- ADR 0021 (roadmap): gate no data plane, com a interceptação no control plane como decisão substituída (ADR 0017 parcialmente revisto).
- Testes: aceitação com um caso que hoje passa pelos globs (`psql -f arquivo.sql` com DELETE em massa) e que no modo enforcing é bloqueado; modo sombra comprovando que tudo passa e é auditado.
- Spike S5 aberto (falso-positivo do modo sombra) fecha dentro desta etapa, antes de ligar o enforcing por padrão.
