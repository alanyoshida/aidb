# Tasks

Regra do projeto (`CLAUDE.md`): rodar a análise de impacto do GitNexus antes de editar cada símbolo existente e `detect-changes` antes de cada commit.

## 1. Tipo do sistema e trava por instalação

- [x] 1.1 Migração Alembic com `systems.kind` (padrão `agent`), `deploy_settings` e `deployments`, e os modelos (design D1, D3); verificar com `alembic upgrade head` e `alembic downgrade -1` num banco efêmero
- [x] 1.2 Configuração `installation_role` (`development` | `production`); `create_system` aceita o tipo e recusa `agent` em produção (design D1); verificar com testes unitários de criação nos dois papéis e de tipo padrão
- [x] 1.3 `provision_system` recusa sistema `agent` num portal de produção, deixando-o em erro com o motivo, também pela reconciliação; verificar com teste de integração
- [ ] 1.4 Formulário de criação: escolha do tipo em desenvolvimento; em produção, "só implantação" fixo e sem provedor de LLM; verificar com teste E2E nos dois papéis
- [x] 1.5 Documentar `APPAIFORGE_INSTALLATION_ROLE` em `docs/configuracao.md`; verificar que o nome bate com `config.py`

## 2. Container sem agente

- [x] 2.1 Supervisor com `AIDB_SYSTEM_KIND=deploy_only`: não sobe harness nem `ensure_openspec`, só a app (design D2); verificar com testes unitários do supervisor
- [x] 2.2 `provision_system` para `deploy_only`: sem config nem perfil de agente, sem credencial nem token de LLM, allow-list só com os registros de pacote; verificar com teste de integração nos dois drivers que o container sobe sem processo de agente e sem variável de LLM
- [x] 2.3 Operação `exec_in_app` nos dois drivers (usuário da app no Docker; container `agent` no Kubernetes) (design D5); verificar com teste de integração nos dois drivers
- [ ] 2.4 Página do sistema `deploy_only` sem Chat nem Checkpoints e com a aba Implantação; o tipo não é editável; verificar com teste E2E

## 3. Repositório de origem e versões

- [x] 3.1 Configuração do repositório para `deploy_only` reaproveitando `system_git_remotes` (chave, identidade do servidor, branch de destino) e `deploy_settings.tag_pattern`; o portal nunca envia nada (design D3); verificar com teste de integração contra o servidor git por SSH de que nenhuma ref remota muda
- [x] 3.2 Listar tags do padrão em ordem de versão, marcando a atual e as já implantadas (design D4); verificar com teste unitário de ordenação (`v1.0.10` > `v1.0.2`) e de filtro, e de integração contra o servidor da fixture
- [x] 3.3 Verificação da tag contra a branch de destino e transferência do commit para o repositório do sistema (design D4); verificar com teste de integração: tag na branch aceita, tag fora recusada, tag movida registra o commit verificado

## 4. Implantação, saúde e histórico

- [x] 4.1 Serviço de implantação com as pré-checagens, dependências antes do código, troca do código e checagem de saúde (design D5), registrando `deployments`; verificar com teste de integração contra a fixture: versão implantada servida em `/apps/{slug}`
- [x] 4.2 Dependências pelo lock: `uv sync --frozen` só quando o lock muda; falha não troca o código; verificar com teste de integração (lock igual não reinstala; dependência inexistente falha e mantém a versão anterior)
- [x] 4.3 Volta automática quando a versão não fica saudável no prazo; verificar com teste de integração com uma versão cuja app quebra ao subir
- [x] 4.4 Uma implantação por sistema por vez e recuperação de implantação interrompida na subida do portal (design D6); verificar com teste de integração
- [ ] 4.5 Aba Implantação: versões com "Implantar", versão atual, histórico e auditoria; rollback é implantar uma tag anterior; verificar com teste E2E

## 5. Modo automático, consulta e webhook

- [x] 5.1 Regra do automático: a tag mais nova do padrão, só se nunca implantada (design D7); verificar com testes unitários (rollback permanece; tag que falhou não repete; modo manual não implanta)
- [x] 5.2 Consulta periódica em thread com intervalo configurável; verificar com teste de integração com intervalo curto
- [x] 5.3 Webhook `POST /hooks/gitlab/{system_id}`: segredo do sistema em tempo constante, 401 sem efeito, corpo ignorado, verificação em segundo plano (design D7); segredo gerado, exibido e trocável na aba; verificar com testes de rota (segredo certo, errado, ausente, corpo com tag inexistente)

## 6. Manifesto de conexões

- [x] 6.1 Homologação: gravar `.aidb/manifest.json` a cada checkpoint de sistema com repositório ativo, só com nome e tipo (design D8); verificar com teste de integração (conexão nova aparece; nenhuma credencial; sistema sem repositório não grava)
- [x] 6.2 Produção: conferir o manifesto do commit antes de implantar, listando conexões faltantes; sem manifesto, segue com aviso; verificar com teste de integração dos três casos
- [x] 6.3 Criar `tests/bdd/features/deploy_only_system.feature` com os cenários da spec e verificar que a suíte BDD passa

## 7. E2E com dois portais e documentação

- [ ] 7.1 Acrescentar um portal de produção (`APPAIFORGE_INSTALLATION_ROLE=production`, porta própria, banco próprio) ao `deploy/docker-compose.e2e-gitlab.yml`; verificar que os dois portais sobem e alcançam o GitLab
- [ ] 7.2 Cenário E2E da jornada: homologação envia e promove; merge e tag pelo pipeline; produção cria o sistema a partir do repositório com chave só leitura, cadastra a conexão do manifesto, implanta a tag e a app responde; nova tag implantada sozinha por webhook; rollback para a anterior permanece; verificar que passa duas vezes seguidas
- [x] 7.3 ADR do sistema só implantação; `docs/gitlab.md` (chave só leitura, webhook); seções em `docs/guia-de-uso.md` e `docs/operacao.md`; verificar que nomes e rótulos citados existem

## 8. Verificação integrada

- [ ] 8.1 Rodar unitários, BDD, integração e as suítes `tests/e2e`, `tests/e2e_oidc` e `tests/e2e_gitlab`, cada uma no seu stack; verificar que todas passam
- [ ] 8.2 Rodar `openspec validate add-deploy-only-system --strict` e verificar que passa

## Workflow follow-up

- Arquivar a change depois da revisão.
