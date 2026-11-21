# Proposal

## Why

A v1.3.0 entregou o sistema só implantação, mas o portal de produção só existe montado dentro da stack E2E com GitLab. Quem for instalar um de verdade não tem chart nem compose prontos: o chart Helm não tem valor para o papel da instalação, o endereço do webhook ou os prazos de implantação, e não expõe o portal, então o GitLab não alcança o webhook. Além disso, sob o driver Docker os containers de sistema se chamam `appaiforge-sys-<slug>` e cada portal os acha pelo nome, sem conferir de quem são. Um portal de produção no mesmo host Docker de um de homologação assumiria o container de um sistema de mesmo slug.

## What Changes

- **Identidade da instalação**: cada portal grava, no primeiro boot, um identificador próprio junto do registro da instalação que já guarda o modo de autenticação. Os containers que o driver Docker cria (sistema e sidecars) levam esse identificador num rótulo.
- **Produção só em host Docker próprio**: sob o driver Docker, o portal de produção recusa subir se o host tem containers gerenciados de outra instalação, e diz quais. Uma configuração de exceção, documentada como só para testes, deixa a stack E2E com GitLab continuar rodando os dois portais no mesmo host.
- **Provisionamento nunca adota container alheio**, nos dois papéis: se já existe um container com o nome do sistema e ele pertence a outro sistema ou a outra instalação, o provisionamento falha com o motivo em vez de removê-lo ou reaproveitá-lo.
- **Chart Helm para produção**:
  - Valores novos: `portal.installationRole`, `portal.webhookBaseUrl` e `portal.deploy.*` (consulta periódica e prazos de saúde).
  - `IngressRoute` opcional para o próprio portal, para que usuários e o webhook do GitLab o alcancem.
  - Arquivo de exemplo `values-production.yaml`.
  - Com papel `production`, o chart recusa renderizar se o admin de demonstração estiver ligado ou sem `secrets.existingSecret`.
- **Compose do portal de produção** (`deploy/docker-compose.production.yml`):
  - Só Postgres, Traefik e portal: sem broker de inferência, LiteLLM, MySQL de demonstração nem observabilidade.
  - Papel `production` e chave secreta obrigatória, sem admin de demonstração.
  - O primeiro admin vem do break-glass ou do OIDC.
- **Guia passo a passo** em `docs/operacao.md`: pré-requisitos, instalação por compose e por Helm, primeiro acesso, ligar ao GitLab, webhook, atualização e backup.

Fora desta change:
- Rodar dois portais no mesmo host Docker em produção (decisão: host próprio).
- Prefixo de nome por instalação.
- Rótulo de instalação nos Pods do driver Kubernetes. Lá o isolamento é um `systemsNamespace` por portal, que o guia exige.
- Migração de schema do banco de produção.

## Capabilities

### New Capabilities

- `portal-installation`: como uma instalação do portal se identifica e se isola das outras (identidade gravada no primeiro boot, rótulo nos containers, recusa de host Docker compartilhado em produção, provisionamento que não adota container alheio), e o empacotamento de uma instalação de produção (valores e guardas do chart Helm, rota do portal, compose de produção).

### Modified Capabilities

(nenhuma)

## Impact

- **Código do portal**:
  - `models.py` e migração: identificador em `portal_instance`.
  - `auth_mode.py` (ou módulo vizinho): gravar e ler o identificador no boot.
  - `drivers/docker_driver.py`: rótulo de instalação e checagem de dono antes de remover ou reaproveitar um container.
  - `main.py`: checagem do host no boot.
  - `config.py`: exceção para host compartilhado.
- **Chart** `deploy/helm/appaiforge-portal`: `values.yaml`, `templates/deployment.yaml`, nova `templates/ingressroute.yaml`, `values-production.yaml`, README e NOTES.
- **Compose**: novo `deploy/docker-compose.production.yml`; `deploy/docker-compose.e2e-gitlab.yml` liga a exceção no portal de produção.
- **Testes**:
  - Unitários: identidade e decisão da checagem.
  - Integração Docker: rótulo, recusa de adoção e recusa de boot.
  - Testes do chart com `helm template`.
  - Instalação do chart em produção no kind.
  - Subida do compose de produção, e a suíte E2E com GitLab repetida.
- **Documentação**: `docs/operacao.md` (guia), `docs/configuracao.md` (nova configuração), README do chart e ADR da isolação por instalação.
