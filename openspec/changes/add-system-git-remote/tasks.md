# Tasks

Pré-requisito: a change `isolate-workspace-repository` aplicada.

Regra do projeto (`CLAUDE.md`): rodar a análise de impacto do GitNexus antes de editar cada símbolo existente e `detect-changes` antes de cada commit.

## 1. Stack E2E com GitLab local e verificação do GitLab

- [x] 1.1 Criar `deploy/docker-compose.e2e-gitlab.yml` com GitLab CE e GitLab Runner em versão fixada e o portal na porta 8083 com harness fake; verificar que o stack sobe do zero e que o GitLab responde ao healthcheck
- [x] 1.2 Escrever o script de inicialização: token de root, runner com executor shell, projeto de modelos de CI com job de validação e job de tag na branch de destino, projeto do sistema com configuração de CI apontando para o primeiro, branches protegidas, merge sem squash; verificar disparando um pipeline pela API e vendo-o concluir
- [x] 1.3 Verificar manualmente contra o stack, com uma chave de implantação e git por SSH, os três comportamentos incertos: opção de criar merge request em push sem commits novos, autor do merge request e do pipeline com chave de implantação, push de chave de implantação em branch protegida que aceita merges; registrar os resultados em `design.md` (D7 e Riscos) e ajustar o script de 1.2 e as tarefas 8.1 e 9.3 se algum resultado contrariar o desenho
- [x] 1.4 Documentar o stack em `docs/testes.md` (como subir, memória necessária, não rodar junto das outras suítes E2E); verificar que os comandos documentados funcionam como escritos

## 2. Vínculo com o remoto e chave de implantação

- [ ] 2.1 Migração Alembic e modelo `system_git_remotes` (design D2); verificar com `alembic upgrade head` e `alembic downgrade -1` num banco efêmero
- [ ] 2.2 Serviço de configuração: validação do endereço SSH, padrões de branch, restrição a quem gerencia o sistema, ativar e desativar o vínculo, com registro de auditoria; verificar com testes unitários de URL aceita e recusada (`ext::`, `file://`, HTTP) e de permissão
- [ ] 2.3 Geração do par ed25519, cifra da chave privada e troca de chave; verificar com teste unitário que a privada nunca aparece em retorno de serviço nem em detalhe de auditoria e que dois sistemas recebem chaves diferentes
- [ ] 2.4 Token de API opcional: cadastro, troca e remoção cifrados, endereço da API derivado do host do repositório ou informado, nunca exibido nem em auditoria (design D7); verificar com testes unitários de derivação de endereço e de que o token não aparece em retorno de serviço nem em detalhe de auditoria
- [ ] 2.5 Remover o vínculo, a chave, o token e a retransmissão na exclusão definitiva do sistema; verificar com teste de integração

## 3. Retransmissão, conexão e envio

- [ ] 3.1 Adicionar `openssh-client` a `deploy/portal.Dockerfile`, a configuração `git_relays_dir` em `config.py` e o volume do portal nos arquivos compose e no chart Helm; verificar com `docker build`, `ssh -V` na imagem e `helm template`
- [ ] 3.2 Criar a fixture de integração com servidor git por SSH efêmero (container com `sshd` e repositório bare); verificar com um teste que clona e empurra usando uma chave gerada na fixture
- [ ] 3.3 Estender o backend git por driver com exportar e importar pacote, em base64 no Kubernetes (design D1); verificar com teste de integração nos dois drivers que um pacote exportado e reimportado preserva os commits
- [ ] 3.4 Implementar a invocação remota: chave em diretório temporário em `tmpfs`, `GIT_SSH_COMMAND`, `known_hosts` temporário, `GIT_ALLOW_PROTOCOL=ssh`, tempo limite de 30 s, limpeza em sucesso e erro (design D2); verificar com teste de integração que nenhum arquivo de chave sobra após sucesso e após falha
- [ ] 3.5 Teste de conexão com obtenção e confirmação da impressão digital do servidor, e recusa quando a chave do servidor muda; verificar com teste de integração trocando a chave do servidor da fixture
- [ ] 3.6 Repositório de retransmissão e envio por pacote, sem `--force`; verificar com teste de integração que o commit chega ao remoto com o editor como autor e que um push rejeitado não reescreve nada
- [ ] 3.7 Vínculo inicial: criar a branch de trabalho quando ausente e recusar histórico não relacionado; verificar os dois casos com teste de integração
- [ ] 3.8 Encaixar o envio depois do checkpoint em `agent_queue._execute`, no checkpoint manual e no rollback; falha vira estado `pending` com motivo e é reenviada no checkpoint seguinte e por "Enviar agora" (design D6); verificar com teste de integração derrubando o servidor da fixture durante uma execução
- [ ] 3.9 Teste de integração provando que a chave privada não existe no sistema de arquivos, no ambiente nem nos processos do container do sistema após envios, nos dois drivers, e que o agente não alcança o servidor git

## 4. Aba Repositório

- [ ] 4.1 Criar a aba em `ui/system_detail.py`, visível a quem gerencia o sistema: endereço, branches, chave pública com botão de copiar, teste de conexão com confirmação da impressão digital, ativar, desativar e gerar nova chave; seguir os tokens de `ui/theme.py`; verificar com teste E2E de visibilidade para dono e para usuário sem gestão
- [ ] 4.2 Exibir o estado do vínculo (sincronizado, envio pendente, divergente, erro) com motivo, último commit enviado e avisos; verificar com teste E2E no stack com GitLab
- [ ] 4.3 Primeiro cenário da suíte `portal/tests/e2e_gitlab`: configurar o repositório, cadastrar a chave pela API, testar a conexão, pedir algo no chat e ver o commit na branch de trabalho do GitLab; verificar que passa duas vezes seguidas a partir de stack limpo

## 5. Sincronização

- [ ] 5.1 Recebimento do remoto pela retransmissão e importação do pacote no repositório do sistema; verificar com teste de integração que commits feitos direto no remoto chegam ao repositório do sistema
- [ ] 5.2 Integração por avanço rápido e por merge sem conflito, com checkpoint `origin = remote` (design D3, casos 1 e 2); verificar cada caso com teste de integração, incluindo que a app reflete a mudança
- [ ] 5.3 Encaixar a sincronização antes do harness em `agent_queue._execute`, não bloqueante em erro de rede, e a ação "Sincronizar agora" que recusa com execução em andamento (design D6); verificar com teste de integração que a execução parte do código mergeado
- [ ] 5.4 Cenário E2E no stack com GitLab: mergear um merge request "humano" na branch de trabalho pela API e ver a execução seguinte partir do código novo, com envio aceito

## 6. Alterações não salvas

- [ ] 6.1 Bloqueio da integração quando há alterações sem checkpoint e commits a trazer: execução encerrada sem chamar o harness, com mensagem no chat, e recusa em "Sincronizar agora" (design D4); verificar com teste de integração que o workspace não muda e o harness não é chamado, e que sem commits a trazer nada é bloqueado
- [ ] 6.2 Ações "Salvar como checkpoint" e "Descartar alterações não salvas" na aba Repositório, a segunda com confirmação, ambas seguidas da integração; verificar os dois desfechos com teste de integração e teste E2E

## 7. Divergência

- [ ] 7.1 Caso de conflito: `merge --abort`, estado `diverged`, lista de arquivos, envios suspensos, chat disponível, sem nova tentativa automática de integração (design D3, caso 3); verificar com teste de integração que a árvore de trabalho fica sem marcas de conflito
- [ ] 7.2 Ações "Resolver no workspace" e "Cancelar resolução", e conclusão do merge no checkpoint seguinte só sem marcas de conflito (design D5); verificar os três desfechos (concluída, incompleta, cancelada) com teste de integração
- [ ] 7.3 Ação "Adotar a versão do remoto" com confirmação listando os checkpoints não enviados, referência de proteção e checkpoint `origin = remote` (design D5); verificar com teste de integração que o workspace reflete o remoto, que um checkpoint deixado de lado é restaurável e que nada muda no remoto
- [ ] 7.4 Exibir a divergência e suas duas saídas na aba Repositório, e registrar sincronizações, divergências, resoluções e adoções na auditoria; verificar com teste E2E e teste de integração das entradas de auditoria

## 8. Promoção e proteção do pipeline

- [ ] 8.1 Teste do token e ação "Solicitar promoção" pela API do GitLab: consulta de MR aberto entre as branches, abertura quando não houver, endereço de criação preenchido sem token ou com token recusado, recusa com pendência ou divergência (design D7); verificar com testes unitários contra um servidor HTTP falso e com o cenário E2E de 9.1
- [ ] 8.2 Proteção de `.gitlab-ci.yml` na raiz para arquivo novo e para arquivo rastreado modificado, com aviso registrado (design D8); verificar os dois casos com teste de integração e que o arquivo vindo do remoto é preservado
- [ ] 8.3 Criar `tests/bdd/features/system-git-remote.feature` com os cenários da spec e verificar que `uv run pytest tests/bdd -k system_git_remote` passa

## 9. Jornada completa e documentação

- [ ] 9.1 Completar a suíte `portal/tests/e2e_gitlab`: cadastrar o token de projeto, solicitar promoção e conferir o merge request; solicitar de novo e ver o mesmo MR; pipeline de validação concluído; mergear e ver a tag criada pelo pipeline da branch de destino; promoção sem token mostra o link de criação; chave só leitura recusada no envio; verificar que a suíte passa duas vezes seguidas a partir de stack limpo
- [ ] 9.2 Escrever o ADR do repositório remoto (retransmissão no portal, chave e token fora do container, git por SSH e API só para o merge request de promoção) e atualizar `docs/adr/README.md` e `docs/seguranca.md`; verificar que os nomes de configuração citados existem no código
- [ ] 9.3 Escrever o guia de preparação do projeto no GitLab (chave de implantação cadastrada por quem pode empurrar na branch de trabalho, token de projeto com papel Developer e escopo `api`, proteção das duas branches, merge sem squash, pipeline em projeto separado, quem aprova, conforme o resultado de 1.3) e atualizar `docs/guia-de-uso.md` com a aba Repositório; verificar seguindo o guia num projeto novo do stack

## 10. Verificação integrada

- [ ] 10.1 Rodar `uv run pytest tests/unit tests/bdd tests/integration` e as suítes `tests/e2e`, `tests/e2e_oidc` e `tests/e2e_gitlab`, cada uma no seu stack; verificar que todas passam
- [ ] 10.2 Subir o stack de desenvolvimento e verificar manualmente que um sistema sem repositório configurado se comporta como antes desta change
- [ ] 10.3 Rodar `openspec validate add-system-git-remote --strict` e verificar que passa

## Workflow follow-up

- Arquivar a change depois da revisão.
- Propor a change seguinte, do sistema "só implantação" do portal de produção, que depende desta.
