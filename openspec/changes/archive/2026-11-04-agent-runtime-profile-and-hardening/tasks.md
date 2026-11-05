# Tasks

## 1. Registro de perfis de runtime no portal

- [x] 1.1 Criar `portal/appaiforge/agent_profiles.py` com o registro declarativo (no formato de `PRESETS` de `services/catalog.py`), contendo o perfil `opencode` com comando, cwd, caminho e formato do config, `credential_env` (literal ou `from_provider`), porta do harness e caminhos legíveis/graváveis; verificar com teste unitário novo em `tests/unit/test_agent_profiles.py` que o perfil padrão é resolvido pelo nome e que um nome desconhecido falha explicitamente
- [x] 1.2 Resolver `credential_env` com o marcador `from_provider` delegando ao catálogo de provedores; verificar com teste unitário que `glm` resolve para `ZHIPU_API_KEY` e `anthropic` para `ANTHROPIC_API_KEY`, preservando o comportamento de `_provider_env` em `provisioning.py`
- [x] 1.3 Serializar o perfil resolvido como JSON em `configs_dir/<slug>/` junto do config do agente, e passar `AIDB_AGENT_PROFILE` no env do container; verificar com teste unitário que o JSON escrito contém o nome da env de credencial e **nenhum** valor de segredo (nem chave de provedor, nem connection string)

## 2. Supervisor dirigido pelo perfil

- [x] 2.1 Remover `HARNESS_CMD` de `base-image/afsupervisor/supervisor.py` e passar a ler comando, cwd e porta do perfil apontado por `AIDB_AGENT_PROFILE`; verificar com os testes de `tests/unit/test_supervisor.py` estendidos, usando o `ProcessRunner` fake, que o agente sobe com o comando do perfil
- [x] 2.2 Tratar perfil ausente ou ilegível como falha explícita, sem recorrer a agente embutido; verificar com teste unitário que o supervisor não spawna agente nenhum e registra a falha
- [x] 2.3 Garantir que a app gerada e o placeholder continuam subindo independentemente do perfil; verificar que os testes existentes de `test_supervisor.py` (backoff, assinatura de mudança, rollback para placeholder) seguem passando sem alteração de expectativa

## 3. Imagem base preparada para não-root

- [x] 3.1 Criar usuário e grupo do agente no `base-image/Dockerfile`, com `HOME` em diretório da imagem com dono ajustado, e declarar `USER` não-root como padrão da imagem; verificar com `docker run --rm <imagem> id` que o usuário padrão não é root
- [x] 3.2 Relocar a instalação do agente para fora de `/root` após o instalador rodar, ajustando dono e symlink; verificar com `docker run --rm <imagem> sh -lc 'command -v opencode && opencode --version'` executando como o usuário não-root
- [x] 3.3 Documentar no `base-image/Dockerfile` (ou no README do repo) que a imagem tem usuário padrão não-root e que o modo antigo o sobrescreve explicitamente; verificar que o texto descreve o comportamento efetivo dos dois modos

## 4. Modo de execução por sistema

- [x] 4.1 Adicionar o campo de modo de execução em `portal/appaiforge/models.py` (dois valores: antigo e reduzido), com default do reduzido no modelo; verificar com teste unitário que um sistema novo nasce no modo reduzido
- [x] 4.2 Criar migração Alembic encadeada ao head atual com `server_default` do modo antigo; verificar com `alembic upgrade head` seguido de `alembic heads` listando um único head, e que as linhas pré-existentes ficam no modo antigo
- [x] 4.3 Expor o modo de execução na consulta do sistema para admin; verificar com teste unitário que o modo aparece nos dados do sistema, permitindo distinguir quem ainda roda no modo antigo

## 5. Identidade de execução reduzida no provisionamento

- [x] 5.1 Aplicar em `provisioning.py`, somente no modo reduzido, `user` não-root, `cap_drop: ALL`, `no-new-privileges` e teto de processos; verificar com teste de integração em `tests/integration/test_provisioning.py` que o container criado roda sem root e sem capabilities (`id` e `capsh --print` dentro do container)
- [x] 5.2 Criar o diretório de workspace de sistemas novos já com o dono do usuário do agente, e manter o modo antigo subindo com root explícito; verificar com teste de integração parametrizado pelos dois modos que cada um sobe e o agente grava no seu workspace
- [x] 5.3 Expor o teto de processos como configuração em `config.py`, ao lado dos outros limites, e calibrar o default; verificar com teste unitário que o valor configurado chega aos kwargs do container
- [x] 5.4 Confirmar que recriação por reconciliação e por `refresh_connections` preserva o modo do sistema; verificar com teste de integração que recriar o container de um sistema de cada modo mantém a identidade de execução original

## 6. Documentação e decisão

- [x] 6.1 Escrever `docs/adr/0018-perfil-de-runtime-do-agente-e-identidade-reduzida.md` em MADR registrando o perfil declarativo, a identidade reduzida e o modo fixado por sistema; verificar que o ADR está indexado em `docs/adr/README.md` com status aceito
- [x] 6.2 Atualizar `README.md` (seção de configuração, com o teto de processos) e `AGENTS.md` (convenção de que o runtime do agente se declara no perfil, não em código de provisionamento); verificar lendo as duas seções que descrevem o comportamento implementado
- [x] 6.3 Marcar a etapa 1 como concluída na tabela de progresso de `docs/roadmap-confinamento-do-agente.md`, anotando que a migração de sistemas antigos ficou fora de escopo; verificar que a tabela e a etapa 1 refletem o entregue

## 7. Verificação integrada

- [x] 7.1 Rodar uma geração real num sistema novo (cenário `@llm_real`, fora de CI) e verificar ponta a ponta: o agente gera a app, o `uv` cria o venv, o checkpoint git é criado, a app responde em `/apps/<slug>` e nada no workspace precisou de root
- [x] 7.2 Registrar o mapa de caminhos que o agente efetivamente escreveu durante 7.1 na etapa 2 do roadmap, como insumo da política de Landlock e da decisão de rootfs somente-leitura; verificar que a etapa 2 do roadmap cita os caminhos observados

## Workflow follow-up

- Arquivar a change após a revisão, sincronizando os deltas para `openspec/specs/`.
- Verificar o resultado arquivado: `agent-runtime` existe como spec vigente e `container-lifecycle` incorporou os requisitos novos.
