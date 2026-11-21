# Proposal

## Why

O portal de homologação já envia o código de cada sistema a um GitLab, onde a mudança passa por merge request, revisão e pipelines e vira uma tag de versão na branch de destino (change `add-system-git-remote`). Falta o outro lado: um portal de produção, isolado, com banco de produção, que implante só essas versões aprovadas — sem agente, sem chat e sem credencial de LLM. Esta change entrega esse tipo de sistema e a trava que garante que um portal de produção nunca rode agente.

## What Changes

- Novo **tipo de sistema**, escolhido na criação: "com agente" (o comportamento atual) ou "só implantação". O tipo é fixo depois de criado.
- Nova configuração de **papel da instalação**: num portal configurado como produção, criar ou provisionar sistema com agente é recusado.
- Um sistema só implantação nasce **vinculado a um repositório GitLab**, com chave de implantação própria só de leitura (a mesma mecânica de chave, identidade do servidor e cópia de retransmissão da change anterior), branch de destino (padrão `main`) e padrão de tags (padrão `v*`).
- O **container do sistema só implantação** não sobe agente, não recebe token de LLM e não expõe chat nem checkpoints; o supervisor instala as dependências da app a partir do lock (`uv sync --frozen`) quando ele muda e serve a app em `/apps/{slug}` como hoje.
- **Implantação por tag**: o portal lista as tags do repositório que seguem o padrão; implantar uma tag só é aceito se o commit dela estiver contido na branch de destino; o workspace passa a ter exatamente o conteúdo daquele commit; se a app não ficar saudável, o portal volta à versão anterior. Cada implantação fica registrada (tag, commit, quem, quando, resultado).
- **Voltar versão** é implantar uma tag anterior.
- **Modo automático** opcional por sistema: implanta a tag mais nova do padrão, desde que nunca tenha sido implantada antes — um rollback manual permanece até sair uma tag nova. A detecção é por **consulta periódica** ou por **webhook do GitLab**, à escolha por sistema; o webhook só dispara uma verificação, nunca implanta o que vem no corpo da chamada.
- **Manifesto de conexões**: o portal de homologação grava, a cada checkpoint de um sistema com repositório ativo, um arquivo no repositório com os nomes e tipos das conexões de banco da app; o portal de produção bloqueia a implantação de uma tag cujo manifesto exige conexão não cadastrada com aquele nome.

Fora desta change: migração de schema do banco de produção, promoção entre portais por API (o elo continua sendo o GitLab), implantação canário ou com várias réplicas, e outras forjas além do GitLab.

## Capabilities

### New Capabilities

- `deploy-only-system`: sistema que só implanta versões aprovadas de um repositório — tipo do sistema, trava por instalação, criação a partir do repositório, container sem agente, implantação por tag verificada, histórico e volta de versão, modo automático com consulta ou webhook, e verificação do manifesto de conexões.

### Modified Capabilities

- `system-git-remote`: acrescenta o manifesto de conexões gravado pelo portal de homologação a cada checkpoint de um sistema com repositório ativo.

## Impact

- **Código do portal**: `models.py` e migração (tipo do sistema, configuração de implantação, histórico de implantações), `services/systems.py` e `ui/system_create.py` (tipo e trava), `provisioning.py` e drivers (container sem agente), `git_sync.py` (tags, verificação, checkout da versão), novo serviço de implantação, `ui/system_detail.py` (aba Implantação; abas de agente ocultas), rota de webhook, tarefa periódica de verificação, `checkpoints.py` (manifesto).
- **Imagem base / supervisor**: modo sem agente e instalação de dependências da app pelo lock.
- **Configuração**: papel da instalação (`APPAIFORGE_INSTALLATION_ROLE`), intervalo da consulta periódica; o portal de produção precisa ser alcançável pelo GitLab para usar webhook.
- **Testes**: unitários, BDD da capability, integração com o servidor git por SSH efêmero, e a suíte E2E com GitLab ganha um segundo portal (produção).
- **Documentação**: ADR do sistema só implantação, `docs/gitlab.md` (chave só leitura, webhook), guia de uso e operação.
