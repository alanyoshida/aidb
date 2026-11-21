# Tasks

Regra do projeto (`CLAUDE.md`): rodar a análise de impacto do GitNexus antes de editar cada símbolo existente e `detect-changes` antes de cada commit.

## 1. Identidade da instalação

- [ ] 1.1 Migração Alembic com a coluna anulável `portal_instance.installation_id` e o campo no modelo (design D1). Verificar com `alembic upgrade head` e `alembic downgrade -1` num banco efêmero.
- [ ] 1.2 Gravar o identificador na criação da linha e completar uma linha antiga sem valor no mesmo passo de boot que fixa o modo de autenticação. Expor `installation_id()` com cache (design D1). Verificar com testes unitários: banco vazio, reinício mantém o valor, linha antiga ganha valor, usuários e modo de autenticação intactos.

## 2. Containers com dono

- [ ] 2.1 Rótulo `appaiforge.installation` no container do sistema e nos dois sidecars (design D2). Verificar com teste de integração Docker que os três containers de um sistema provisionado têm o rótulo desta instalação.
- [ ] 2.2 Função única de dono e erro `ComputeUnitOwnedElsewhere`, aplicada antes de remover ou adotar pelo nome em `provision`, `remove`, `reconcile_one` e na recriação dos sidecars (design D2). Verificar com testes unitários da decisão: rótulo igual, rótulo diferente, sem rótulo com mesmo sistema, sem rótulo com outro sistema, sem `managed`.
- [ ] 2.3 Provisionamento e reconciliação deixam o sistema em erro com o motivo quando o nome está com outro dono, sem tocar no container. Verificar com teste de integração Docker: um container de outra instalação com o nome do sistema continua rodando, e o sistema fica em erro com a mensagem.
- [ ] 2.4 Container antigo sem rótulo do próprio sistema continua sendo reconhecido e ganha o rótulo ao ser recriado. Verificar com teste de integração Docker.

## 3. Host Docker próprio em produção

- [ ] 3.1 Configuração `allow_shared_docker_host` (padrão falso) e `check_docker_host()` no boot, só com driver Docker e papel de produção, antes da reconciliação (design D3). Verificar com testes unitários da decisão: produção recusa, exceção só avisa, desenvolvimento não checa, host só com containers próprios passa.
- [ ] 3.2 Mensagem lista até dez containers alheios e diz que produção precisa de host próprio. Verificar com teste de integração Docker subindo o app de produção com um container de outra instalação no host: a subida falha com a mensagem e, com a exceção, sobe com aviso.
- [ ] 3.3 Ligar `APPAIFORGE_ALLOW_SHARED_DOCKER_HOST=true` no `portal-prod` de `deploy/docker-compose.e2e-gitlab.yml`. Documentar a configuração em `docs/configuracao.md` como só para testes. Verificar que o nome bate com `config.py`.

## 4. Chart Helm

- [ ] 4.1 Valores `portal.installationRole`, `portal.webhookBaseUrl` e `portal.deploy.*` no `values.yaml` e as env correspondentes no `deployment.yaml`. As de implantação só entram com papel de produção (design D4). Verificar com teste de `helm template` que os valores chegam ao portal e que a renderização com os valores padrão é idêntica à de antes (comparando com a saída do chart em `main`).
- [ ] 4.2 Guardas com papel de produção: `seedDemoAdmin` ligado e `secrets.existingSecret` vazio falham com mensagem (design D4). Verificar com teste de `helm template` para cada caso.
- [ ] 4.3 `templates/ingressroute.yaml` com `portalRoute.*`, desligada por padrão, `priority: 1` e host obrigatório quando ligada (design D5). Verificar com teste de `helm template`: ligada gera a rota com o host, desligada não gera nada, ligada sem host falha.
- [ ] 4.4 `values-production.yaml` de exemplo, e README e NOTES do chart com a instalação de produção e a exigência de `systemsNamespace` próprio. Verificar com `helm lint` usando o arquivo de exemplo, com um Secret de nome fictício.
- [ ] 4.5 Instalar o chart no kind com os valores de produção, num namespace próprio, com a imagem do portal desta branch. Verificar: `/api/health` responde pela rota do portal; criar sistema com agente é recusado; um sistema só implantação é provisionado e a app responde em `/apps/<slug>` pela mesma entrada, mostrando que a rota do portal não captura a do sistema.

## 5. Compose de produção

- [ ] 5.1 `deploy/docker-compose.production.yml` (projeto `aidb-prod`: postgres, traefik, portal) e `deploy/production.env.example` (design D6). Verificar com `docker compose config` que falha sem `APPAIFORGE_SECRET_KEY` e sem a senha do banco, e passa com o arquivo de exemplo preenchido.
- [ ] 5.2 Subir o compose de produção sozinho no host, com as stacks de desenvolvimento e E2E paradas e sem containers de sistema de outras instalações. Verificar: `/api/health` responde; o papel é produção; criar sistema com agente é recusado; o admin de emergência entra; um sistema só implantação é provisionado e o webhook responde 401 sem o segredo. Depois, derrubar com `down -v`.

## 6. Documentação

- [ ] 6.1 Seção "Instalar um portal de produção" em `docs/operacao.md`, com os passos da design D7 e links para `docs/gitlab.md` seção 7 e para o README do chart. Verificar que os comandos do guia são os mesmos usados nas tarefas 4.5 e 5.2.
- [ ] 6.2 ADR curto da isolação por instalação (design D2 e D3) e a linha no índice de ADRs. Verificar que o índice aponta para o arquivo.

## 7. Verificação integrada

- [ ] 7.1 Suítes completas: unitários, BDD, integração (Docker e Kubernetes), E2E local e E2E com GitLab. Verificar que todas passam e que o E2E com GitLab roda com a exceção ligada.
- [ ] 7.2 `openspec validate add-production-portal-install --strict`. Verificar que passa.
