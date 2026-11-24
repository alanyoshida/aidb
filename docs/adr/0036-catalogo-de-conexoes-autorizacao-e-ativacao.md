# 0036 — Catálogo de conexões de banco: autorização pelo DB Manager, ativação pelo dono do sistema

* Status: aceito
* Data: 2026-11-24
* Decidida em: change `add-db-manager-role`
* Relacionada: [ADR 0007](0007-metadados-em-postgres-e-credenciais-cifradas.md) (credenciais
  cifradas); [ADR 0017](0017-gate-de-operacoes-destrutivas-com-classificador-sql.md) (gate de
  operações destrutivas); [ADR 0021](0021-gate-de-sql-no-data-plane-via-sidecar-proxy.md) (gate no
  sidecar, listeners por origem); [ADR 0023](0023-confirmavel-recusado-direto-sem-pedir-aprovacao.md)
  (confirmável recusado direto)

## Contexto

Cada dono de sistema cadastrava as próprias conexões de banco, com host, usuário e senha. A
credencial ficava espalhada entre quem constrói sistemas, a mesma conexão não podia servir a dois
sistemas, e quem responde pelos bancos não controlava quem acessa o quê. O gate também recusava
toda DDL, então o agente não conseguia criar nem reestruturar tabelas no começo de um sistema.

## Decisão

**DB Manager é uma capacidade, não um tipo.** Um indicador no usuário, somado ao tipo global
(`admin`, `editor`, `app_user`). Um editor pode também ser DB Manager. No OIDC vem do papel
`db_manager`, no mesmo claim de papéis, fora da ordem de tipos; sozinho ele não basta para entrar.

**Conexões formam um catálogo único.** Uma conexão não pertence a sistema. Quem gere o catálogo
(DB Manager ou admin) cadastra, edita, testa e exclui. O tipo é imutável depois do cadastro.

**Duas camadas: autorização e ativação.** O DB Manager autoriza uma conexão para um sistema e
define o teto de modo de acesso. O dono do sistema ativa ou não, escolhe o alias e o modo vigente,
igual ou abaixo do teto. Só conexões ativas chegam ao agente e à app.

**O alias é o contrato com o código.** `DATABASE_URL_<ALIAS>`, o nome da ferramenta MCP, o
manifesto no git e a conferência do deploy usam o alias, que o dono escolhe e que não muda
enquanto a conexão está ativa. O nome no catálogo é só para exibição.

**Três modos ordenados.** `read_only` < `read_write` < `schema_admin`. `schema_admin` libera DDL e
DML em massa no listener de origem `agente` do sidecar; o listener da `app` nunca recebe essa
liberação. Toda statement liberada é auditada como decisão do gate.

**Revogar é reprovisionar na hora.** Revogar, rebaixar o teto abaixo do modo vigente e excluir a
conexão recriam o container dos sistemas afetados, o mesmo caminho de antes para remover conexão.
O dono vê um aviso com data e autor.

## Alternativas consideradas

- **Quarto valor no enum de tipo** — descartada: o tipo é exclusivo e ordenado, e DB Manager não
  está acima nem abaixo de editor.
- **Copiar a conexão para cada sistema** — descartada: duplica a credencial e transforma a rotação
  de senha em várias edições.
- **Nome global imutável no lugar do alias** — descartada: engessa o catálogo e colide na migração,
  porque vários sistemas tinham conexões com o mesmo nome.
- **Recarga a quente do sidecar** — descartada: o sidecar lê o manifesto na partida, e BigQuery,
  que não passa por ele, exigiria recriar o container de qualquer forma.
- **Prazo de expiração para `schema_admin`** — descartada nesta decisão: o rebaixamento é manual,
  com um selo de "DDL liberada desde" visível ao dono e ao DB Manager.

## Consequências

- O dono deixa de ver host, porta, banco e usuário; vê nome, descrição, tipo, saúde, teto e modo.
- O teto `read_only` continua valendo só no MCP: o bash do agente e a app ainda escrevem.
  Isolamento real de leitura exige um usuário de banco somente-leitura cadastrado como outra conexão.
- Com o gate em modo sombra, `schema_admin` não muda nada, porque nada é recusado.
- Revogar uma conexão BigQuery corta a entrega da credencial, mas a chave já lida pela app só é
  invalidada ao ser rotacionada no GCP.
- A migração converte cada conexão em item do catálogo autorizado e ativo no sistema de origem; o
  `downgrade` só funciona enquanto cada conexão tiver uma autorização.
