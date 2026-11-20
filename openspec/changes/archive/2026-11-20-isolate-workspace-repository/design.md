# Design

## Context

Motivação e escopo: ver `proposal.md`. Requisitos: ver `specs/`.

Estado atual observado no código:

- `portal/appaiforge/checkpoints.py` é o único lugar que executa git. No driver Docker o portal roda `git` como root, por `subprocess`, no bind mount do workspace. No driver Kubernetes roda por `exec` dentro do container `agent` do pod.
- O `.git` fica em `/workspace/.git`, e `/workspace` está nos `writable_paths` dos dois perfis de agente (`agent_profiles.py`). Não há neutralização de hooks nem de configuração. `git status` e `git add` honram `core.fsmonitor`, filtros de `.gitattributes` e hooks, todos graváveis pelo agente.
- Um processo criado por `exec` no container não herda o Landlock/seccomp que o supervisor impõe à árvore do agente. No driver Kubernetes, um hook plantado executaria fora do confinamento, com rede direta.
- O rollback é `git reset --hard` + `git clean -fd`, chamado direto da aba Checkpoints.
- Migrações de schema usam Alembic (`portal/migrations`).

A existência do risco foi deduzida da leitura do código; a tarefa 1.1 o reproduziu antes de qualquer correção, com `tests/integration/test_workspace_repository_isolation.py` contra o código anterior (git 2.54, host com Landlock ABI 8):

| Item plantado pelo agente | Driver Docker | Driver Kubernetes |
|---|---|---|
| hook `pre-commit` e `post-commit` | executou | executou |
| `core.fsmonitor` em `.git/config` | executou | executou |
| filtro declarado em `.gitattributes` | executou | executou |
| filtro definido por `include.path` | não executou | não executou |

- **Docker**: os comandos rodaram no processo do portal, com a identidade dele (root na imagem do portal; o uid do desenvolvedor na rodada local).
- **Kubernetes**: rodaram por `exec` no container `agent`, com o uid do agente, e o hook conseguiu escrever em `/home/agent`, fora dos `writable_paths` do perfil. O sistema estava em modo `sandboxed`, então isso confirma execução fora do Landlock.
- O `include.path` não reproduziu, mas não foi investigado: a correção não depende disso, e o teste continua cobrindo o caso.

## Goals / Non-Goals

**Goals:**

- Nenhum conteúdo gravável pelo agente é interpretado como código ou configuração pelas operações git do portal.
- Mesma garantia nos drivers Docker e Kubernetes.
- Nenhum checkpoint existente é perdido e nenhum identificador muda.
- Rollback que não reescreve histórico, para todo sistema.

**Non-Goals:**

- Qualquer comunicação com repositório remoto.
- Dar ao agente acesso ao histórico git do sistema.
- Remover o `.git` antigo do workspace.
- Submódulos e Git LFS.

## Decisions

### D1 — Repositório com `GIT_DIR` separado da árvore de trabalho

O repositório de cada sistema passa a viver fora do workspace e é operado com `GIT_DIR` e `GIT_WORK_TREE` explícitos. O workspace é só a árvore de trabalho. Toda invocação usa ambiente limpo: `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`, sem `HOME` herdado. A configuração do repositório é escrita pelo portal e não define filtro, driver de merge/diff nem hook.

Com isso, hooks e `config` são do portal. `.gitattributes` continua sendo lido da árvore de trabalho, mas um filtro ou driver só executa se a configuração o definir, e ela não define nenhum. Um diretório `.git` na raiz da árvore de trabalho nunca é rastreado pelo git, então o `.git` antigo fica inerte.

Alternativas descartadas:

- *`-c core.hooksPath=/dev/null` e afins a cada chamada*: é lista de bloqueio. Não cobre filtros, `core.fsmonitor`, `include.path`, drivers e o que versões futuras do git acrescentarem.
- *Tornar `.git` não gravável por permissão de arquivo*: o agente é dono de `/workspace` e pode renomear o diretório e criar outro. O Landlock é lista de permissão hierárquica e não permite exceção de negação abaixo de um caminho liberado.
- *Rodar git só dentro do container como o agente*: no driver Kubernetes já é assim, e o processo de `exec` fica fora do confinamento.

### D2 — Onde o `GIT_DIR` fica, por driver

- **Docker**: em `<gitdirs_dir>/<slug>`, num volume montado só no portal (nova configuração `gitdirs_dir`). O container do sistema não monta esse volume.
- **Kubernetes**: num PVC próprio (`gitdir-<slug>`), montado só num novo container auxiliar `git` do pod do sistema, que também monta o volume do workspace. O container `agent` não monta o PVC do repositório. O container auxiliar usa a imagem base (já tem git), fica ocioso e só executa o que o portal pede por `exec`. O pod não compartilha namespace de processos.

Alternativa descartada: usar `subPath` do PVC de workspace existente para separar árvore e repositório. Exigiria migrar o conteúdo de todo PVC existente para um subdiretório.

Todo comando git passa a ser `exec` no container `git`, nunca no `agent`.

A variação por driver fica atrás de uma interface pequena de backend git: executar git no repositório do sistema e remover o repositório. A change `add-system-git-remote` estende essa interface.

### D3 — Identidade que executa o git

O git roda com o mesmo uid/gid dono do workspace do sistema (o uid do agente nos modos `reduced` e `sandboxed`, root em `legacy`). No Docker isso é feito no `subprocess` (`user=`/`group=`); no Kubernetes o container `git` herda `runAsUser`/`fsGroup` do pod. Assim os arquivos escritos por restauração continuam do agente, e o git deixa de rodar como root no processo do portal para sistemas não legados. O `GIT_DIR` pertence a esse mesmo uid; o isolamento vem de o volume não estar montado no container do agente, não de permissão de arquivo.

**Normalização de dono (acrescentada na implementação, decisão do usuário).** A verificação com um sistema legado (tarefa 5.2) mostrou que workspaces do driver Docker têm caminhos do root: o portal antigo restaurava como root, e o `materialize` das guidelines ainda escreve como root. Com o git rodando como o agente, a restauração falhava com `Permission denied` ao reescrever dentro desses diretórios. Por isso, no driver Docker com o portal rodando como root, antes da migração e de cada restauração o portal passa ao uid do agente o que estiver com o root dentro do workspace, exceto o `.git` antigo da raiz. A varredura usa `os.fwalk` sem seguir links e `chown` relativo ao descritor do diretório, também sem seguir link, então trocar um diretório por um link simbólico no meio da varredura não leva o `chown` para fora do workspace. No Kubernetes não há o que normalizar.

Alternativas consideradas: voltar a rodar o git como root e só ajustar o dono do que a restauração escreveu (o que o portal grava fora da restauração continuaria do root); ou só documentar e exigir `chown` manual.

**Restauração atômica em relação à branch.** A mesma verificação mostrou que uma falha depois do `reset --hard` deixava a branch no checkpoint antigo. A restauração passou a devolver a branch à ponta anterior (e, no melhor esforço, a árvore de trabalho) antes de propagar o erro.

### D4 — Migração do histórico existente como dado

Na primeira operação git de um sistema sem `GIT_DIR` novo: criar o repositório novo, copiar `objects/` do `.git` antigo (arquivos endereçados por conteúdo, tratados como dado) e apontar a branch para o `git_sha` do checkpoint mais recente registrado na tabela `checkpoints`, depois de confirmar que o objeto existe. Referências, `config`, `hooks` e `packed-refs` antigos não são lidos. Sem checkpoint registrado, o repositório nasce vazio.

O `.git` antigo permanece no workspace, intocado. Motivo: o harness pode usar a presença de um repositório para identificar o projeto e manter sessões, e removê-lo é uma mudança de comportamento sem ganho de segurança depois de D1. Para sistemas novos o portal deixa de criar `.git` no workspace (ver Open Questions).

### D5 — Rollback como commit de restauração

`rollback(sha)` passa a: carregar a árvore de `sha` no índice e na árvore de trabalho (removendo arquivos que não existem nela), e commitar com mensagem `restaura checkpoint <sha8>`. Se a árvore resultante for idêntica à atual, nada é commitado. O commit é registrado na tabela `checkpoints` com `origin = restore`.

A tabela `checkpoints` ganha a coluna `origin` (`run`, `manual`, `restore`), com `run` como padrão para os registros existentes. A coluna é texto livre, para a change seguinte acrescentar valores sem nova migração de tipo.

### D6 — Estratégia de teste

- **Integração**: um teste que planta hook, filtro, `core.fsmonitor` e `include.path` no workspace e verifica que nada executa. O mesmo teste roda primeiro contra o código atual para confirmar o risco (tarefa 1.1).
- **Paridade**: `tests/integration/test_driver_parity.py` ganha checkpoint, hook plantado e restauração nos dois drivers.
- **BDD**: feature nova para `workspace-repository` e cenários novos em `agent-harness`, conforme o ADR 0016.
- **E2E**: a aba Checkpoints, no stack E2E existente.

## Risks / Trade-offs

- [O risco pode não ser explorável como deduzido] → A tarefa 1.1 reproduz antes de corrigir. Se não reproduzir em algum driver, o resultado é registrado no ADR; a mudança de local continua valendo como defesa e como pré-requisito do remoto.
- [Link simbólico malicioso na árvore de trabalho durante uma restauração] → O git recusa escrever através de link simbólico; D3 tira o root do caminho nos modos não legados; no Kubernetes a operação ocorre dentro do pod.
- [Pods existentes precisam ser recriados para ganhar o container `git`] → A reconciliação recria; até lá o portal detecta a ausência do container e recusa a operação git com mensagem clara, sem cair no caminho antigo.
- [O `.git` antigo fica desatualizado no workspace e o agente pode lê-lo] → Sem efeito sobre o portal; registrado em `docs/seguranca.md`.
- [`chown` feito como root numa árvore controlada pelo agente] → Varredura por descritor, sem seguir link, nunca entra no `.git` antigo; verificado como root com um link para `/app` plantado no workspace, que continuou inteiro do root.
- [O rollback muda de semântica para quem já usa] → O estado do workspace resultante é o mesmo; a aba Checkpoints passa a mostrar a origem de cada ponto.
- [Mais um container e um PVC por sistema no Kubernetes] → Container ocioso, sem requisição relevante de recursos; PVC pequeno.

## Migration Plan

1. Migração Alembic: coluna `checkpoints.origin`.
2. Deploy do portal com o novo volume (`gitdirs_dir`). No Kubernetes, o chart ganha o PVC por sistema e o container `git`.
3. A migração do histórico (D4) é preguiçosa: acontece na primeira operação git de cada sistema. Não há passo manual.
4. No Kubernetes, a reconciliação recria os pods com o container `git`.

Reversão: a versão anterior do portal volta a usar `/workspace/.git`, que foi preservado. Checkpoints criados depois da migração não existem nesse repositório antigo e seriam perdidos na reversão. A reversão do schema é a migração Alembic de descida.

## Open Questions

- ~~O harness precisa de um `.git` no workspace em sistemas novos?~~ **Respondida (tarefa 2.6): não.** Com o workspace sem `.git`, o opencode manteve a sessão por várias mensagens e carregou o `AGENTS.md` (`test_opencode_instructions.py`), e o claude-code completou uma execução com checkpoint (`test_claude_code_e2e.py`, rodado com o stub no `node` 22 da imagem local porque o registry estava inacessível). O supervisor não cria repositório nenhum.
