# Proposal

## Why

As releases já chegaram à v1.10.0, mas a instalação inteira ainda se identifica como `0.1.0`:
- o portal, no `/health`, no OpenAPI e no `service.version` da telemetria;
- o chart (`version`, `appVersion` e a tag padrão da imagem do portal);
- as imagens padrão dos sistemas (`appaiforge/base` e `appaiforge/claude-code`);
- os comandos de build da documentação.

Não dá para saber, por uma instalação ou por um traço no APM, qual release está rodando.

## What Changes

- **Uma versão para tudo, igual à da release.** A versão sai de um lugar só, o pacote do portal, e passa a valer para:
  - o `/health`, o OpenAPI e o `service.version` padrão da telemetria;
  - o `version` e o `appVersion` do chart e a tag padrão da imagem do portal (`values.yaml` e `values-production.yaml`);
  - as imagens padrão dos sistemas, `appaiforge/base:<versão>` e `appaiforge/claude-code:<versão>`;
  - os comandos de build e as tabelas da documentação.
- **A versão desta change é 1.11.0**, a da release que vai levá-la. A v1.10.0 já foi publicada com `0.1.0`, e o código só deve dizer uma versão quando a release dela sai.
- **Um teste trava o alinhamento:** pacote, `uv.lock`, chart, valores e documentação têm de dizer a mesma versão.
- **Procedimento de release documentado:** subir a versão é o primeiro passo de cada release, e o teste aponta o que faltou.
- **BREAKING (operação):** as imagens padrão dos sistemas mudam de tag.
  - No Docker, os containers que já existem continuam na imagem antiga até serem recriados. Um container recriado ou um sistema novo pede a imagem nova, que precisa existir no host.
  - No Kubernetes, a reconciliação recria os Pods de sistema com a imagem nova.

  Nos dois casos, construa (ou publique no registro) `appaiforge/base:1.11.0` e `appaiforge/claude-code:1.11.0` antes de subir o portal. Quem fixa as imagens por configuração (`APPAIFORGE_BASE_IMAGE`, `portal.baseImage` etc.) não é afetado.
- **Fora do escopo:**
  - versionar separadamente o chart, o broker ou as imagens;
  - publicar imagens num registro;
  - CI de release.

## Capabilities

### New Capabilities

(nenhuma)

### Modified Capabilities

- `portal-installation`: requisito novo de versão única da instalação. Portal, chart e imagens padrão dos sistemas levam a versão da release.

## Impact

- **Portal:**
  - `appaiforge/__init__.py`: a versão passa a vir do pacote instalado;
  - `pyproject.toml` e `uv.lock`, com a versão nova;
  - `config.py`, com as imagens padrão derivadas da versão.
- **Chart:** `Chart.yaml`, `values.yaml`, `values-production.yaml` e README.
- **Docs:** `README.md`, `docs/operacao.md`, `docs/configuracao.md`, `docs/driver-kubernetes.md` e `deploy/pilot-k8s/README.md`.
- **Testes:**
  - os que fixam `0.1.0` (perfis de agente e a imagem base dos testes de integração);
  - um teste novo de alinhamento.
- **Ambiente de desenvolvimento:** as imagens `appaiforge/base:1.11.0` e `appaiforge/claude-code:1.11.0` precisam ser construídas no host. Os sistemas existentes não são tocados.
