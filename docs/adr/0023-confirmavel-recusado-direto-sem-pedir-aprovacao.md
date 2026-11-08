# 0023 — Statement confirmável recusada direto em enforce, sem pedir aprovação

* Status: aceito
* Data: 2026-11-07
* Decidida em: change `db-proxy-gate-data-plane` (revisão de D3), achado ao vivo em uso real
* Substitui parcialmente: [0021](0021-gate-de-sql-no-data-plane-via-sidecar-proxy.md) — só a
  decisão D3 (hold + aprovação humana para `confirmável`); o restante (sidecar por sistema,
  classificador canônico, dois listeners por origem, modos sombra/enforce) continua

## Contexto

O ADR 0021 (D3) decidiu que uma statement `confirmável` (`DELETE`/`UPDATE` sem `WHERE` restritivo)
seguraria a conexão e pediria decisão humana no chat — o mesmo tratamento que o gate antigo do
control plane (ADR 0017) já dava. Em uso real (`homolog-crm`, 2026-11-07), o agente pediu
confirmação de um `DELETE FROM dono` pela ferramenta nativa `question` do próprio opencode — um
mecanismo do modelo, sem relação com o gate — e, separadamente, o proxy segurou a mesma statement e
criou o card de aprovação do data plane. Alguém aprovou esse card (rotina de quem está testando o
enforce), a statement foi liberada e falhou só por uma FK real do schema — não pelo gate.

O problema: o card de aprovação do proxy ("pede aprovação para uma operação destrutiva") não
distingue uma statement perigosa de uma rotineira — é texto genérico com o SQL embaixo. Quem aprova
por hábito (o mesmo padrão que faz sentido para os pedidos de permissão não-SQL do agente, ex.:
acesso a diretório) aprova também um `DELETE` sem `WHERE` disfarçado em meio a uma sessão normal.
Diferente de uma DDL (sempre recusada, sem decisão de ninguém), o `confirmável` era o único caso em
que uma operação de fato destrutiva dependia de um clique correto sob pressão de rotina.

## Decisão

Em `APPAIFORGE_DB_GATE_MODE=enforce`, `confirmável` passa a ter o **mesmo tratamento de
`bloqueada`**: o proxy recusa a statement na hora, sem segurar a conexão, consultar o portal ou
esperar decisão de ninguém — exatamente como já acontecia com DDL. O cliente recebe o erro de
protocolo de volta (`DELETE sem WHERE afeta a tabela inteira`, mesmo texto que já existia como
motivo da classificação) e, se houver uma run ativa do agente, o chat mostra a notificação de
bloqueio (`gate_denied`, mecanismo que já existia só para `bloqueada`) com a query e o motivo à
mostra — correção do achado de que o bloqueio de DDL aparecia no chat, mas a recusa de um
`confirmável` segurado não deixava rastro nenhum na conversa, só na auditoria.

A classificação em si não muda: `confirmável` continua uma classe distinta de `bloqueada` na
auditoria (`classification=confirmavel, decision=bloqueada`) — a diferença fica só no **motivo**
exibido (sem WHERE restritivo vs. DDL), não no tratamento. Em `shadow`, nada muda: a statement
continua passando normalmente, só auditada.

Toda a infraestrutura de pedido pendente construída para D3 (tabela `gate_requests` como fila de
pendências, `create_request`/`get_request`/decide_request`/`list_pending_for_run`, os dois
endpoints internos correspondentes, o cliente HTTP de hold do proxy — `request_approval`/
`wait_decision`/`decide_confirmable` — e o card "proxy de banco" no chat) foi removida: nada mais a
cria, e manter o código vivo sem nenhum caminho que o chame seria complexidade sem uso. A tabela
`gate_requests` em si fica no banco, inerte, com o histórico anterior — dropá-la exigiria migração
sem nenhum ganho.

## Alternativas consideradas

- **Manter o hold, mas com um card mais específico** (ex.: destacar "sem WHERE" em vermelho,
  exigir digitar a tabela para confirmar) — descartada: ainda depende de alguém prestar atenção sob
  rotina; o padrão que funcionou para DDL (recusa automática, zero decisão humana) é mais simples e
  fecha a lacuna de verdade.
- **Diferenciar por conexão (`read_only` vs `read_write`)** — ortogonal: `access_mode` já existe
  para o MCP de leitura; não resolve o caso de uma conexão de escrita legítima com um `DELETE` sem
  `WHERE` por engano.
- **Exigir uma segunda aprovação (duplo clique, admin em vez de editor)** — descartada por mesmo
  motivo: atrito a mais no caminho humano não fecha a lacuna estrutural, só a adia.

## Consequências

- Uma `DELETE`/`UPDATE` sem `WHERE` restritivo nunca mais executa pelo agente ou pela app gerada em
  `enforce` — quem precisar de fato apagar/atualizar em massa reescreve a statement com um `WHERE`
  explícito (ainda que tautológico) ou roda manualmente fora do caminho do proxy, com a credencial
  real.
- A tarefa 6.2 original (medir falso-positivo do modo sombra antes de confiar no proxy para decidir
  sozinho) fica sem objeto para `confirmável`: não há mais uma "decisão de confiar" a validar — o
  tratamento é uniforme e automático, igual a DDL. A tarefa 7.3 (virar o default para `enforce`) foi
  concluída por pedido direto do operador, sem esperar o período de comparação formal.
- Nenhuma statement que antes só pedia confirmação volta a executar sem revisão: a app gerada mantém
  seu próprio diálogo de confirmação (`dbgate.py`, requirement *Gate na app gerada* de
  `destructive-gate`), que é uma camada de UX para o usuário final da app, não o fluxo de aprovação
  entre agente e editor que este ADR remove.
