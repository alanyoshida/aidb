# Design

## Context

Motivação e escopo: ver `proposal.md`. Requisitos: ver `specs/`.

Esta change parte do estado deixado por `isolate-workspace-repository`: o repositório de cada sistema vive fora do workspace, atrás de um backend git por driver (subprocesso com `GIT_DIR` próprio no Docker; `exec` num container auxiliar `git` no Kubernetes), o rollback é um commit de restauração e a tabela `checkpoints` tem a coluna `origin`.

Estado atual observado no código, relevante aqui:

- O checkpoint acontece em `agent_queue.py`, ao fim de `_execute`, e a fila é serial por sistema.
- Segredos de sistema são cifrados com `security.encrypt_secret`.
- A imagem do portal tem `git`, mas não tem cliente SSH.
- O stack E2E com Keycloak (`deploy/docker-compose.e2e-oidc.yml`, `tests/e2e_oidc`) é o precedente para um stack E2E com serviço externo local.
- O harness fake grava arquivos reais no workspace, então uma execução de teste gera checkpoint de verdade.

Restrições vindas da exploração com o usuário: dois portais isolados (homologação e produção) compartilham só o repositório; GitLab é a primeira forja; a branch de trabalho recebe merges de humanos; o merge request para a branch de destino nasce por ação explícita; a definição do pipeline vive em projeto separado; o stack E2E com GitLab e runner é montado no início; alterações não salvas bloqueiam a sincronização até o editor decidir; o estado divergente tem duas saídas.

## Goals / Non-Goals

**Goals:**

- A chave privada de implantação só existe em memória e em arquivo temporário dentro do processo do portal.
- Um único caminho de código para a lógica de remoto nos dois drivers.
- Falha do remoto nunca derruba uma execução do agente nem perde um checkpoint.
- O portal nunca decide sozinho entre salvar e descartar trabalho do editor.

**Non-Goals:**

- Sistema "só implantação" e tudo do portal de produção (change seguinte).
- Status de pipeline no portal. A API do GitLab é usada só para abrir e consultar o merge request de promoção (D7).
- git por HTTPS com token, GitHub e outras forjas.
- Submódulos e Git LFS.

## Decisions

### D1 — Repositório de retransmissão no portal e pacotes git

Toda conversa com o remoto parte de um repositório bare por sistema no portal, em `<git_relays_dir>/<slug>`, sem árvore de trabalho. É um cache reconstruível.

```
 repositorio do sistema                     portal
+--------------------------+   bundle   +----------------------+   SSH   +--------+
| GIT_DIR + arvore de      |----------->| retransmissao (bare) |-------->| GitLab |
| trabalho no workspace    |<-----------| chave so aqui        |<--------|        |
+--------------------------+   bundle   +----------------------+         +--------+
```

- **Envio**: `git bundle create` da branch no repositório do sistema, limitado ao que o remoto ainda não tem; `git fetch` do pacote na retransmissão; `git push` para `refs/heads/<branch de trabalho>`, sem `--force`.
- **Recebimento**: `git fetch` do remoto na retransmissão; pacote do que o sistema ainda não tem; `git fetch` do pacote no repositório do sistema; integração (D3).

O backend git por driver ganha duas operações: exportar pacote e importar pacote. No Docker o pacote é um arquivo local. No Kubernetes trafega pelo `exec` codificado em base64, porque o canal de `exec` do cliente Python não é seguro para binário.

Por que não empurrar direto do repositório do sistema: no Kubernetes ele vive num pod que divide o namespace de rede com o agente. Empurrar de lá exigiria colocar a chave no pod e liberar a saída do pod para o servidor git, o que amplia a rede dos sistemas em modo não `sandboxed`. Usar o mesmo caminho no Docker mantém uma lógica só e dá à suíte de paridade o que comparar.

### D2 — Chave, identidade do servidor e invocação do SSH

- Par ed25519 gerado pelo portal (biblioteca `cryptography`, já usada para a cifra de segredos) na primeira abertura da aba. Privada guardada com `encrypt_secret`; pública em claro.
- Nova tabela `system_git_remotes` (uma linha por sistema): `url`, `working_branch`, `target_branch`, `public_key`, `private_key_encrypted`, `host_key`, `api_url` (vazio = derivado), `api_token_encrypted` (opcional), `enabled`, `state` (`synced`, `pending`, `diverged`, `error`), `state_detail`, `last_pushed_sha`, `last_synced_at`, `conflict_files`, `merge_in_progress`, `unsaved_blocked`, `last_mr_url`.
- Identidade do servidor: no teste de conexão o portal obtém a chave do servidor, mostra a impressão digital SHA256 e grava `host_key` só depois da confirmação. As operações usam `StrictHostKeyChecking=yes` com um `known_hosts` temporário contendo só essa chave.
- Cada operação remota escreve a chave privada num diretório temporário `0700` em `tmpfs`, usa `GIT_SSH_COMMAND` com `-i`, `IdentitiesOnly=yes`, `BatchMode=yes`, `UserKnownHostsFile`, e apaga o diretório ao terminar, inclusive em erro.
- O endereço aceito é `ssh://[user@]host[:porta]/caminho` ou `user@host:caminho`. Protocolos `ext::`, `file://` e HTTP são recusados, e as chamadas usam `GIT_ALLOW_PROTOCOL=ssh`.
- A imagem do portal ganha `openssh-client`.

### D3 — Integração do que vem do remoto

A integração roda no repositório do sistema. Primeiro passo, sempre: se o recebimento trouxe commits e `git status --porcelain` não está vazio, a integração não acontece (ver D4). Depois, três casos:

1. **Remoto à frente, local sem commits não enviados**: avanço rápido da branch e atualização da árvore de trabalho. O supervisor já reinicia a app quando os arquivos mudam.
2. **Os dois com commits novos, sem conflito**: `git merge --no-ff` com autor do portal; o resultado é enviado.
3. **Conflito**: `git merge --abort`, grava `state = diverged` e `conflict_files`. A árvore de trabalho fica como estava.

Toda integração que traz commits registra um checkpoint com `origin = remote`.

Enquanto o sistema está divergente, o portal continua recebendo do remoto para a retransmissão, mas não tenta integrar de novo sozinho.

### D4 — Alterações não salvas bloqueiam, o editor decide

Quando o recebimento trouxe commits e há alterações sem checkpoint:

- Antes de uma execução: o harness não é chamado. A execução termina com falha explícita e uma mensagem no chat explicando o motivo e apontando para a aba Repositório. `unsaved_blocked` é gravado.
- Em "Sincronizar agora": a ação é recusada com a mesma explicação.

A aba Repositório mostra o bloqueio com duas ações: "Salvar como checkpoint" (o checkpoint manual existente, seguido da integração) e "Descartar alterações não salvas" (com confirmação; restaura a árvore de trabalho para o último checkpoint e segue com a integração). Depois de qualquer uma, `unsaved_blocked` é limpo e o editor reenvia o pedido.

Sem commits a trazer, alterações não salvas não bloqueiam nada: o comportamento é o de hoje. Depois de uma execução bem-sucedida não há alterações não salvas, porque o checkpoint acabou de ser criado.

Alternativa descartada, a pedido do usuário: checkpoint automático das sobras antes de sincronizar. Evitaria travar o chat, mas enviaria trabalho incompleto à branch de trabalho sem ninguém decidir.

### D5 — Saídas do estado divergente

**Resolver no workspace**: refaz o merge sem abortar, deixando as marcas nos arquivos, e grava `merge_in_progress`. No checkpoint seguinte, se algum arquivo de `conflict_files` ainda contiver linha iniciada por `<<<<<<<`, `=======` ou `>>>>>>>`, o portal não conclui o merge e mantém `diverged`; senão conclui o commit de merge e envia. "Cancelar resolução" executa `git merge --abort`. Com `merge_in_progress`, as marcas na árvore de trabalho não contam como alterações não salvas para D4.

**Adotar a versão do remoto**: com confirmação que lista os checkpoints locais não enviados. O portal grava uma referência de proteção `refs/aidb/set-aside/<sha>` para a ponta local (para os objetos sobreviverem à coleta de lixo), move a branch local para a ponta remota, atualiza a árvore de trabalho e registra um checkpoint `origin = remote`. Os checkpoints deixados de lado continuam na tabela e são restauráveis pelo rollback da change anterior, que só precisa do objeto. Nada é enviado ao remoto.

### D6 — Pontos de encaixe na fila do agente

Em `agent_queue._execute`, para sistemas com remoto ativo:

- **Antes de chamar o harness**: recebimento e integração (D3, D4). Erro de rede é registrado em `state_detail` e a execução segue.
- **Depois do checkpoint de uma execução bem-sucedida**: recebimento, integração e envio. Erro vira `state = pending`.

As operações remotas têm tempo limite de 30 s e rodam na thread de trabalho do sistema. Como a fila é serial por sistema, uma sincronização nunca coincide com uma execução; as ações da aba Repositório verificam `system_state` e recusam quando há execução em andamento. Checkpoint manual e rollback pela aba Checkpoints seguem o mesmo passo de envio.

### D7 — Solicitação de promoção pela API do GitLab, com token por sistema

**Decisão revista depois da tarefa 1.3** (escolha do usuário). O desenho original usava `-o merge_request.create` no push, sem API. A verificação mostrou que, sem commit novo a enviar — o caso comum ao solicitar promoção —, o git nem contacta o servidor; o portal não conseguiria abrir o MR nem saber se já existe um.

- **Token opcional por sistema**, cifrado com `encrypt_secret` (`api_token_encrypted`), nunca exibido nem entregue ao container. Recomendação no guia: token de projeto com papel Developer e escopo `api` — o mínimo que abre merge request.
- **Endereço da API**: `https://<host do endereço SSH>` por padrão; o editor pode informar outro (`api_url`), necessário quando o SSH e o HTTP do GitLab têm hosts ou esquemas diferentes, como na stack E2E (`gitlab:22` e `http://gitlab`).
- **Projeto**: o caminho do endereço SSH sem `.git`, codificado na URL (`/projects/time%2Fapp`).
- **Promoção**: `GET /projects/:id/merge_requests?state=opened&source_branch=<trabalho>&target_branch=<destino>`; havendo um, mostra o endereço dele; senão, `POST /projects/:id/merge_requests` com título e descrição gerados pelo portal (sistema, branches, últimos checkpoints). O endereço fica em `last_mr_url`.
- **Teste do token**: `GET /projects/:id` e verificação de que o nível de acesso permite abrir MR; nada é escrito.
- **Sem token ou token recusado**: o portal exibe o endereço de criação preenchido: `<base do projeto>/-/merge_requests/new?merge_request[source_branch]=<trabalho>&merge_request[target_branch]=<destino>`.
- As chamadas saem do processo do portal (cliente HTTP já usado pelo portal, tempo limite de 30 s), nunca do container do sistema; a rede do agente não muda.

Alternativas consideradas: só o link de criação mais o último MR visto nas respostas de push (sem segredo novo, mas sem como saber se o MR ainda está aberto); commit vazio de promoção para forçar o push (polui o histórico a cada solicitação).

**Verificado contra o GitLab CE 19.4.5 (tarefa 1.3), com a chave cadastrada por um mantenedor comum:**

| Comportamento | Resultado |
|---|---|
| Push na branch de trabalho protegida ("mantenedores fazem push") | aceito |
| Push direto na branch de destino protegida ("ninguém faz push") | recusado |
| Autor do push, do merge request e do pipeline | quem cadastrou a chave no GitLab; o commit mantém o editor como autor |
| `-o merge_request.create` num push **com** commit novo | abre o merge request e a resposta traz o endereço |
| A mesma opção num push **sem** commit novo | não funciona: o git responde "Everything up-to-date" e nem contacta o servidor |
| Push com merge request já aberto para a branch | a resposta traz "View merge request for <branch>" com o endereço |

Consequências: a chave de implantação deve ser cadastrada por alguém com permissão de push na branch de trabalho e sem permissão de push na de destino; o GitLab trata o push como dessa pessoa. A proteção da branch de destino (ninguém faz push) é o que obriga o merge request, independentemente de quem cadastrou a chave.

### D8 — Proteção de `.gitlab-ci.yml`

Em sistemas com remoto ativo, antes do commit de cada checkpoint: se `.gitlab-ci.yml` na raiz não é rastreado, ele é excluído pelo `info/exclude` do `GIT_DIR` (que o agente não alcança); se é rastreado e foi modificado na árvore de trabalho, o arquivo é restaurado para a versão do último commit antes do `git add`. Nos dois casos o checkpoint registra um aviso exibido na aba Repositório e na auditoria. Alterações que chegam pelo remoto não são afetadas.

Isso é defesa adicional. A garantia principal é o projeto no GitLab apontar a configuração de CI para outro projeto, o que o guia de preparação documenta.

### D9 — Stack E2E primeiro, e estratégia de teste

O stack com GitLab é a primeira entrega, porque três comportamentos do GitLab sustentam D7 e a configuração de proteção de branch e não foram verificados.

- **E2E**: `deploy/docker-compose.e2e-gitlab.yml` com GitLab CE e GitLab Runner em versões fixadas, portal na porta 8083 com harness fake, e a suíte `portal/tests/e2e_gitlab`. Um script de inicialização cria o token de root, registra o runner (executor shell), cria o projeto de modelos de CI e o projeto do sistema com a configuração de CI apontando para o primeiro, protege as branches e habilita merge sem squash. O teste faz o papel do humano pela API. O pipeline tem um job de validação simbólico e, na branch de destino, um job que cria a tag de versão.
- **Integração**: servidor git por SSH efêmero (container com `sshd` e repositório bare) para envio, recebimento, bloqueio por alterações não salvas, conflito, as duas saídas da divergência e chave do servidor trocada. É aqui que a lógica de git é exercitada no dia a dia, sem GitLab.
- **BDD**: um arquivo de feature para a capability, conforme o ADR 0016.
- **Unitário**: validação de URL, geração de chave, extração do endereço do merge request, detecção de marcas de conflito, derivação do endereço de criação.

## Risks / Trade-offs

- [O GitLab pode ignorar opções de push sem commits novos] → **Confirmado na tarefa 1.3**: sem commit novo o git nem contacta o servidor. Ver a tabela em D7.
- [Autor do merge request e do pipeline quando o push vem de chave de implantação] → **Verificado na tarefa 1.3**: é quem cadastrou a chave. No GitLab Free a aprovação é opcional, então a garantia é a branch de destino protegida.
- [Chave de implantação em branch protegida que também aceita merges] → **Verificado na tarefa 1.3**: funciona com "mantenedores fazem push / developers fazem merge" na branch de trabalho, desde que a chave seja cadastrada por um mantenedor.
- [O bloqueio por alterações não salvas para o chat até alguém decidir] → Escolha do usuário. Só ocorre quando há commits a trazer; a mensagem no chat leva direto à decisão.
- [Adotar o remoto deixa de lado trabalho local com um clique] → Confirmação lista os checkpoints; eles continuam restauráveis; a ação é auditada.
- [Quem tem permissão de merge na branch de trabalho consegue instruir o agente, via `AGENTS.md` e `openspec/` trazidos pela sincronização] → Aceito: é código revisado. O guia orienta proteger a branch de trabalho com o mesmo rigor da de destino.
- [O GitLab local é pesado e lento para subir] → Suíte separada, fora do ciclo rápido; a lógica de git é coberta na camada de integração.
- [Sincronização antes de cada execução acrescenta latência ao chat] → Tempo limite de 30 s e falha não bloqueante; sistemas sem remoto não pagam nada.
- [Histórico ruidoso: um commit por execução] → Aceito; o merge request agrupa a revisão. Merge sem squash é exigido para a branch de trabalho não divergir da de destino.
- [A retransmissão duplica o histórico em disco no portal] → Repositórios de app gerada são pequenos; é cache reconstruível e é removido na exclusão definitiva.

## Migration Plan

1. Aplicar antes a change `isolate-workspace-repository`.
2. Migração Alembic: tabela `system_git_remotes`.
3. Deploy do portal com o volume `git_relays_dir` e a imagem com cliente SSH.
4. Nenhum sistema muda de comportamento até alguém configurar e ativar um repositório na aba.

Reversão: desativar o vínculo de cada sistema interrompe envios e sincronizações sem tocar no workspace nem no remoto. A reversão do schema é a migração Alembic de descida; o que já foi publicado no remoto permanece lá.
