# Proposal

## Why

Precisamos de um portal (AppAIForge) onde sistemas de gestão sejam criados por IA sobre bancos de dados existentes: hoje, construir painéis administrativos, dashboards e relatórios sobre um banco é trabalho manual repetitivo, e a plataforma o transforma em uma conversa — o usuário descreve o que quer, um agente (harness opencode dentro de um container por sistema) entende o banco via MCP e gera backend + frontend em Python (NiceGUI), que sobe automaticamente e passa a ser acessível de dentro do portal.

Este é o change fundador do projeto: entrega a primeira fatia vertical completa do AppAIForge — do cadastro do sistema à app gerada rodando e proxiada.

## What Changes

- **Portal web (FastAPI + NiceGUI)** novo, com banco Postgres próprio para metadados, rodando neste host com Docker.
- **Identidade e acesso**: login local (e-mail/senha); usuários com tipo global — `admin` (tudo), `editor` (cria sistemas, cadastra conexões, conversa com o agente), `app_user` (só usa apps geradas acessíveis); grupos de usuários com acesso a N sistemas.
- **Cadastro de sistemas**: cada sistema criado por um editor (que se torna dono) ganha um container próprio com imagem base pré-assada (Python + uv + opencode + supervisor + MCP servers).
- **Conexões de banco**: um sistema cadastra N conexões; neste MVP o tipo suportado é **PostgreSQL** (produção, leitura e escrita); credenciais armazenadas cifradas e injetadas apenas no container do sistema.
- **Agente por sistema**: harness `opencode serve` rodando dentro do container, acessado pelo portal através de um adapter; provedor de LLM configurável por sistema (padrão GLM/Z.ai); o agente recebe as conexões como MCP servers e guidelines de geração globais (editáveis pelo admin; UIs geradas em PT-BR, padrão NiceGUI).
- **Chat com streaming**: o editor conversa com o agente pelo portal, vê o trabalho em tempo real (arquivos, comandos) e pode interromper; um agente por sistema por vez (fila para os demais editores).
- **Checkpoints de código**: git no workspace de cada sistema; commit automático ao fim de cada sessão de chat bem-sucedida, com rollback pelo portal.
- **App gerada servida**: supervisor no container sobe/reinicia a app NiceGUI gerada; o portal a expõe em `/apps/{slug}` (abstração pronta para subdomínios futuros), injetando a identidade do usuário logado na app proxiada.
- **Ciclo de vida e recursos**: containers sempre ativos com restart policy e reconciliação no boot do portal; limites padrão por container (2 CPUs / 2 GB RAM / 10 GB disco, ~10 simultâneos, ajustável na configuração).
- **Visibilidade de custo**: dashboards de consumo de tokens por sistema/usuário (sem bloqueio).

**Fora do escopo deste change** (changes seguintes já previstas): suporte a MySQL/MariaDB, SQLite e MongoDB; gate de confirmação para operações destrutivas no banco (agente e app); proxy por subdomínio; auth via OIDC; auto-stop de containers inativos; tetos/bloqueio de custo de LLM.

## Capabilities

### New Capabilities

- `portal-identity`: autenticação local (e-mail/senha, sessões), usuários com tipo global (admin/editor/app_user), grupos e concessão de acesso a sistemas.
- `system-management`: cadastro e ciclo de vida administrativo de sistemas por editores (dono), listagem e visibilidade conforme permissões.
- `db-connections`: cadastro, validação e guarda cifrada de conexões de banco por sistema (PostgreSQL neste MVP) e provisão como MCP servers para o agente e credenciais de ambiente para a app gerada.
- `container-lifecycle`: criação/gerenciamento do container por sistema (imagem base, limites de recursos, restart policy, reconciliação no boot).
- `agent-harness`: adapter do portal para o harness opencode serve (sessões, streaming, fila por sistema), configuração de provedor LLM por sistema, guidelines de geração, checkpoints git e registro de uso de tokens.
- `app-serving`: supervisor da app gerada no container, proxy do portal em `/apps/{slug}` com injeção de identidade do usuário logado e verificação de saúde.

### Modified Capabilities

(nenhuma — projeto novo, sem specs existentes)

## Impact

- **Novo código**: monorepo do portal (backend FastAPI + frontend NiceGUI), imagem base dos containers, supervisor, adapter de harness; sem código existente afetado (greenfield).
- **Dependências novas**: Docker (API de containers no host), opencode (binário na imagem base), MCP servers de Postgres, provedores de LLM via API (padrão GLM/Z.ai).
- **Sistemas externos**: bancos PostgreSQL de produção acessados pelos sistemas cadastrados (leitura pelo agente via MCP; leitura e escrita pela app gerada com a mesma credencial da conexão — risco aceito, gate dedicado vem em change posterior).
- **Host**: este host (Docker 29.9, 28 CPUs, 46 GB RAM); novo serviço Postgres para metadados do portal; ~10 containers de sistema suportados com limites padrão.
