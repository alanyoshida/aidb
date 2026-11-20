# Tasks

Regra do projeto (`CLAUDE.md`): rodar a análise de impacto do GitNexus antes de editar cada símbolo existente e `detect-changes` antes de cada commit.

## 1. Confirmação do risco

- [x] 1.1 Escrever o teste de integração que planta hook, filtro em `.gitattributes`, `core.fsmonitor` e `include.path` no workspace e observa se algo executa durante um checkpoint, nos drivers Docker e Kubernetes; rodar contra o código atual e registrar o resultado (o que executa, com qual identidade, dentro ou fora do confinamento) para o ADR da tarefa 4.5

## 2. Repositório fora do workspace (driver Docker)

- [x] 2.1 Adicionar a configuração `gitdirs_dir` em `config.py` e o volume correspondente, montado só no portal, em `deploy/docker-compose.yml`, `docker-compose.e2e.yml` e `docker-compose.e2e-oidc.yml`; verificar com `docker compose config` que nenhum container de sistema monta esse volume
- [x] 2.2 Criar a interface de backend git por driver (executar git no repositório do sistema, remover repositório) e a implementação Docker com `GIT_DIR`/`GIT_WORK_TREE` explícitos, ambiente limpo e uid/gid do dono do workspace (design D1, D3); verificar com teste unitário que o ambiente passado ao git não herda `HOME` nem configuração global
- [x] 2.3 Implementar a migração preguiçosa do histórico (design D4): copiar `objects/` do `.git` antigo e apontar a branch para o último `git_sha` registrado; verificar com teste de integração que um checkpoint antigo é restaurável depois da migração e que referências adulteradas no `.git` antigo são ignoradas
- [x] 2.4 Reescrever `checkpoints.py` sobre o backend (commit, status, listagem), deixando de criar `.git` no workspace; verificar que `tests/unit/test_checkpoint_openspec.py` e os testes de integração de checkpoint existentes passam
- [x] 2.5 Remover o repositório do sistema em `provisioning.delete_system`, preservando-o no arquivamento; verificar com teste de integração que o diretório some na exclusão definitiva e permanece no arquivamento
- [x] 2.6 Verificar, com harness opencode e claude-code reais, se um sistema novo sem `.git` no workspace mantém sessões e identidade de projeto; se não mantiver, fazer o supervisor criar um repositório vazio com a identidade do agente; registrar o resultado no design (Open Questions) e verificar com `tests/integration/test_opencode_instructions.py` e `test_claude_code_e2e.py`
- [x] 2.7 Verificar que o teste da tarefa 1.1 passa no driver Docker (nada executa, nada é lido) e que um arquivo restaurado continua gravável pelo uid do agente
- [x] 2.8 Criar `tests/bdd/features/workspace-repository.feature` com os cenários da spec e verificar que `uv run pytest tests/bdd -k workspace_repository` passa
- [x] 2.9 Atualizar `docs/seguranca.md` com o novo local do repositório e o que deixa de ser executável; verificar que os caminhos e nomes de configuração citados existem no código

## 3. Repositório fora do workspace (driver Kubernetes)

- [x] 3.1 Adicionar o PVC `gitdir-<slug>` e o container auxiliar `git` ao pod do sistema, sem montar o PVC no container `agent` (design D2); verificar em `tests/integration/test_kubernetes_driver.py` a composição do pod e os mounts de cada container
- [x] 3.2 Implementar o backend Kubernetes: git por `exec` no container `git`, incluindo a migração preguiçosa do histórico; verificar com teste de integração que checkpoint e listagem funcionam e que um checkpoint antigo é restaurável
- [x] 3.3 Detectar pod sem o container `git` e recusar a operação com mensagem clara, e fazer a reconciliação recriar esses pods; verificar com teste de integração que um pod antigo é recriado e que nenhuma operação cai no caminho de `exec` no container `agent`
- [x] 3.4 Remover o PVC do repositório na exclusão definitiva, junto do PVC do workspace; verificar com teste de integração
- [x] 3.5 Atualizar o chart em `deploy/helm` para a nova configuração e os volumes; verificar com `helm template` que o manifesto renderiza
- [x] 3.6 Estender `tests/integration/test_driver_parity.py` com checkpoint, hook plantado e restauração nos dois drivers, e verificar que o teste da tarefa 1.1 passa no driver Kubernetes
- [x] 3.7 Atualizar `docs/driver-kubernetes.md` com o container auxiliar e o PVC; verificar que os nomes citados batem com o driver

## 4. Rollback que preserva o histórico

- [x] 4.1 Migração Alembic adicionando `checkpoints.origin` com padrão `run` e o campo no modelo; verificar com `alembic upgrade head` e `alembic downgrade -1` num banco efêmero
- [x] 4.2 Reimplementar `rollback` como commit de restauração registrado com `origin = restore`, sem commit quando a árvore é idêntica (design D5); verificar com teste de integração, nos dois drivers, que checkpoints posteriores continuam restauráveis
- [x] 4.3 Ajustar a aba Checkpoints: mostrar a origem de cada ponto, informar "nada a restaurar" e atualizar a lista após restaurar; verificar com teste E2E em `tests/e2e`
- [x] 4.4 Atualizar `tests/bdd/features/agent-harness.feature` com os cenários novos do requisito de checkpoints; verificar que a suíte BDD passa
- [x] 4.5 Escrever o ADR que substitui a parte de rollback do ADR 0009 e registra o repositório fora do workspace e o resultado da tarefa 1.1, e atualizar `docs/adr/README.md`; verificar que o ADR 0009 aponta para o novo

## 5. Verificação integrada

- [x] 5.1 Rodar `uv run pytest tests/unit tests/bdd tests/integration` e as suítes `tests/e2e` e `tests/e2e_oidc`, cada uma no seu stack; verificar que todas passam
  - Rodado em 2026-11-20: unitários + BDD 533/533; integração 81/81 (`test_https_proxy.py` 4/4 e `test_claude_code_e2e.py` 1/1 repetidos sem desvio depois que a rede voltou; as falhas anteriores eram de rede, confirmado rodando o mesmo arquivo no commit anterior à change nas mesmas condições); `tests/e2e` 37/37 e `tests/e2e_oidc` 8/8 com as duas stacks construídas por `docker compose up -d --build`.

- [x] 5.2 Subir o stack de desenvolvimento com um sistema criado antes da change e verificar manualmente: histórico migrado, checkpoint antigo restaurável, chat e app funcionando
  - Feito na stack E2E (descartável), não na de desenvolvimento, para não migrar os sistemas reais: sistema criado pelo código anterior à change, depois trocado para o código novo. Ver design D3 (normalização de dono e restauração atômica, acrescentadas a partir desta verificação).
- [x] 5.3 Rodar `openspec validate isolate-workspace-repository --strict` e verificar que passa

## Workflow follow-up

- Arquivar a change depois da revisão.
- Aplicar em seguida a change `add-system-git-remote`, que depende desta.
