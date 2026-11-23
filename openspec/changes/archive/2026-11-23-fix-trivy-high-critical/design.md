# Design

## Context

O trivy 0.76.2 local, nas imagens construídas do zero (`--pull --no-cache`) e no repositório, deu os achados altos e críticos da proposta. Duas decisões vieram do operador:
- os CVEs do Debian sem correção ficam no relatório;
- o chart é endurecido, e as demais configurações viram exceções justificadas.

## Goals / Non-Goals

**Goals:**
- zerar os achados altos e críticos que têm correção, nas três imagens;
- zerar os achados de configuração do chart do próprio projeto;
- deixar cada exceção restante escrita, com motivo e escopo de um arquivo.

**Non-Goals:**
- portal sem root (mexe no `chown` dos workspaces e no git por uid no compose; fica para uma change própria);
- ligar o bloqueio do trivy na CI (com CVEs do Debian sem correção, a CI ficaria vermelha sem nada a fazer);
- trocar a base `python:3.12-slim`.

## Decisions

### D1. Node 22.23.5 com npm 11.21.3

Todos os 40 achados por imagem estão no npm embutido em `/usr/local/lib/node_modules/npm`. O resultado por combinação, medido numa imagem só com o Node:

| Combinação | Achados altos e críticos |
|---|---|
| Node 22.14.0 com o npm 10.9.2 embutido | 40 |
| Node 22.23.5 com o npm 10.9.9 embutido | 10 (`pacote` 19, `sigstore` 3, `brace-expansion`, `ip-address`) |
| Node 22.23.5 com o npm 11.21.3 | 0 |
| Node 22.23.5 com o npm 12.2.3 | 0 |

O npm 11 é o menor major que zera os achados e aceita Node `^20.17.0 || >=22.9.0`. O Node continua na linha 22, a mesma que o opencode, o OpenSpec e a CLI do Claude já usam. `NPM_VERSION` é `ARG`, como as demais versões pinadas dos Dockerfiles.

### D2. `apt-get upgrade` no build

A imagem `python:3.12-slim` atrasa em relação às correções do Debian: o `zlib1g` do portal tinha correção publicada. `apt-get upgrade -y --no-install-recommends` antes do `install` pega essas correções. O build já não é byte a byte reprodutível, porque o `apt-get install` resolve a versão do dia.

### D3. CVEs do Debian sem correção ficam no relatório

São cerca de 125 por imagem: krb5, openssh-client (com 1 crítico no portal), git, util-linux, curl, perl, sqlite, openssl, ncurses, systemd e expat. Nas bases há ainda os 40 do `linux-libc-dev`. Não existe versão corrigida para instalar.

`--ignore-unfixed` esconderia esses achados da aba Security. Deixá-los visíveis mostra o risco real, e D2 traz cada correção sozinho.

### D4. Portal com contexto restrito, ainda como root

No chart, o portal fala com a API do Kubernetes e opera o git de cada sistema por exec no Pod (`KubernetesGitBackend`). Ele não faz `chown` nem troca de uid, que só existem no compose. Por isso:
- **contexto:** `capabilities.drop: [ALL]`, `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, e `seccompProfile: RuntimeDefault` no Pod. Vale também para o initContainer das migrações;
- **volumes `emptyDir`:** o portal com a raiz somente leitura precisou de três:
  - `/tmp`, para os temporários do Python e os pacotes do git;
  - `/dynamic`, porque `edge.write_portal_router()` grava a rota do portal para o Traefik do compose em todo startup, mesmo no cluster, onde ninguém a lê;
  - `/workspaces`, porque o harness fake (`portal.harnessMode: fake`, padrão do chart) grava a app de exemplo no `workspaces_dir` local.

  Os dois últimos apareceram como `Read-only file system` na validação (D7). `/configs` e `/git-relays` já eram `emptyDir`. Os segredos de SSH vão para `/dev/shm`, que continua gravável.

Rodar o portal como não-root no chart funcionaria. Mas a imagem é a mesma do compose, que precisa de root, e deixaria de ser o que roda nos dois modos. Fica para a change que tirar o root do portal.

### D5. Postgres com as capabilities do entrypoint oficial

O entrypoint de `postgres:16-alpine` começa como root, acerta o dono de `PGDATA` e de `/var/run/postgresql` e troca para o usuário `postgres` com `su-exec`. Para isso precisa de `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `SETGID` e `SETUID`, e só delas. Raiz somente leitura com `emptyDir` em `/var/run/postgresql` (socket do `pg_isready`) e em `/tmp`.

`runAsUser` do postgres com `fsGroup` foi descartado. O `fsGroup` dá permissão de grupo ao volume, e o Postgres recusa um diretório de dados que não esteja em `0700` ou `0750`. Mudar `PGDATA` para uma subpasta quebraria as instalações existentes. Com as cinco capabilities, nada muda no volume.

### D6. Exceções em `.trivyignore.yaml`, por arquivo

O formato YAML do trivy aceita `paths` por exceção. Um `.trivyignore` simples ignoraria a regra no repositório inteiro. Com `paths`, o mesmo achado num arquivo novo continua no relatório: um Dockerfile de rascunho como root, criado na validação, foi achado com DS-0002. Cada entrada tem um `statement` com o motivo. O trivy só lê o YAML com `--ignorefile`, que o job `trivy-repo` passa.

### D7. Validação num cluster kind descartável

Num cluster `kind` novo, criado e apagado só para isto (os clusters existentes ficam intocados):
1. instala o chart de antes, com a imagem de antes, e grava uma marca no banco;
2. faz o upgrade para o chart e a imagem novos;
3. confere que a marca está no banco, as migrações rodaram no initContainer endurecido e o portal responde sem capabilities nem escrita na raiz;
4. pelo portal, cria um sistema descartável, roda o chat fake e confere o checkpoint.

## Risks / Trade-offs

- **[Um caminho do portal que grave na raiz e não foi exercitado]** → a validação cobriu login, criação de sistema, chat e checkpoint. Um erro `Read-only file system` em outro fluxo se resolve com mais um `emptyDir`, e aparece no log com o caminho.
- **[npm 11 muda comportamento do `npx` dos MCP servers]** → o `npx` funciona na imagem nova. O OpenSpec e a CLI do Claude respondem com as mesmas versões de antes.
- **[`apt-get upgrade` torna o build menos previsível]** → é só correção de segurança do Debian estável. A suíte e a checagem de segredos rodam em toda imagem.
- **[Os CVEs do Debian sem correção continuam]** → visíveis na aba Security, e corrigidos no primeiro build depois da correção publicada (D2, D3).
