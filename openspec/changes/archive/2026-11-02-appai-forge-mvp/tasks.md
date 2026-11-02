# Tasks

Convenção de testes (design D13): toda task verifica seu trabalho na camada que couber — unitários (pytest), BDD (feature pytest-bdd derivada dos cenários das specs, em `tests/bdd/features/`) e E2E pelo browser (Playwright, em `tests/e2e/`). Nenhuma task fica sem verificação automatizada, exceto os spikes marcados como manuais.

Convenção de decisões (ADRs 0014–0016, índice em `docs/adr/README.md`): qualquer decisão arquitetural ou de produto tomada durante a implementação é registrada como ADR sequencial em `docs/adr/` (formato MADR, PT-BR) e referenciada no design.md; decisões existentes já têm ADR (mapa no design.md).

## 1. Setup do monorepo, stack do portal e infraestrutura de testes

- [x] 1.1 Criar a estrutura do monorepo (`portal/`, `base-image/`, `deploy/`) com `pyproject.toml` do portal e verificar que os diretórios e arquivos esperados existem
- [x] 1.2 Criar o compose do stack do portal (Postgres, Traefik, portal) com healthchecks e verificar com `docker compose up` que o portal responde em `/` via Traefik
- [x] 1.3 Criar o modelo de dados completo (usuários, grupos, vínculos, sistemas, conexões, sessões de chat, runs, checkpoints, uso de tokens, guidelines) com migração Alembic inicial e verificar que `alembic upgrade head` cria todas as tabelas
- [x] 1.4 Criar comando CLI de bootstrap que cria o usuário admin inicial e verificar que o admin consegue autenticar-se no portal
- [x] 1.5 Configurar as três camadas de teste: pytest (unitários), pytest-bdd com estrutura `tests/bdd/features/` por capability, pytest-playwright com stack de teste dedicado (compose) e Postgres efêmero via testcontainers, e o harness fake de `HarnessPort` para E2E; verificar que um exemplo de cada camada roda verde (`pytest`, `pytest tests/bdd`, `pytest tests/e2e`)

## 2. Identidade e RBAC

- [x] 2.1 Implementar autenticação local (e-mail/senha com hash, sessões, logout, mensagem genérica em falha) com testes unitários de hash/sessão e a feature `portal-identity.feature` cobrindo os cenários de login válido, login inválido e logout da spec; verificar `pytest tests/bdd --verbose` verde nesses cenários
- [x] 2.2 Implementar os tipos globais de usuário (`admin`, `editor`, `app_user`) com guardas de capacidade; verificar com testes unitários das guardas e cenários BDD de criação de sistema por editor, recusa de `app_user` e acesso total de admin
- [x] 2.3 Implementar a UI de administração de usuários e grupos (criar usuário com tipo, desativar, criar grupo, adicionar membros, vincular grupo a sistema) e verificar com suíte E2E Playwright o fluxo completo no browser com um editor e um `app_user` de teste
- [x] 2.4 Implementar a visibilidade de sistemas conforme permissão nas listagens; verificar com testes unitários das queries de visibilidade e cenários BDD de dono, `app_user` de grupo e usuário sem vínculo

## 3. Sistemas e conexões de banco

- [x] 3.1 Implementar o CRUD de sistemas (slug único, dono = criador, provedor/modelo LLM com default GLM, estados provisionando/ativo/erro); verificar com testes unitários e cenários BDD de slug duplicado e default de provedor (`system-management.feature`)
- [x] 3.2 Implementar o cadastro de conexões PostgreSQL com teste de conectividade antes de salvar; verificar com testes de integração contra Postgres efêmero (testcontainers) e cenários BDD de conexão válida e inválida (`db-connections.feature`)
- [x] 3.3 Implementar a cifra de credenciais em repouso e a proteção contra vazamento (senha nunca retorna na edição, não aparece em logs/eventos); verificar com testes unitários da cifra e asserções de ausência de segredo em logs capturados
- [x] 3.4 Implementar a UI de cadastro/edição de sistemas e conexões para o dono; verificar com suíte E2E Playwright o cadastro no browser de um sistema com duas conexões a bancos distintos

## 4. Imagem base e ciclo de vida dos containers

- [x] 4.1 Criar o Dockerfile da imagem base (Python 3.12, uv, opencode em versão pinada, MCP server de Postgres); verificar que a imagem builda e o container responde `opencode --version`
- [x] 4.2 Implementar o supervisor como PID 1 (sobe `opencode serve`, watchdog da app em `/workspace/app` com reinício e backoff, healthcheck em `/healthz`); verificar com testes unitários da lógica de backoff/watchdog e execução manual do container: app de exemplo reinicia ao editar arquivo e health check reflete o estado
- [x] 4.3 Implementar o provisionamento via Docker API (container + volume + rede com labels próprios, limites padrão de recursos, teto de simultâneos, restart policy `unless-stopped`); verificar com testes de integração com Docker real e cenários BDD de limites aplicados e workspace persistente (`container-lifecycle.feature`)
- [x] 4.4 Implementar a reconciliação no boot/periódica (recria container ausente com workspace existente) e os fluxos de arquivamento (dono; preserva workspace) e exclusão definitiva (só admin; remove container e workspace); verificar com testes de integração e cenários BDD da spec

## 5. Harness do agente e chat

- [x] 5.1 Executar o spike da API `opencode serve` (sessões, envio de mensagem, eventos de stream, interrupção, uso de tokens) com script manual contra a imagem base e registrar no design.md o mapeamento final de eventos normalizados
- [x] 5.2 Implementar a fronteira `HarnessPort` e o adapter `OpencodeHarness` (sessões, envio, stream de eventos normalizados, interrupção, uso de tokens); verificar com testes unitários contra servidor HTTP falso cobrindo todos os eventos e a interrupção
- [x] 5.3 Implementar a fila de um agente por sistema (runs com estado, ordem de chegada, execução corrente visível aos demais editores); verificar com testes unitários/de integração de concorrência que dois pedidos simultâneos executam em série na ordem enviada
- [x] 5.4 Implementar a provisão das conexões ao container (opencode.json com MCP server por conexão, credenciais via env) e verificar em sessão manual que o agente lista as tabelas de um Postgres de teste via MCP
- [x] 5.5 Implementar o chat no portal com streaming WebSocket e interrupção; verificar com suíte E2E Playwright (harness fake) um pedido ponta a ponta com eventos chegando em tempo real no browser e interrupção funcional
- [x] 5.6 Implementar as guidelines de geração (documento editável pelo admin, materializado como AGENTS.md no workspace, padrão NiceGUI/PT-BR/uma app por sistema); verificar com testes unitários que a atualização propaga para o workspace na execução seguinte
- [x] 5.7 Implementar os checkpoints git (commit ao fim de run bem-sucedida, histórico por sistema, rollback com reinício da app); verificar com testes de integração em workspace de teste que o rollback restaura o estado anterior e a app reinicia nele, e cenário BDD correspondente
- [x] 5.8 Implementar o registro de uso de tokens por run e o painel de consumo por sistema/usuário/período; verificar com testes unitários do agregador e E2E Playwright de que o painel exibe os dados de uma run do harness fake

## 6. Publicação das apps geradas

- [x] 6.1 Executar o spike de path-prefix do NiceGUI (app servida em `/apps/{slug}/` com WebSocket via Traefik, `root_path` configurado) e consolidar o layout de projeto e middleware nas guidelines
- [x] 6.2 Implementar o roteador de apps (config dinâmica do Traefik ao provisionar/arquivar sistema, caminho estável `/apps/{slug}`); verificar com teste de integração que a rota é publicada ao criar e removida ao arquivar
- [x] 6.3 Implementar a propagação de identidade (token HMAC curto por sistema, troca por sessão na app via middleware das guidelines, reautenticação do portal em token inválido/expirado); verificar com testes unitários dos cenários de token válido, inválido e expirado e cenários BDD (`app-serving.feature`)
- [x] 6.4 Implementar o monitoramento de saúde (health check contínuo, estado rodando/erro na página do sistema, reinício com backoff); verificar com teste de integração de app quebrada (estado de erro aparece e recupera) e E2E Playwright do estado exibido na página do sistema

## 7. Verificação ponta a ponta

- [x] 7.1 Compor a suíte E2E Playwright completa contra o stack completo com harness fake: jornada criar sistema → conectar Postgres de teste → gerar admin CRUD → `app_user` usa a app em `/apps/{slug}`; incluir negação de permissão a usuário sem vínculo e rollback por checkpoint na UI; verificar que a suíte roda verde do zero
- [x] 7.2 Executar o cenário `@llm_real` (chat com opencode + GLM gerando um admin real sobre Postgres de homologação) e registrar a evidência do fluxo completo com LLM real
- [x] 7.3 Escrever o README de operação (subir o stack, bootstrap do admin, criar sistema/conexão, rollback de checkpoint, ajustar limites, rodar as três camadas de teste: `pytest`, `pytest tests/bdd`, `pytest tests/e2e`) e verificar que um operador segue o documento do zero sem ajuda externa

## Workflow follow-up

- Arquivar a change (`/opsx archive`) após implementação concluída e revisada.
- Changes seguintes previstas no roadmap: suporte a MySQL/MariaDB, SQLite e MongoDB; gate de confirmação para operações destrutivas; proxy por subdomínio; OIDC; auto-stop por inatividade; bloqueio de custo de LLM; usuário de banco com privilégios mínimos para apps geradas.
