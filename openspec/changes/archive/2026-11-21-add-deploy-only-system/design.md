# Design

## Context

Motivação e escopo: ver `proposal.md`. Requisitos: ver `specs/`.

Estado atual observado no código:

- O supervisor (`base-image/afsupervisor/supervisor.py`) sobe o agente pelo perfil apontado por `AIDB_AGENT_PROFILE` e a app com `app/.venv/bin/python main.py` (ou o Python do sistema, sem venv). Reinicia a app quando a assinatura dos arquivos de `app/` muda — diretórios ocultos, como `.venv`, ficam fora da assinatura. Sem `app/main.py`, serve uma página provisória.
- A app gerada declara dependências com `uv` em `app/` (`pyproject.toml`, `uv.lock`); o `.venv` não entra no Git. Num clone, o ambiente não existe.
- `provisioning.provision_system` monta o ambiente do container com o perfil do agente, a credencial de LLM ou o token do broker, as conexões e o proxy de saída. `default_https_allowlist` libera os registros de pacote e o host do LLM ou do broker.
- `health_monitor` checa a saúde da app periodicamente; `is_healthy` aceita qualquer resposta HTTP abaixo de 500 (o gate de identidade responde 403 sem token, e isso é app no ar).
- A change `add-system-git-remote` deixou pronto: chave de implantação por sistema, identidade do servidor, cópia de retransmissão, pacotes entre retransmissão e repositório do sistema (`git_sync`), e o repositório do sistema fora do workspace (`git_backend`).

Decisões já tomadas com o usuário: tipo por sistema com trava por instalação; implantação manual ou automática por sistema; detecção por consulta ou webhook; o automático só implanta tags nunca implantadas; manifesto gravado pela homologação; schema do banco fora do escopo.

## Goals / Non-Goals

**Goals:**

- Um portal de produção não executa agente nem guarda credencial de LLM para nenhum sistema.
- Só roda em produção código de um commit contido na branch de destino do repositório.
- Uma implantação que falha nunca deixa o sistema fora do ar se a versão anterior funcionava.
- Reaproveitar a mecânica de chave, identidade e retransmissão da change anterior.

**Non-Goals:**

- Migração de schema do banco de produção.
- Implantação canário, réplicas, ou janela de manutenção.
- Verificar assinatura de tag (tags assinadas) — a garantia é a tag estar na branch de destino, que é protegida.
- Promover entre portais por API: o elo continua sendo o GitLab.

## Decisions

### D1 — Tipo do sistema e papel da instalação

- `systems.kind`: `agent` (padrão, inclusive para os existentes) ou `deploy_only`, fixado na criação como `execution_mode`.
- `APPAIFORGE_INSTALLATION_ROLE`: `development` (padrão) ou `production`. Em `production`, `create_system` recusa `agent` e `provision_system` recusa qualquer sistema `agent` (estado `error` com o motivo, inclusive na reconciliação). O formulário de criação esconde a escolha de tipo e de provedor de LLM.
- Num portal `development` os dois tipos convivem; útil para testar o fluxo de produção sem outro portal.

Alternativa descartada: papel da instalação como único critério (sem tipo por sistema). Escolha do usuário: tipo por sistema mais trava.

### D2 — Container sem agente

`provision_system` para `deploy_only`: não escreve config de agente nem perfil, não define `AIDB_AGENT_PROFILE`, nenhuma credencial ou token de LLM, e define `AIDB_SYSTEM_KIND=deploy_only`. O supervisor, nesse modo, não sobe harness e não roda `ensure_openspec`. A allow-list do proxy de saída fica só com os registros de pacote (sem host de LLM nem broker). Conexões, gate de banco, proxy de saída e identidade da app seguem iguais.

A imagem continua sendo a imagem base da plataforma (a mesma do perfil `opencode`), que já tem `uv` e o Python da app.

### D3 — Configuração de implantação e histórico

- O vínculo com o repositório reutiliza `system_git_remotes` (endereço, chave, identidade do servidor, branch de destino). Para `deploy_only`, a branch de trabalho não é usada, e a chave é cadastrada no GitLab sem escrita.
- Nova tabela `deploy_settings` (uma por sistema): `tag_pattern` (padrão `v*`), `mode` (`manual` | `automatic`), `detection` (`polling` | `webhook`), `webhook_secret_encrypted`, `last_checked_at`.
- Nova tabela `deployments`: `system_id`, `tag`, `commit_sha`, `trigger` (`manual` | `polling` | `webhook`), `actor_id`, `status` (`running` | `succeeded` | `failed` | `rolled_back`), `detail`, `previous_sha`, `created_at`, `finished_at`. A versão atual é a última com `succeeded`.

### D4 — Listar e verificar tags

Na cópia de retransmissão: `git ls-remote --tags` (tags anotadas resolvidas pelo `^{}`), filtro pelo padrão (`fnmatch`), ordenação por versão (componentes numéricos comparados como números). Para implantar a tag T:

1. `fetch` da branch de destino e de `refs/tags/T` na retransmissão;
2. `merge-base --is-ancestor <commit de T> <ponta da branch de destino>`; se não, recusa;
3. pacote do commit para o repositório do sistema (`refs/aidb/deploy/<commit>`), pela mesma troca de pacotes da change anterior.

O commit verificado é o que fica registrado e é o que vai para o workspace, independentemente do que a tag aponte depois.

### D5 — Ordem da implantação: dependências antes do código

O supervisor reinicia a app quando os arquivos de `app/` mudam, mas ignora `.venv`. A implantação:

1. **Pré-checagens** (sem mexer em nada): `app/main.py` existe no commit; manifesto de conexões (D8).
2. **Dependências**: se `app/uv.lock` do commit difere do da versão atual, o portal grava `pyproject.toml` e `uv.lock` do commit num diretório temporário dentro do container e roda `uv sync --frozen --project <tmp>` com `UV_PROJECT_ENVIRONMENT=/workspace/app/.venv`, como o usuário da app, com o proxy de saída do container. Falhou: implantação `failed`, nada mais muda.
3. **Código**: `reset --hard <commit>` e `clean -fdq` no repositório do sistema (o `.venv` é ignorado e fica). A troca dos arquivos faz o supervisor reiniciar a app.
4. **Saúde**: o portal espera a app responder (`is_healthy`) em três checagens seguidas dentro do prazo (`APPAIFORGE_DEPLOY_HEALTH_TIMEOUT`, padrão 90 s). Não ficou saudável: volta ao commit anterior pelos passos 2 e 3 e registra `rolled_back`.

A execução de comando no container da app vira uma operação do driver (`exec_in_app`): `exec_run` com o usuário da app no Docker; `exec` no container `agent` do pod no Kubernetes (que, num sistema `deploy_only`, só roda a app).

### D6 — Serialização e consistência

Uma implantação por sistema por vez (o lock por sistema de `git_sync`). Uma implantação `running` encontrada na subida do portal é marcada `failed` ("interrompida") e a reconciliação garante que o workspace esteja no commit da última implantação `succeeded`.

### D7 — Modo automático, consulta e webhook

- **Regra**: lista as tags do padrão; pega a mais nova; implanta só se nenhuma implantação (qualquer status) daquele sistema tem essa tag. Assim rollback manual e tag que falhou não são repetidos.
- **Consulta periódica**: uma thread como o `health_monitor`, a cada `APPAIFORGE_DEPLOY_POLL_INTERVAL` (padrão 60 s), percorre os sistemas `deploy_only` ativos em modo automático com detecção `polling`.
- **Webhook**: `POST /hooks/gitlab/{system_id}`, fora da autenticação de sessão. Exige `X-Gitlab-Token` igual ao segredo do sistema (comparação em tempo constante); qualquer outro caso responde 401 sem efeito. Um webhook válido só agenda a mesma verificação da consulta, em segundo plano, e responde 202 — o corpo é ignorado. O segredo é gerado pelo portal, exibido na aba para cadastro no GitLab e pode ser trocado.
- O GitLab precisa alcançar o portal de produção para o webhook; quando não alcança, a consulta periódica atende.

### D8 — Manifesto de conexões

- Arquivo `.aidb/manifest.json` na raiz do repositório: `{"version": 1, "connections": [{"name": "vendas", "kind": "postgres"}]}`.
- **Homologação**: em `checkpoints.commit_all`, para sistema com repositório ativo, o portal reescreve o arquivo a partir da tabela `db_connections` antes do `git add` — o que o agente tiver escrito nele é sobrescrito.
- **Produção**: lê o arquivo do commit (`git show <commit>:.aidb/manifest.json`); compara pelos nomes normalizados como em `DATABASE_URL_<NOME>`; faltando, recusa listando. Sem arquivo, segue com aviso.

### D9 — Interface

Para `deploy_only`, a página do sistema não tem Chat nem Checkpoints; ganha a aba **Implantação**: repositório (reaproveitando os blocos de chave, endereço e identidade da aba Repositório, com o texto "só leitura"), padrão de tags, versões com "Implantar" por linha, versão atual, histórico, modo automático e detecção, e o endereço e o segredo do webhook. Conexões, Domínios, Editor (somente leitura), Configurações e Auditoria continuam.

## Risks / Trade-offs

- [O GitLab precisa alcançar o portal de produção para o webhook] → A consulta periódica é a alternativa sem entrada de rede; o guia descreve as duas.
- [Instalar dependências exige saída para o PyPI a partir do container] → A allow-list padrão já libera os registros de pacote; com internet desligada no sistema, só versões com o mesmo lock implantam, e o motivo aparece no histórico.
- [`uv sync` no ambiente em uso enquanto a versão anterior roda] → A versão anterior pode perder uma dependência removida até o reinício, segundos depois; aceito.
- [App que sobe e cai em seguida] → Três checagens de saúde seguidas dentro do prazo, não uma.
- [Tag movida para outro commit] → Implanta e registra o commit verificado no momento; recomendar tags protegidas no guia.
- [Mudança de schema não acompanha a versão] → Fora do escopo; o manifesto só cobre a existência das conexões.

## Migration Plan

1. Migração Alembic: `systems.kind` (padrão `agent`), `deploy_settings`, `deployments`. Rodar antes de reiniciar o portal.
2. Imagem base com o modo `deploy_only` do supervisor; imagem do portal sem mudança de pacote.
3. Portais existentes continuam `development`: nada muda para os sistemas atuais. Um portal de produção é uma instalação nova com `APPAIFORGE_INSTALLATION_ROLE=production`.

Reversão: a versão anterior do portal ignora as tabelas novas; sistemas `deploy_only` existentes ficariam sem supervisão de implantação até a volta.
