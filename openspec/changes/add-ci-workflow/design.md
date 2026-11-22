# Design

## Context

- **Suíte local** (`docs/testes.md`): `uv run pytest -n 8 tests/unit tests/bdd`. Cada processo do xdist sobe o seu Postgres efêmero pelo testcontainers, o que exige Docker. Os runners `ubuntu-latest` do GitHub têm Docker.
- **Pulos atuais:**
  - os testes do chart (`test_helm_chart.py`) se pulam sem `helm`, e os de health check do Kubernetes sem `curl`;
  - os de sandbox se pulam sozinhos sem Landlock, e isso continua: confinamento real é opt-in (marker `sandbox`).
- **Testes de `base-image/`** (claude-code-shim, dbproxy, gated-mcp, httpproxy): 87 testes, rápidos. Só rodam pasta por pasta, porque há dois `test_sidecar.py` e eles colidem numa coleta única. Usam o ambiente do portal.
- **Imagens do projeto:**
  - `deploy/portal.Dockerfile`, com contexto na raiz, usada pelo portal e pelo broker;
  - `base-image/Dockerfile` e `base-image/Dockerfile.claude-code`, com contexto em `base-image/`.

  Os padrões do portal e do chart usam nomes locais: `appaiforge/portal`, `appaiforge/base` e `appaiforge/claude-code`, com a tag da versão.
- **Pinos do projeto:**
  - Python 3.12;
  - uv 0.13.7;
  - OpenSpec 1.15.0;
  - Helm 3.19.
- **Contexto de build:** o `.dockerignore` da raiz exclui `.git`, `.env`, `tests`, `docs`, `openspec` e `*.md`, mas não `*.env` nem chaves. `base-image/` não tem `.dockerignore`, e os Dockerfiles dela copiam pastas inteiras (`gated-mcp`, `dbproxy`, `httpproxy`, `afsupervisor`, `claude-code-shim`). Nenhum Dockerfile declara `ARG` ou `ENV` com segredo.
- **Varredura de hoje** (feita para esta change):
  - **gitleaks 8.30.1 no sistema de arquivos exportado das imagens:** 1 achado no portal e 4 na base e na claude-code, todos da regra `generic-api-key` em arquivos do sistema: `/usr/include/linux/netfilter*`, `/usr/include/linux/nl80211.h`, `/usr/lib/x86_64-linux-gnu/perl*` e `/usr/local/include/node`.
  - **gitleaks 8.30.1, histórico inteiro:** 8 achados, todos falsos positivos. São os tokens fictícios `glpat-aidbE2E…` das fixtures de E2E, `glpat-segredo-de-teste-123` e `sup3r-senha-do-banco` nos testes unitários, e o placeholder `Bearer SUA_CHAVE` em `README.md` e `docs/llm-e-broker.md`.
  - **trivy 0.76.2:**
    - dependências do repositório: nada;
    - configuração: 1 crítico, no subchart do Traefik, que lê Secrets, e 16 altos. Os altos são o portal rodando como root, `readOnlyRootFilesystem`, `securityContext` e afins, no chart e em manifestos arquivados;
    - segredos nas imagens (`--scanners secret --image-config-scanners secret`): 0 nas três;
    - imagens, altos e críticos com correção: portal 1 (`zlib1g`), base cerca de 96 (`tar` e outros pacotes do npm global, e libs do MariaDB), claude-code cerca de 40 (npm). Há muitos outros do Debian sem correção.
- **O chart vem com dependência:** o subchart do Traefik fica versionado em `charts/`, com `Chart.lock`, então `helm lint` não precisa de rede.
- **O repositório é público e não tem workflow.** As releases são criadas com `gh release create` no merge commit.

## Goals / Non-Goals

**Goals:**
- cada commit numa branch passa pela suíte rápida e pela busca de segredos antes do merge;
- as três imagens são construídas e escaneadas em toda execução, e publicadas só por uma release;
- nenhuma imagem com segredo chega ao registry;
- um teste que depende de ferramenta não vira verde por falta dela;
- privilégio mínimo: cada job só recebe as permissões do que faz.

**Non-Goals:**
- cache de camadas de imagem e matriz de versões de Python;
- bloquear por vulnerabilidade, o que fica para uma change que corrija as imagens;
- multi-arquitetura e assinatura (cosign);
- mudar os nomes padrão das imagens.

## Decisions

### D1. Gatilhos

- **`push` em qualquer branch:** roda os jobs de verificação e constrói as imagens.
- **`pull_request`:** só quando a PR vem de outro repositório (`github.event.pull_request.head.repo.full_name != github.repository`). Uma PR da mesma origem não roda duas vezes, porque o push já rodou no commit da cabeça dela. Esse status serve para a proteção de branch.
- **`release: published`:** roda os jobs de verificação e o de publicação.
- **`workflow_dispatch`, com o input `tag`:** publica as imagens de uma release que já existe, como a v1.11.0, que saiu antes desta CI. Só roda a partir da `main`.

Também há `concurrency` por ref, cancelando a execução anterior da mesma branch. Ela não cancela uma publicação.

Alternativa descartada: só `pull_request`. A CI só rodaria depois de abrir a PR, e o fluxo do projeto arquiva antes de abrir a PR.

### D2. Jobs

| Job | Quando | O que faz | Permissões |
|---|---|---|---|
| `testes` | push, PR de fork, release | uv 0.13.7, Python 3.12 e Helm 3.19.0; `uv sync --frozen`; `uv run pytest -n auto tests/unit tests/bdd`; um passo por pasta de `base-image/` | `contents: read` |
| `specs` | idem | Node 22, `@fission-ai/openspec@1.15.0` e `openspec validate --all --strict`, com telemetria e checagem de update desligadas | `contents: read` |
| `chart` | idem | `helm lint deploy/helm/appaiforge-portal` | `contents: read` |
| `segredos` | idem | gitleaks no histórico inteiro (D6) | `contents: read` |
| `trivy-repo` | push, PR de fork | trivy `fs` com dependências, configuração e segredos, enviado como SARIF (D7) | `contents: read`, `security-events: write` |
| `imagens` | push, PR de fork | matriz `portal`/`base`/`claude-code`: `docker build`, checagem de segredos na imagem, bloqueando (D10), e trivy `image` em SARIF (D7). Não publica | `contents: read`, `security-events: write` |
| `publicar` | release, dispatch | depende de `testes`, `specs`, `chart` e `segredos`. Confere a versão, constrói, checa segredos (D10, bloqueando), escaneia e envia ao GHCR (D8) | `contents: read`, `packages: write`, `security-events: write` |

Os jobs são separados para uma falha não esconder outra. A matriz de imagens usa `fail-fast: false`.

### D3. Actions pinadas por commit, scanners por digest

- **Actions de terceiros**, referenciadas pelo SHA do commit da release, com a tag num comentário: `actions/checkout`, `actions/setup-node`, `astral-sh/setup-uv`, `azure/setup-helm` e `github/codeql-action/upload-sarif`.
- **Gitleaks e trivy** rodam pelas imagens oficiais, pinadas por digest (`ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:…` e `aquasec/trivy:0.76.2@sha256:…`), e não pelas actions deles. Isso deixa menos código de terceiros no caminho, a mesma versão roda local e na CI, e evita a licença que a action do gitleaks exige de organizações.
- **Credenciais:** `permissions: contents: read` no topo, e cada job só amplia o que precisa (D2). O checkout usa `persist-credentials: false`.

### D4. Falta de ferramenta é falha na CI

Nos dois módulos com `skipif(shutil.which(...) is None)`, o pulo só vale fora da CI: `... is None and not os.environ.get("CI")`. O GitHub define `CI=true`. Na máquina do desenvolvedor, o comportamento não muda.

Alternativa descartada: um plugin que falha em qualquer pulo. Os de sandbox e os de Landlock devem continuar se pulando.

### D5. Validação local do workflow

O workflow é validado com o `actionlint` (imagem `rhysd/actionlint` pinada), antes do push.

### D6. Gitleaks bloqueando, com allowlist explícita

- **Execução:** `gitleaks git` no histórico inteiro (checkout com `fetch-depth: 0`), com `--redact` e um relatório SARIF só no log. Achado novo é falha.
- **`.gitleaks.toml`:** estende as regras padrão (`[extend] useDefault = true`) e acrescenta uma allowlist que casa só com os valores fictícios conhecidos: `glpat-aidbE2E`, `glpat-segredo-de-teste-`, `sup3r-senha-do-banco` e `Bearer SUA_CHAVE`. Cada entrada leva um comentário dizendo onde mora e por que é falsa.

Alternativa descartada: `.gitleaksignore` com fingerprints. A fingerprint inclui commit e linha, e qualquer edição daquelas linhas gera um achado novo.

Alternativa descartada: excluir as pastas de teste. Um segredo real numa fixture também deve ser pego.

### D7. Trivy só como relatório

- **Execução:** `trivy fs --scanners vuln,misconfig,secret` no repositório e `trivy image` em cada imagem construída, com `--exit-code 0` e `--format sarif`.
- **Envio:** o upload vai com uma `category` por alvo (`trivy-repo`, `trivy-portal`, `trivy-base`, `trivy-claude-code`). Assim, os alertas de um alvo não apagam os de outro na aba Security.
- **PR de fork:** o token não tem `security-events: write`. Os passos de upload são pulados, e o relatório fica só no log.
- **Saída no log:** uma tabela resumida, com severidade alta e crítica.
- **Exclusões:** `.claude/` e `openspec/changes/archive/`, onde ficam manifestos antigos que não são instalados. Os alertas de configuração do chart real continuam.

Alternativa descartada: bloquear já. A CI nasceria vermelha por vulnerabilidades do Debian sem correção. O bloqueio, com `--ignore-unfixed` e um limiar, entra numa change que corrija as imagens.

### D8. Publicação no GHCR

- **Nomes:** `ghcr.io/alanyoshida/appaiforge/portal`, `…/base` e `…/claude-code`, todos em minúsculas.
- **Tags:** `<versão>` e `latest`. A versão é a tag da release sem o `v`.
- **Guarda:** antes de construir, o job confere que a versão é igual ao `version` do `portal/pyproject.toml` no commit da tag. Se não for, falha sem publicar.
- **Build:** `docker build` simples, `linux/amd64`, com labels OCI:
  - `org.opencontainers.image.source=https://github.com/alanyoshida/aidb`, que liga o pacote ao repositório;
  - `version`;
  - `revision`.
- **Ordem:** constrói, checa segredos na imagem (D10, um achado para o job), escaneia vulnerabilidades (D7, só relatório), faz `docker login ghcr.io` com o `GITHUB_TOKEN` e envia. O login só acontece depois da checagem de segredos, então uma imagem reprovada nunca tem como ser enviada.
- **Dispatch:** faz checkout da tag pedida e segue o mesmo caminho.

Alternativa descartada: `docker/build-push-action`. Sem cache nem multi-arquitetura, ela só acrescenta uma action de terceiros.

Alternativa descartada: publicar também na `main`. O operador escolheu só releases.

### D9. Padrões das imagens e uso do GHCR

Os padrões não mudam. `docs/operacao.md` mostra como usar o GHCR:
- **compose:** `APPAIFORGE_BASE_IMAGE` e `APPAIFORGE_CLAUDE_CODE_IMAGE`, ou `docker pull` seguido de `docker tag` para o nome local;
- **chart:** `image.repository`, `portal.baseImage` e `portal.claudeCodeImage`.

Os pacotes nascem privados. Para puxar sem login, o operador os torna públicos nas configurações do pacote, e isso vira um passo do procedimento de release.

### D10. Nenhuma imagem com segredo chega ao registry

Três camadas: as duas primeiras evitam que o segredo entre, e a terceira bloqueia a imagem que o tenha mesmo assim.

1. **Contexto de build.**
   - O `.dockerignore` da raiz ganha `**/.env`, `**/.env.*`, `**/*.env`, com `!**/*.env.example`, mais `**/*.pem`, `**/*.key`, `**/*.p12`, `**/id_rsa*`, `**/id_ed25519*`, `**/.npmrc`, `**/.pypirc` e `**/.netrc`.
   - Um `base-image/.dockerignore` novo leva os mesmos padrões, mais `**/__pycache__` e `**/.pytest_cache`.
   - Nada que está no Git hoje fica de fora, então o conteúdo das imagens não muda.
2. **Dockerfiles.** Um teste unitário (`test_container_hygiene.py`) confere:
   - que nenhum Dockerfile do projeto declara `ARG` ou `ENV` cujo nome contenha `TOKEN`, `SECRET`, `PASSWORD`, `PASSWD`, `API_KEY` ou `PRIVATE_KEY`. Um valor assim ficaria no histórico da imagem;
   - que os dois `.dockerignore` têm os padrões de segredo do item 1.
3. **Imagem construída, antes de qualquer push.** Dois detectores diferentes, os dois bloqueando:
   - **trivy:** `image --scanners secret --image-config-scanners secret --exit-code 1`, que olha as camadas e a configuração (`ENV`, labels, histórico de comandos);
   - **gitleaks:** `dir --redact` no sistema de arquivos da imagem, exportado com `docker create` e `docker export`, com a configuração própria `.gitleaks-image.toml`. Ela estende as regras padrão e tem uma allowlist só dos caminhos do sistema que dão falso positivo hoje: `/usr/include/linux/`, `/usr/lib/x86_64-linux-gnu/perl` e `/usr/local/include/node/`. São arquivos do Debian e do Node, não do projeto.

   Os valores achados saem mascarados no log.

   A checagem roda no job `imagens`, em toda branch, e no `publicar`, antes do `docker login`. A imagem publicada é a mesma que passou pela checagem, porque é a mesma construção no mesmo job.

Alternativa descartada: só o trivy. Os dois motores têm regras diferentes, e o custo de rodar o gitleaks é baixo (segundos, num sistema de arquivos de 1 GB).

Alternativa descartada: varrer só `/app` e `/opt`. Um segredo copiado por engano pode cair em qualquer pasta. A allowlist por caminho de sistema é mais estreita que uma lista de pastas a varrer.

## Risks / Trade-offs

- **[Testcontainers lento ou instável no runner]:** cada worker do xdist sobe um Postgres. O `-n auto` usa os núcleos do runner, quatro nos públicos. → Se ficar instável, fixar `-n 2`.
- **[Limite de download da base do trivy]:** cada execução baixa a base de vulnerabilidades. → Usar `--db-repository` com o espelho público da AWS como alternativa. Se o download falhar, o relatório falha, mas não bloqueia.
- **[Build das três imagens em todo push]:** a base e a claude-code instalam pacotes do npm e levam alguns minutos. → Os jobs correm em paralelo com os testes. O cache de camadas fica como melhoria futura.
- **[Falso positivo novo numa imagem depois de atualizar o Debian ou o Node]:** a CI bloqueia. → O log mostra a regra e o caminho, com o valor mascarado. Se for um arquivo do sistema, a allowlist de `.gitleaks-image.toml` ganha o caminho, numa PR revisada.
- **[Allowlist do gitleaks larga demais]:** um segredo real com o mesmo prefixo seria ignorado. → As entradas casam com os valores fictícios inteiros, não com prefixos genéricos como `glpat-`.
- **[Publicação de uma release com testes vermelhos]:** `publicar` depende dos jobs de verificação da mesma execução. → Se um falhar, nada é publicado.
- **[Pacote privado]:** quem não tem acesso ao repositório não consegue puxar. → Documentado: tornar os pacotes públicos é uma decisão do operador.
- **[Pinos de ferramenta divergirem do projeto]:** `docs/testes.md` lista onde cada pino mora.
- **[Check verde não impede o merge]:** sem a proteção da branch, um merge com CI vermelha continua possível. → Documentar como torná-la obrigatória. A decisão fica com o operador.

## Migration Plan

1. O merge da PR liga a CI na `main` e em toda branch nova.
2. Depois do merge, um disparo manual (`gh workflow run ci.yml -f tag=v1.11.0`) publica as imagens da v1.11.0. A próxima release publica as dela sozinha.
3. Opcional, pelo operador:
   - tornar os três pacotes públicos;
   - exigir os checks `testes`, `specs`, `chart` e `segredos` na `main`.
4. Rollback: remover `.github/workflows/ci.yml`. Os pacotes já publicados ficam no GHCR.
