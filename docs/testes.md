# Testes (três camadas — ADR 0016)

← [README](../README.md)

```bash
cd portal
uv sync                                  # deps (Python 3.12)
docker compose -f ../deploy/docker-compose.yml up -d --build   # stack para E2E

uv run pytest -n 8 tests/unit tests/bdd  # unitários e BDD em paralelo (~2 min; ~9 min sem -n)
uv run pytest tests/integration          # Docker real + Postgres efêmero
uv run pytest tests/e2e                  # browser (Playwright) contra o stack, do zero
```

**Paralelismo (`-n`, pytest-xdist):** só para `tests/unit` e `tests/bdd`. Cada processo é uma sessão
própria e sobe o seu Postgres efêmero, então os testes não disputam tabelas. As suítes de
integração e E2E rodam sem `-n`: criam containers e Pods com nomes fixos, usam um único cluster
`kind` e falam com um stack único, que limpam no começo.

A suíte E2E roda contra um **stack dedicado e isolado** (porta 8081, harness sempre fake, bancos e workspaces próprios) — nunca toca no portal nem nos sistemas do ambiente real:

```bash
docker compose -f deploy/docker-compose.e2e.yml up -d --build
cd portal && uv run pytest tests/e2e     # browser (Playwright), do zero, no stack 8081
```

O modo SSO tem seu **próprio stack** (o modo de autenticação fica travado na base): portal na
porta 8082 com `AUTH_MODE=oidc` e um Keycloak local (8180) com o realm de teste — ver
[Autenticação](autenticacao.md#e2e-com-keycloak-local). Não rode as duas suítes E2E ao mesmo tempo.

```bash
docker compose -f deploy/docker-compose.e2e-oidc.yml up -d --build
cd portal && uv run pytest tests/e2e_oidc
```

O vínculo de um sistema com um repositório remoto (change `add-system-git-remote`) tem um **terceiro
stack**: portal na porta 8083 com harness fake, GitLab CE (API em 8929, SSH em 2229) e GitLab Runner
com executor shell, em versões fixadas. O GitLab pede alguns GB de memória e leva de 4 a 5 minutos
para responder na primeira subida; não rode junto com os outros stacks E2E. O script de inicialização
é idempotente e cria o token de root, registra o runner e prepara os projetos `aidb/ci-templates`
(pipeline dos sistemas) e `aidb/sistema-e2e` (branches `main` e `homolog` protegidas, merge sem squash,
merge só com pipeline verde, CI apontando para o pipeline do outro projeto).

```bash
docker compose -f deploy/docker-compose.e2e-gitlab.yml up -d --build
python3 deploy/e2e-gitlab/init.py
cd portal && uv run pytest tests/e2e_gitlab
```

Para recomeçar o GitLab do zero, remova também os volumes: `docker compose -f
deploy/docker-compose.e2e-gitlab.yml down -v`. O token de root e as senhas do arquivo compose e de
`deploy/e2e-gitlab/init.py` valem só para esse stack.

## CI (GitHub Actions)

O workflow `.github/workflows/ci.yml` roda em cada push de qualquer branch, em PRs vindas de fork e em cada release publicada. Numa PR deste repositório, o status do push no commit da cabeça já vale para a PR.

| Job | O que roda | Bloqueia |
|---|---|---|
| `testes` | `uv run pytest -n auto tests/unit tests/bdd` e os testes de `base-image/` (claude-code-shim, dbproxy, gated-mcp, httpproxy), pasta por pasta | sim |
| `specs` | `openspec validate --all --strict` | sim |
| `chart` | `helm lint deploy/helm/appaiforge-portal` | sim |
| `segredos` | gitleaks no histórico inteiro, com `.gitleaks.toml` | sim |
| `imagens` | build de portal, base e claude-code, checagem de segredos em cada imagem (`.github/scripts/scan-image-secrets.sh`) e vulnerabilidades pelo trivy | só os segredos |
| `trivy-repo` | trivy nas dependências, na configuração (Dockerfiles e chart) e em segredos do repositório | não |
| `publicar` | só numa release: publica as três imagens no GHCR ([Operação](operacao.md#publicar-uma-release)) | — |

- **Testes de unidade como o uid 1000 na CI.** O portal dá o workspace dos sistemas ao uid do agente (1000) e roda o git deles como esse uid. Parte dos testes também sobe containers com `appaiforge/base:<versão>`. Por isso o job constrói a imagem base e roda os testes como um usuário de uid 1000, que é o ambiente em que a suíte passa na máquina de desenvolvimento. Rodando à mão como outro usuário, ou sem a imagem base, esses testes falham.
- **Na CI, falta de ferramenta é falha.** Os testes do chart e o de health check do Kubernetes se pulam sem `helm` ou sem `curl` só fora da CI. Com `CI` definido, a falta vira falha, para a CI não ficar verde sem testar.
- **Relatórios do trivy:** ficam na aba *Security → Code scanning* do repositório, um por categoria (`trivy-repo`, `trivy-portal`, `trivy-base`, `trivy-claude-code`). O log de cada job mostra também uma tabela com os achados altos e críticos.
- **Achados altos e críticos.** Os que têm correção são corrigidos. Os de pacotes do Debian sem correção publicada continuam no relatório, e o `apt-get upgrade` dos Dockerfiles traz a correção no primeiro build depois que o Debian a publicar. Os achados de configuração que ficam por desenho, ou que vêm do subchart do Traefik, estão em `.trivyignore.yaml`, cada um com o motivo e limitado ao arquivo onde aparece. Um achado novo do mesmo tipo em outro arquivo volta ao relatório.
- **Fica de fora da CI:** a integração com Docker real (`tests/integration`), os E2E com browser e o kind. Rode-os à mão, como acima.
- **Pinos de versão.** Subir uma versão é mudar os dois lugares:
  - Python 3.12 e uv 0.13.7: no workflow e nos Dockerfiles;
  - Helm 3.19.0: no workflow;
  - OpenSpec 1.15.0: no workflow e em `base-image/Dockerfile`;
  - Node 22.23.5 e npm 11.21.3: nos dois Dockerfiles de `base-image/`;
  - gitleaks, trivy, Alpine e actions: pinados por digest ou commit no workflow e em `.github/scripts/scan-image-secrets.sh`.
- **Exigir os checks antes do merge:** em *Settings → Branches* (ou *Rules*), crie uma regra para `main` que exige os checks `testes`, `specs`, `chart` e `segredos`. É uma configuração do repositório e não vem com o código.

## Cenário com LLM real (`@llm_real`)

O caminho opencode+GLM é validado manualmente (não roda em CI):

1. Suba o stack com `APPAIFORGE_HARNESS_MODE=opencode` e a chave GLM cadastrada (ver [Chave de LLM](llm-e-broker.md)).
2. Crie um sistema apontando para um **banco de homologação** (ADR 0015: a app usa a mesma credencial da conexão, com escrita; o gate de destrutivas protege as operações).
3. No chat: "analise o banco via MCP e crie um CRUD da tabela <x>".
4. Verifique: eventos de ferramenta no chat, app gerada em `/apps/<slug>`, MCP visível em `GET /mcp/status` do container do sistema.
