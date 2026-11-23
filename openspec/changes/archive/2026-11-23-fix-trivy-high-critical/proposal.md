# Proposal

## Why

A CI (change `add-ci-workflow`) passou a mostrar os achados do trivy na aba Security. O trivy local, com severidade alta e crítica, achou:
- nas imagens base e claude-code, 40 CVEs cada (3 críticos) no npm 10 que vem embutido no Node 22.14.0 (`tar`, `glob`, `minimatch`, `brace-expansion`, `pacote`, `sigstore`, `ip-address`). Todos têm correção;
- na imagem do portal, o `zlib1g`, com correção publicada pelo Debian depois da imagem `python:3.12-slim`;
- nas três imagens, cerca de 125 CVEs de pacotes do Debian **sem correção publicada**, e 40 dos cabeçalhos do kernel (`linux-libc-dev`, que entram pelo `gcc` das imagens base);
- no repositório, oito configurações:
  - portal e Postgres do chart sem `securityContext` e sem raiz somente leitura (KSV-0014 e KSV-0118);
  - `portal.Dockerfile` e o servidor SSH de teste rodando como root (DS-0002);
  - o RBAC do portal gerenciando rede (KSV-0056);
  - o ClusterRole do subchart do Traefik lendo Secrets (KSV-0041).

## What Changes

- **Imagens base e claude-code:** Node 22.23.5 e npm 11.21.3. Os 40 achados do npm somem. O npm 11 é o primeiro major sem nenhum deles; ele aceita Node 20.17 ou 22.9 em diante.
- **As três imagens:** `apt-get upgrade` antes de instalar os pacotes. Pega o `zlib1g` corrigido agora, e cada correção futura do Debian no primeiro build depois dela.
- **CVEs do Debian sem correção:** continuam no relatório. Não há versão corrigida para instalar. Tirar o `gcc` das bases eliminaria os 40 do `linux-libc-dev`, mas os sistemas deixariam de compilar dependências nativas.
- **Chart, portal e Postgres com contexto de segurança restrito:**
  - sem escalada de privilégio, `seccompProfile: RuntimeDefault` e raiz somente leitura;
  - o portal e o initContainer das migrações sem nenhuma capability;
  - o Postgres só com as cinco capabilities de que o entrypoint oficial precisa;
  - volumes `emptyDir` onde cada um grava fora dos volumes de hoje.

  O portal continua rodando como root.
- **Exceções justificadas em `.trivyignore.yaml`**, cada uma limitada ao arquivo onde aparece:
  - DS-0002 no `portal.Dockerfile` (root por desenho no compose);
  - DS-0002 no servidor SSH de teste;
  - KSV-0056 no RBAC do portal (publica rotas e NetworkPolicy dos sistemas);
  - KSV-0041 no ClusterRole do subchart oficial do Traefik.

  A CI passa `--ignorefile .trivyignore.yaml` no `trivy-repo`.

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

- `portal-installation`: o chart instala o portal e o Postgres com contexto de segurança restrito e raiz somente leitura, sem mudar o que o portal faz.

## Impact

- `base-image/Dockerfile`, `base-image/Dockerfile.claude-code` e `deploy/portal.Dockerfile`.
- `deploy/helm/appaiforge-portal/templates/deployment.yaml` e `postgres.yaml`.
- `.trivyignore.yaml` (novo) e o job `trivy-repo` de `.github/workflows/ci.yml`.
- `docs/testes.md` e `docs/seguranca.md`.
- Nenhuma mudança de código do portal. Uma instalação existente faz upgrade sem migração: a PVC do Postgres e o banco continuam os mesmos.
