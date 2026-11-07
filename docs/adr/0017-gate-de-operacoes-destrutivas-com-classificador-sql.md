# 0017 — Gate de operações destrutivas com classificador SQL único

* Status: aceito (gatilho do agente substituído por [0021](0021-gate-de-sql-no-data-plane-via-sidecar-proxy.md); classificador, classes e auditoria continuam)
* Data: 2026-11-02
* Decidida em: change `destructive-op-gate` (design D1–D5)
* Substitui parcialmente: [0015](0015-mesma-credencial-de-producao-para-app-gerada.md) (a parte "sem gate")

## Contexto

As apps geradas escrevem em bancos de produção com a credencial da conexão (ADR 0015) e o agente também alcança esses bancos. Nada impedia um `DELETE` sem `WHERE`, um `TRUNCATE` ou um `DROP` pedido por engano ao agente ou disparado por um bug da app. O ADR 0015 aceitou o risco e adiou o gate para uma change seguinte.

## Decisão

Toda SQL que toca os bancos das conexões é classificada por **um único classificador baseado em sqlglot** (`sqlgate.py`), com três classes:

| Classe | Critério | Comportamento |
|---|---|---|
| **normal** | DML escopado por chave | executa sem atrito |
| **confirmável** | `DELETE`/`UPDATE` sem `WHERE`, tautológico ou sem condição por linha | exige confirmação explícita |
| **bloqueada** | qualquer DDL (`DROP`, `TRUNCATE`, `ALTER`, `CREATE`, `GRANT`, `REVOKE`) | sempre recusada |

Em múltiplas statements numa só string vale a pior classe. O módulo canônico é `portal/appaiforge/app_template/sqlgate.py`: o portal o importa e o `materialize` o copia para o workspace de cada app (um teste em `test_agent_pipeline.py` garante que a cópia é idêntica). O MCP roda na imagem base, fora do alcance do código do portal, e por isso tem uma segunda cópia manual em `base-image/gated-mcp/sqlgate.py`, e um teste em `test_sqlgate.py` garante que ela é idêntica à canônica.

- **Agente**: o `opencode.json` pede permissão (`ask`) para comandos bash que executam SQL. O portal recebe o evento `permission.asked`, classifica e responde: bloqueada é recusada na hora, confirmável fica pendente com botões Aprovar/Recusar no chat, normal é aprovada automaticamente. O run ganha o estado "aguardando aprovação".
- **MCP**: o permissionamento do opencode não cobre ferramentas MCP, então o MCP genérico é trocado por um servidor próprio, o `gated-mcp`, somente leitura (`list_tables`, `describe_table`, `read_query`). Escritas via MCP são sempre recusadas; a via de escrita do agente é o bash, que passa pelo fluxo de permissões.
- **App gerada**: a camada `dbgate.py` é obrigatória nas guidelines; operação confirmável dispara diálogo com a contagem estimada de linhas, e DDL levanta erro.
- **Auditoria**: toda decisão (aprovada, recusada, bloqueada) é gravada em `gate_decisions` e exibida na página do sistema.
- **Aprovação**: o editor que conduz a sessão aprova sozinho (coerente com o ADR 0014). Não há expiração automática; interromper o run recusa o pedido pendente.

## Alternativas consideradas

- **Regex sobre o texto SQL** — falha com CTEs, comentários e subqueries.
- **Classificar no banco via `EXPLAIN`** — não cobre DDL e não impede a execução.
- **Orientar o agente por guidelines ("consulte antes")** — política por prompt, não enforcement.
- **Credencial restrita por schema/tabela para a app** — continua recomendada, mas é uma change própria e não substitui o gate.

## Consequências

- O risco do ADR 0015 deixa de ser irrestrito, mas não desaparece: o gate depende do classificador (falsos negativos são possíveis) e a credencial continua com escrita.
- Apps geradas antes do gate só passam a usá-lo quando o agente as edita de novo.
- O gate é provisionado para as conexões Postgres e MySQL; outros tipos acompanham o suporte do classificador.
- Alterar o classificador exige copiar o arquivo para `base-image/gated-mcp/` (o teste falha se esquecer) e reconstruir a imagem base.
- Mudar as regras de fronteira (por exemplo `INSERT ... SELECT` sem `WHERE`) é mudança de código revisada por teste, não de configuração.
