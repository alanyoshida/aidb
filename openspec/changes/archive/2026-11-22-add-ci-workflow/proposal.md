# Proposal

## Why

O repositório não tem CI. As últimas releases criaram testes de guarda:
- versão alinhada entre pacote, chart e docs;
- processors da borda iguais nos três Collectors;
- `openspec validate --all --strict` em 29 de 29.

Só que eles protegem apenas quando alguém os roda à mão antes do merge. Faltam ainda três coisas:
- nada procura segredos commitados;
- nada mostra as vulnerabilidades das imagens;
- as imagens só existem se cada operador as construir no próprio host.

## What Changes

- **Um workflow do GitHub Actions** (`.github/workflows/ci.yml`) que roda em cada push de branch, em PRs vindas de fork e em cada release publicada.
- **Testes, specs e chart:**
  - `pytest` de `tests/unit` e `tests/bdd` em paralelo, com o Postgres efêmero do testcontainers, e os testes dos componentes da imagem base (`base-image/*`);
  - `openspec validate --all --strict`;
  - `helm lint` do chart.
- **Gitleaks, bloqueando:** procura segredos no histórico inteiro, com os valores mascarados no log. Os 8 achados de hoje são falsos positivos: tokens fictícios das fixtures de E2E e de testes, e o placeholder `SUA_CHAVE` dos exemplos de `curl`. Eles entram numa allowlist explícita em `.gitleaks.toml`. Um segredo novo faz a CI falhar.
- **Trivy, só como relatório:** varre as dependências, a configuração (Dockerfiles e chart) e as três imagens construídas. O resultado vai para a aba Security do GitHub (SARIF) e não falha a CI. Hoje há achados altos e críticos nas imagens, a maioria do Debian sem correção, e alertas de endurecimento no chart. Corrigi-los e ligar o bloqueio fica para uma change própria.
- **Nenhuma imagem com segredo chega ao registry.** Antes de qualquer push, cada imagem construída passa por dois detectores, e um achado bloqueia:
  - o de segredos do trivy, nas camadas e na configuração da imagem (`ENV`, labels, histórico);
  - o gitleaks, no sistema de arquivos exportado da imagem.

  A mesma checagem roda em toda branch, para o problema aparecer antes do merge. Hoje as três imagens dão zero achados no trivy. No gitleaks, os únicos achados são 4 falsos positivos da regra genérica em arquivos do sistema operacional (cabeçalhos em `/usr/include`, `/usr/local/include/node` e um módulo do Perl), que entram numa allowlist só desses caminhos.
- **Prevenção no build:**
  - o `.dockerignore` da raiz e um `.dockerignore` novo em `base-image/` excluem arquivos de segredo (`.env`, `*.env` exceto os `.example`, chaves `*.pem`/`*.key`/`id_*`, `.npmrc`, `.pypirc`, `.git`). Hoje a raiz só exclui `.env`, e `base-image/` não tem nenhum, embora os Dockerfiles dela copiem pastas inteiras;
  - um teste confere que nenhum Dockerfile declara `ARG` ou `ENV` com nome de segredo.
- **Build das imagens em toda execução:** portal (que o broker também usa), base e claude-code são construídas e escaneadas. Nas branches e nas PRs, nada é publicado.
- **Publicação no GitHub Container Registry, só nas releases:**
  - uma release publicada (`gh release create`) envia as três imagens para `ghcr.io/alanyoshida/appaiforge/{portal,base,claude-code}`, com as tags `<versão>` e `latest`;
  - a publicação só acontece com os testes verdes, e se a versão da tag for igual à do `pyproject`;
  - um disparo manual publica as imagens de uma release que já existe, como a v1.11.0.
- **Padrões não mudam.** O portal e o chart continuam apontando para os nomes locais (`appaiforge/base:<versão>` etc.). Os docs mostram como usar as imagens do GHCR por configuração.
- **Ferramentas e actions pinadas:**
  - Python 3.12, uv, Helm, OpenSpec, gitleaks e trivy nas versões do projeto;
  - actions de terceiros pinadas por commit;
  - imagens dos scanners pinadas por digest.
- **Permissões mínimas por job:**
  - leitura do repositório por padrão;
  - escrita de resultados de segurança só nos jobs que enviam SARIF;
  - escrita de pacotes só no job de publicação.

  Nenhum segredo além do `GITHUB_TOKEN`.
- **Testes que dependem de ferramenta não se pulam em silêncio na CI.** Na CI, a falta de `helm` ou `curl` passa a ser falha.
- **Docs:**
  - `docs/testes.md` explica a CI;
  - `docs/operacao.md` explica a publicação, como usar as imagens do GHCR e como tornar os pacotes públicos, e o procedimento de release passa a dizer que a release publica as imagens.
- **Fora do escopo:**
  - integração com Docker real, E2E com browser e kind;
  - imagens multi-arquitetura (só `linux/amd64`);
  - assinatura das imagens;
  - corrigir as vulnerabilidades e os alertas do trivy;
  - exigir os checks na proteção da `main`;
  - tornar públicos os pacotes do GHCR, que nascem privados e são uma configuração do operador.

## Capabilities

### New Capabilities

(nenhuma)

### Modified Capabilities

(nenhuma: é ferramenta de desenvolvimento e de entrega, sem mudança de comportamento do produto. Os padrões das imagens não mudam. A change declara `skip_specs`)

## Impact

- **Arquivos novos:** `.github/workflows/ci.yml`, `.gitleaks.toml`, `.gitleaks-image.toml` e `base-image/.dockerignore`. Muda o `.dockerignore` da raiz.
- **Testes:** `portal/tests/unit/test_helm_chart.py` e `test_kubernetes_health_check.py`, no critério de pular. Um teste novo verifica os Dockerfiles e os `.dockerignore`.
- **Docs:** `docs/testes.md` e `docs/operacao.md`.
- **GitHub:**
  - cada push numa branch roda a CI;
  - cada release publica pacotes no GHCR do dono do repositório;
  - os resultados do trivy aparecem em Security, em "Code scanning".

  O repositório é público, então os minutos dos runners hospedados não são cobrados.
- **Código do portal, chart e imagens:** nada muda.
