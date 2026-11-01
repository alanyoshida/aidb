# Tasks

## 1. Setup do monorepo e stack do portal

- [ ] 1.1 Criar a estrutura do monorepo (`portal/`, `base-image/`, `deploy/`) com `pyproject.toml` do portal e verificar que os diretórios e arquivos esperados existem
- [ ] 1.2 Criar o compose do stack do portal (Postgres, Traefik, portal) com healthchecks e verificar com `docker compose up` que o portal responde em `/` via Traefik
- [ ] 1.3 Criar o modelo de dados completo (usuários, grupos, vínculos, sistemas, conexões, sessões de chat, runs, checkpoints, uso de tokens, guidelines) com migração Alembic inicial e verificar que `alembic upgrade head` cria todas as tabelas
- [ ] 1.4 Criar comando CLI de bootstrap que cria o usuário admin inicial e verificar que o admin consegue autenticar-se no portal

## 2. Identidade e RBAC

- [ ] 2.1 Implementar autenticação local (e-mail/senha com hash, sessões, logout, mensagem genérica em falha) e verificar com testes os cenários de login válido, login inválido e logout da spec `portal-identity`
- [ ] 2.2 Implementar os tipos globais de usuário (`admin`, `editor`, `app_user`) com guardas de capacidade e verificar com testes que editor cria sistema, `app_user` é recusado e admin tem acesso total
- [ ] 2.3 Implementar a UI de administração de usuários e grupos (criar usuário com tipo, desativar, criar grupo, adicionar membros, vincular grupo a sistema) e verificar o fluxo completo pelo browser com um editor e um `app_user` de teste
- [ ] 2.4 Implementar a visibilidade de sistemas conforme permissão nas listagens e verificar com testes que dono vê os seus, `app_user` vê só os de seus grupos e usuário sem vínculo não vê nada

## 3. Sistemas e conexões de banco

- [ ] 3.1 Implementar o CRUD de sistemas (slug único, dono = criador, provedor/modelo LLM com default GLM, estados provisionando/ativo/erro) e verificar com testes os cenários de slug duplicado e default de provedor da spec `system-management`
- [ ] 3.2 Implementar o cadastro de conexões PostgreSQL com teste de conectividade antes de salvar, usando um Postgres efêmero de teste, e verificar os cenários de conexão válida e inválida da spec `db-connections`
- [ ] 3.3 Implementar a cifra de credenciais em repouso e a proteção contra vazamento (senha nunca retorna na edição, não aparece em logs/eventos) e verificar com testes unitários da cifra e inspeção dos logs de teste
- [ ] 3.4 Implementar a UI de cadastro/edição de sistemas e conexões para o dono e verificar pelo browser o cadastro de um sistema com duas conexões a bancos distintos

## 4. Imagem base e ciclo de vida dos containers

- [ ] 4.1 Criar o Dockerfile da imagem base (Python 3.12, uv, opencode em versão pinada, MCP server de Postgres) e verificar que a imagem builda e o container responde `opencode --version`
- [ ] 4.2 Implementar o supervisor como PID 1 (sobe `opencode serve`, watchdog da app em `/workspace/app` com reinício e backoff, healthcheck em `/healthz`) e verificar com execução manual do container: app de exemplo reinicia ao editar arquivo e health check reflete o estado
- [ ] 4.3 Implementar o provisionamento via Docker API (container + volume + rede com labels próprios, limites padrão de recursos, teto de simultâneos, restart policy `unless-stopped`) e verificar com teste de integração real: sistema criado gera container com limites e workspace persistente entre reinícios
- [ ] 4.4 Implementar a reconciliação no boot/periódica (recria container ausente com workspace existente) e os fluxos de arquivamento (dono; preserva workspace) e exclusão definitiva (só admin; remove container e workspace), verificando com testes de integração os cenários da spec `container-lifecycle`

## 5. Harness do agente e chat

- [ ] 5.1 Executar o spike da API `opencode serve` (sessões, envio de mensagem, eventos de stream, interrupção, uso de tokens) com script manual contra a imagem base e registrar no design.md o mapeamento final de eventos normalizados
- [ ] 5.2 Implementar a fronteira `HarnessPort` e o adapter `OpencodeHarness` (sessões, envio, stream de eventos normalizados, interrupção, uso de tokens) e verificar com testes unitários contra um servidor HTTP falso que cobrem os eventos e a interrupção
- [ ] 5.3 Implementar a fila de um agente por sistema (runs com estado, ordem de chegada, execução corrente visível aos demais editores) e verificar com testes de concorrência que dois pedidos simultâneos executam em série na ordem enviada
- [ ] 5.4 Implementar a provisão das conexões ao container (opencode.json com MCP server por conexão, credenciais via env) e verificar que o agente lista as tabelas de um Postgres de teste via MCP em sessão manual
- [ ] 5.5 Implementar o chat no portal com streaming WebSocket e interrupção, e verificar pelo browser um pedido ponta a ponta ("liste as tabelas") com eventos chegando em tempo real e interrupção funcional
- [ ] 5.6 Implementar as guidelines de geração (documento editável pelo admin, materializado como AGENTS.md no workspace, padrão NiceGUI/PT-BR/uma app por sistema) e verificar com testes que a atualização propaga para o workspace na execução seguinte
- [ ] 5.7 Implementar os checkpoints git (commit ao fim de run bem-sucedida, histórico por sistema, rollback com reinício da app) e verificar com um workspace de teste que o rollback restaura o estado anterior e a app reinicia nele
- [ ] 5.8 Implementar o registro de uso de tokens por run e o painel de consumo por sistema/usuário/período, e verificar com os dados de uma run real que o dashboard bate com o evento de uso reportado

## 6. Publicação das apps geradas

- [ ] 6.1 Executar o spike de path-prefix do NiceGUI (app servida em `/apps/{slug}/` com WebSocket via Traefik, `root_path` configurado) e consolidar o layout de projeto e middleware nas guidelines
- [ ] 6.2 Implementar o roteador de apps (config dinâmica do Traefik ao provisionar/arquivar sistema, caminho estável `/apps/{slug}`) e verificar com teste de integração que a rota é publicada ao criar e removida ao arquivar
- [ ] 6.3 Implementar a propagação de identidade (token HMAC curto por sistema, troca por sessão na app via middleware das guidelines, reautenticação do portal em token inválido/expirado) e verificar com testes os cenários de token válido, inválido e expirado da spec `app-serving`
- [ ] 6.4 Implementar o monitoramento de saúde (health check contínuo, estado rodando/erro na página do sistema, reinício com backoff) e verificar simulando uma app quebrada: estado de erro aparece e recupera após correção

## 7. Verificação ponta a ponta

- [ ] 7.1 Criar o smoke test E2E automatizado (criar sistema → conectar Postgres de teste → pedir ao agente um admin CRUD de uma tabela → app sadia em `/apps/{slug}` acessada por um `app_user`) e verificar que o teste passa do zero contra o stack completo
- [ ] 7.2 Escrever o README de operação (subir o stack, bootstrap do admin, criar sistema/conexão, rollback de checkpoint, ajustar limites) e verificar que um operador consegue subir o ambiente do zero seguindo apenas o documento

## Workflow follow-up

- Arquivar a change (`/opsx archive`) após implementação concluída e revisada.
- Changes seguintes previstas no roadmap: suporte a MySQL/MariaDB, SQLite e MongoDB; gate de confirmação para operações destrutivas; proxy por subdomínio; OIDC; auto-stop por inatividade; bloqueio de custo de LLM; usuário de banco com privilégios mínimos para apps geradas.
