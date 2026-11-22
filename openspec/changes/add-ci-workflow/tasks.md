# Tasks

## 1. Testes que não se pulam na CI

- [x] 1.1 Em `portal/tests/unit/test_helm_chart.py` e `test_kubernetes_health_check.py`, fazer o pulo por falta de `helm` ou `curl` valer só sem `CI` no ambiente (design D4). Verificar com `PATH` sem `helm` (`uv run` com `env PATH=...`):
  - sem `CI`, os testes do chart se pulam;
  - com `CI=true`, eles falham;
  - com `helm` no `PATH`, passam nos dois casos.

## 2. Segredos

- [x] 2.1 Criar `.gitleaks.toml` (design D6), com as regras padrão e a allowlist dos quatro valores fictícios, cada um comentado. Verificar com o gitleaks 8.30.1 pinado em Docker, no histórico inteiro:
  - nenhum achado;
  - num commit de rascunho com um token falso novo no formato de um PAT do GitLab, o gitleaks acha e sai com código diferente de zero. Desfazer depois.

## 3. Nenhum segredo nas imagens

- [x] 3.1 Acrescentar os padrões de segredo ao `.dockerignore` da raiz e criar `base-image/.dockerignore` (design D10, item 1). Criar `portal/tests/unit/test_container_hygiene.py` (item 2). Verificar que:
  - o teste passa;
  - ele falha num rascunho com `ARG GITLAB_TOKEN` num Dockerfile, desfeito depois;
  - as três imagens reconstruídas têm o mesmo conjunto de arquivos de antes (`docker export` e lista comparada, sem diferença).
- [x] 3.2 Criar `.gitleaks-image.toml` com a allowlist dos caminhos de sistema (item 3). Rodar localmente, nas três imagens, o trivy de segredos e o gitleaks no sistema de arquivos exportado, com os comandos exatos que vão para o workflow. Verificar que:
  - os dois saem com zero achados nas três imagens;
  - numa imagem de teste com um arquivo de token falso (`FROM` da imagem do portal mais `COPY` de um `.env` com um PAT fictício do GitLab), os dois acham o token e saem com código diferente de zero. Apagar a imagem de teste depois.

## 4. Workflow

- [x] 4.1 Criar `.github/workflows/ci.yml` com os gatilhos de D1, os jobs e as permissões de D2, as actions pinadas por SHA e os scanners por digest de D3 (os SHAs resolvidos com `gh api` na tag da release), o trivy de D7, a publicação de D8 e a checagem de segredos de D10 antes do `docker login`. Verificar com:
  - `actionlint` pinado em Docker, sem erro;
  - os comandos dos jobs rodados localmente: `pytest -n auto tests/unit tests/bdd`, os quatro de `base-image/`, `openspec validate --all --strict`, `helm lint`, o gitleaks com a configuração nova, o trivy `fs` e o `image` em SARIF, e o build das três imagens com as labels OCI;
  - a guarda de versão de D8, local: com tag `v1.11.0`, passa; com `v9.9.9`, falha.
- [x] 4.2 Documentar:
  - em `docs/testes.md`, o que a CI roda, o que fica de fora, onde mora cada pino de versão, como tornar os checks obrigatórios na `main`, e onde ver os relatórios do trivy;
  - em `docs/seguranca.md`, as três camadas contra segredo nas imagens e o que fazer com um falso positivo;
  - em `docs/operacao.md`, a publicação no GHCR (nomes, tags, disparo manual para uma release antiga), como usar as imagens por configuração ou `docker pull` e `docker tag` (D9), e como tornar os pacotes públicos;
  - no procedimento de release, "CI verde antes do merge" e "a release publica as imagens".

  Verificar que os comandos documentados são os do workflow.

## 5. Verificação no GitHub

- [ ] 5.1 Com o ok do operador para commitar e empurrar a branch, que dispara a CI (D1), conferir com `gh run watch` que `testes`, `specs`, `chart`, `segredos`, `trivy-repo` e `imagens` terminam verdes no commit da branch. Conferir também:
  - nos logs de `testes`, que os testes do chart rodaram, sem pulo;
  - nos logs de `imagens`, que as duas checagens de segredo rodaram nas três imagens, com zero achados;
  - na aba Security, os quatro relatórios do trivy, um por categoria;
  - que `publicar` não rodou.

  Se um job falhar por diferença do runner, corrigir e repetir. Registrar o tempo de cada job.

## Workflow follow-up

- Arquivar a change (sem specs a sincronizar, `skip_specs`) na mesma branch, antes de abrir a PR. Depois, PR e merge.
- **Depois do merge, com o ok do operador:** rodar `gh workflow run ci.yml -f tag=v1.11.0` e conferir as três imagens no GHCR com as tags `1.11.0` e `latest`, e no log que a checagem de segredos rodou antes do `docker login`. É a primeira verificação real de `publicar`.
- **Decisões do operador, fora desta change:**
  - tornar os pacotes públicos;
  - exigir os checks na `main`;
  - uma change para corrigir as vulnerabilidades e ligar o bloqueio do trivy.
