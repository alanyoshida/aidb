# Tasks

## 1. Imagens

- [x] 1.1 Nos dois Dockerfiles de `base-image/`, Node 22.23.5 e npm 11.21.3 (`ARG NPM_VERSION`), conforme D1. Nos três Dockerfiles, `apt-get upgrade` antes do `install` (D2). Verificar com as três imagens construídas do zero e o trivy 0.76.2 pinado, severidade alta e crítica:
  - base e claude-code sem nenhum achado de biblioteca e sem nenhum achado com correção;
  - portal sem nenhum achado com correção;
  - `node`, `npm`, `npx`, `openspec` e `claude` respondendo nas imagens novas;
  - `.github/scripts/scan-image-secrets.sh` sem achado nas três.

## 2. Chart

- [x] 2.1 Contexto restrito no portal, no initContainer das migrações e no Postgres, com os `emptyDir` de D4 e D5. Verificar:
  - `helm lint` e os testes do chart;
  - o trivy do repositório sem KSV-0014 e KSV-0118 em `deployment.yaml` e `postgres.yaml`;
  - antes do chart, portal e Postgres com `--read-only` e as mesmas capabilities, com `docker run`: o Postgres aceita conexões e o portal responde no health.

## 3. Exceções

- [x] 3.1 Criar `.trivyignore.yaml` com as quatro exceções de D6, cada uma com motivo e limitada ao arquivo. Passar `--ignorefile .trivyignore.yaml` no `trivy-repo` da CI. Verificar:
  - o trivy do repositório, com os mesmos argumentos da CI, sem nenhum achado alto ou crítico;
  - um Dockerfile de rascunho como root em outra pasta ainda é achado (DS-0002). Apagar depois.

## 4. Validação no cluster

- [x] 4.1 Validação de D7 num cluster kind descartável novo, apagado no fim, sem tocar nos clusters existentes.

## 5. Documentação

- [x] 5.1 Em `docs/testes.md`, o que acontece com os achados altos e críticos, as exceções e o pino do Node e do npm. Em `docs/seguranca.md`, o contexto restrito do portal e do Postgres no cluster.

## 6. Verificação final

- [x] 6.1 `pytest -n auto tests/unit tests/bdd`, `openspec validate --all --strict` e `actionlint`.

- Resultado:
  - **Trivy nas imagens**, alto e crítico, antes e depois:

    | Imagem | Antes | Depois | Com correção (antes e depois) | Críticos (antes e depois) |
    |---|---|---|---|---|
    | portal | 128 | 127 | 1 e 0 | 1 e 1 |
    | base | 206 | 166 | 40 e 0 | 3 e 0 |
    | claude-code | 206 | 166 | 40 e 0 | 3 e 0 |

    O crítico que sobra no portal é o `openssh-client` (CVE-2026-60002), sem correção no Debian. O que sobra nas três é só do Debian sem correção.
  - **Trivy no repositório:** zero achados altos e críticos com as exceções. O DS-0002 de rascunho foi achado.
  - **Checagem de segredos:** nenhum segredo nas três imagens novas.
  - **Testes:** 792 passados.
  - **Docker com `--read-only`:** o primeiro teste do portal falhou em `/dynamic` e passou com ele em `tmpfs`.
  - **Kind descartável `aidb-sec-test`** (apagado):
    - a marca gravada no banco antes do upgrade estava lá depois;
    - as migrações rodaram no initContainer;
    - o portal ficou com `CapEff` zerado e sem escrita em `/app`;
    - login e criação do sistema `teste-endurecimento` funcionaram.

    O primeiro chat falhou com `Read-only file system: '/workspaces'`, do harness fake. Com o `emptyDir` em `/workspaces`, o chat terminou e o checkpoint apareceu.
