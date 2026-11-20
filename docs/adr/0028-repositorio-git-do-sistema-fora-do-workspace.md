# 0028 — Repositório git do sistema fora do workspace; restauração sem reescrever histórico

* Status: aceito
* Data: 2026-11-21
* Decidida em: change `isolate-workspace-repository` (design D1-D5)
* Substitui: a parte de rollback do [0009](0009-git-por-sistema-com-checkpoints.md)

## Contexto

Pelo [0009](0009-git-por-sistema-com-checkpoints.md), o repositório de checkpoints vivia em
`/workspace/.git`, dentro do diretório que o agente escreve livremente, e o portal rodava `git`
ali. O git interpreta como comando várias coisas que ficam nesse diretório: hooks, `core.fsmonitor`,
filtros declarados em `.gitattributes` e definidos na config, `include.path`.

Um teste escrito antes da correção (`tests/integration/test_workspace_repository_isolation.py`,
git 2.54, host com Landlock ABI 8) confirmou, contra o código anterior:

| Item plantado pelo agente | Driver Docker | Driver Kubernetes |
|---|---|---|
| hook `pre-commit` e `post-commit` | executou | executou |
| `core.fsmonitor` | executou | executou |
| filtro em `.gitattributes` | executou | executou |
| filtro via `include.path` | não executou | não executou |

No Docker, os comandos rodaram no processo do portal (root, na imagem do portal). No Kubernetes,
rodaram por `exec` no container `agent` com o uid do agente, mas **fora do Landlock**: o hook
escreveu em `/home/agent`, que o agente confinado (`sandboxed`) não alcança.

Além disso, o rollback era `git reset --hard`: reescrevia o histórico e apagava da branch os
checkpoints posteriores ao restaurado, o que inviabiliza enviar o histórico a um repositório
remoto (change `add-system-git-remote`).

## Decisão

1. **O repositório sai do workspace.** O workspace é só a árvore de trabalho; o `GIT_DIR` fica em
   `APPAIFORGE_GITDIRS_DIR/<slug>` (volume montado só no portal) no Docker, e num PVC próprio
   (`appaiforge-sys-<slug>-gitdir`) montado só num container auxiliar `git` do pod no Kubernetes.
   O container `agent` não monta o repositório, e o git do portal nunca roda nele.
2. **Ambiente limpo em toda chamada** (`appaiforge/git_backend.py`): `GIT_DIR`/`GIT_WORK_TREE`
   explícitos, `HOME` inexistente, `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`, e
   `core.hooksPath=/dev/null`, `core.fsmonitor=false` e `safe.directory=*` na linha de comando.
   A config do repositório é escrita pelo portal e não define filtro, driver, hook nem include.
3. **O git roda com o uid do dono do workspace** (o do agente em `reduced`/`sandboxed`, root em
   `legacy`), decidido pelo modo de execução gravado, para os arquivos restaurados continuarem do
   agente. No driver Docker, antes da migração e de cada restauração, o que estiver com o root no
   workspace passa ao agente (exceto o `.git` antigo), por varredura que nunca segue link
   simbólico — sem isso, a restauração falhava com `Permission denied` em workspaces antigos,
   que têm diretórios criados pelo portal como root.
4. **Migração preguiçosa como dado**: na primeira operação git de um sistema antigo, só os arquivos
   de objeto do `.git` antigo são copiados (sem links simbólicos, sem `alternates`), e a branch
   aponta para o último checkpoint **registrado pelo portal**, nunca para as refs antigas. O `.git`
   antigo fica no workspace, sem uso.
5. **Restaurar cria um checkpoint novo** (`origin = restore`) sobre a ponta atual; os checkpoints
   posteriores continuam no histórico e restauráveis. Restaurar um checkpoint igual ao estado atual
   não cria nada. A tabela `checkpoints` ganha `origin` (`run`, `manual`, `restore`).

## Alternativas consideradas

- **Neutralizar por opção a cada chamada** (`-c core.hooksPath=/dev/null` e afins): lista de
  bloqueio; não cobre filtros, `include.path`, drivers nem o que versões futuras do git
  acrescentarem. Mantida só como defesa adicional.
- **Tornar `.git` não gravável por permissão**: o agente é dono de `/workspace` e pode renomear o
  diretório; o Landlock não permite exceção de negação abaixo de um caminho liberado.
- **`subPath` no PVC do workspace** para separar árvore e repositório: exigiria migrar o conteúdo
  de todo PVC existente.

## Consequências

- Nada que o agente escreve no workspace é executado pelas operações git do portal, nos dois
  drivers (`test_workspace_repository_isolation.py`, `test_driver_parity.py`).
- No Kubernetes, cada pod ganha o container `git` e um PVC de 1 GiB; pods antigos são recriados
  pela reconciliação. O `Role` do chart passa a precisar de `delete` em `persistentvolumeclaims`
  (que a exclusão definitiva do PVC do workspace já exigia e não tinha).
- Migrar um sistema de `legacy` para `sandboxed` exige também dar o repositório ao uid do agente
  ([segurança](../seguranca.md#migrar-um-sistema-de-legacy-para-sandboxed)).
- Restaurar não desfaz mais o histórico: uma restauração indesejada se desfaz restaurando o
  checkpoint anterior a ela. Alterações sem checkpoint continuam sendo descartadas na restauração.
- O `.git` antigo, desatualizado, continua legível pelo agente nos sistemas migrados.
- Uma restauração que falha no meio devolve a branch à ponta anterior antes de propagar o erro.
- Verificado com um sistema criado pelo portal anterior na stack E2E: histórico migrado para o
  último checkpoint registrado, restauração reescrevendo dentro de diretório do root, arquivos
  restaurados com o uid do agente, `/app` do portal intacto com um link para ele plantado no
  workspace, execução de chat e app no ar depois da migração.
- Reverter o portal para a versão anterior volta a usar `/workspace/.git`; os checkpoints criados
  depois da migração não existem lá.
