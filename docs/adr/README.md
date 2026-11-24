# ADRs — Architecture Decision Records do AIDB

Registro das decisões arquiteturais e de produto da plataforma, em formato MADR (Markdown ADR), em português.

## Convenção

- Toda decisão arquitetural ou de produto relevante gera um ADR numerado sequencialmente (`NNNN-titulo-em-kebab-case.md`).
- Um ADR, uma decisão. Decisões revogadas mudam de status (`aceito` → `substituído por NNNN`), nunca são apagadas.
- Decisões tomadas durante a implementação de uma change também viram ADR e são referenciadas no `design.md` da change.

## Índice

| ADR | Decisão | Status |
|---|---|---|
| [0001](0001-monorepo-portal-base-image-deploy.md) | Monorepo com três entregáveis | aceito |
| [0002](0002-traefik-edge-com-config-dinamica.md) | Traefik como edge proxy com config dinâmica; path agora, subdomínio depois | aceito |
| [0003](0003-container-por-sistema-com-supervisor-pid1.md) | Container por sistema com supervisor próprio como PID 1 | aceito |
| [0004](0004-opencode-serve-atras-de-adapter-com-fila-no-portal.md) | Harness opencode serve atrás de adapter; fila de execução no portal | aceito |
| [0005](0005-streaming-do-chat-por-websocket.md) | Streaming do chat por WebSocket | aceito |
| [0006](0006-identidade-injetada-por-token-hmac.md) | Identidade do portal propagada às apps por token HMAC | substituído por 0027 |
| [0007](0007-metadados-em-postgres-e-credenciais-cifradas.md) | Metadados em Postgres; credenciais cifradas em repouso | aceito |
| [0008](0008-mcp-para-agente-driver-direto-para-app.md) | MCP para o agente analisar; driver direto para a app gerada | aceito |
| [0009](0009-git-por-sistema-com-checkpoints.md) | Git por sistema com checkpoints por execução | aceito (local do repositório e rollback: ver 0028) |
| [0010](0010-app-unica-em-nicegui-em-pt-br.md) | App única em NiceGUI por sistema, interface em PT-BR | aceito |
| [0011](0011-guidelines-de-geracao-editaveis-pelo-admin.md) | Guidelines de geração centralizadas, editáveis pelo admin | aceito |
| [0012](0012-llm-via-api-externa-provedor-por-sistema.md) | LLM via API externa; provedor por sistema (default GLM); custo só com visibilidade | aceito |
| [0013](0013-containers-sempre-ativos-com-reconciliacao.md) | Containers sempre ativos, com reconciliação e limites padrão | aceito |
| [0014](0014-rbac-com-tipos-globais-de-usuario.md) | RBAC com tipos globais de usuário; só editor cria sistemas | aceito (autenticação: ver 0027) |
| [0015](0015-mesma-credencial-de-producao-para-app-gerada.md) | App gerada usa a mesma credencial de produção; gate de destrutivas adiado | aceito (gate: ver 0017) |
| [0016](0016-testes-em-tres-camadas-unit-bdd-e2e.md) | Testes em três camadas: unitários, BDD e E2E pelo browser | aceito |
| [0017](0017-gate-de-operacoes-destrutivas-com-classificador-sql.md) | Gate de operações destrutivas com classificador SQL único (sqlglot) | aceito (gatilho do agente: ver 0021) |
| [0018](0018-perfil-de-runtime-do-agente-e-identidade-reduzida.md) | Perfil de runtime do agente declarativo; identidade de execução reduzida por sistema | aceito |
| [0019](0019-sandbox-seccomp-landlock-no-supervisor.md) | Sandbox do agente: seccomp + Landlock instalados pelo supervisor antes do exec | aceito |
| [0020](0020-broker-de-inferencia-com-litellm.md) | Broker de inferência: token opaco no container, LiteLLM como backend de credencial | aceito |
| [0021](0021-gate-de-sql-no-data-plane-via-sidecar-proxy.md) | Gate de SQL no data plane via sidecar proxy de wire protocol (Postgres/MySQL) | aceito (D3: ver 0023) |
| [0022](0022-confinamento-de-rede-por-porta-tcp-via-landlock.md) | Confinamento de rede por porta TCP via Landlock, fechando o bypass dos proxies de banco/broker | aceito (443/80: ver 0024) |
| [0023](0023-confirmavel-recusado-direto-sem-pedir-aprovacao.md) | Statement confirmável recusada direto em enforce, sem pedir aprovação (fecha disfarce de SQL destrutivo em card genérico) | aceito |
| [0024](0024-proxy-http-s-de-saida-obrigatorio-por-sistema.md) | Proxy HTTP(S) de saída obrigatório por sistema, com allow-list por host (fecha o corte de escopo da etapa 5) | aceito |
| [0025](0025-telemetria-otel-agnostica-de-backend.md) | Telemetria OTel agnóstica de backend via Collector; Debug log em Postgres próprio; gate/auditoria continuam fora da telemetria | aceito |
| [0026](0026-metricas-de-recursos-por-container-via-cadvisor.md) | Métricas de recursos por container via cAdvisor, rotuladas no scrape pra portabilidade futura a Kubernetes | aceito |
| [0027](0027-sso-oidc-e-identidade-das-apps-por-forwardauth.md) | SSO por OIDC opcional (modo por ENV, break-glass); acesso às apps verificado no edge e identidade por app em JWT | aceito |
| [0028](0028-repositorio-git-do-sistema-fora-do-workspace.md) | Repositório git do sistema fora do workspace; restauração cria checkpoint novo em vez de reescrever o histórico | aceito |
| [0029](0029-repositorio-remoto-por-retransmissao-no-portal.md) | Repositório remoto do sistema: envio pelo portal por cópia de retransmissão, chave e token fora do container, API só para a promoção | aceito |
| [0030](0030-sistema-so-implantacao-no-portal-de-producao.md) | Sistema só implantação: o portal de produção implanta tags verificadas na branch de destino, sem agente nem credencial de LLM | aceito |
| [0031](0031-isolacao-por-instalacao-do-portal.md) | Isolação por instalação: cada portal só remove ou adota os próprios containers, e a produção exige host Docker próprio | aceito |
| [0032](0032-gateway-api-com-traefik-como-implementacao.md) | Gateway API com o Traefik como implementação (auth por `ExtensionRef` ao `forwardAuth`), Traefik como subchart e dois modos de roteamento transitórios | aceito |
| [0033](0033-auto-instrumentacao-do-portal-e-elastic-apm.md) | Auto-instrumentação OTel do portal e do broker (sampler sem raiz de cliente, query string removida na origem, SQLAlchemy só no engine do portal); Elastic APM pelo APM Server standalone | aceito |
| [0034](0034-observabilidade-no-chart-kubernetes.md) | Observabilidade no chart Kubernetes: Collector opcional e agnóstico de backend, credencial do destino só nele, CPU e memória por sistema pelo kubelet num DaemonSet | aceito |
| [0035](0035-borda-das-apps-como-servicos-no-apm.md) | Borda das apps: cada app como um serviço no APM, com o slug tirado do caminho no Collector, transações sem identificadores e assets e query string fora | aceito |
| [0036](0036-catalogo-de-conexoes-autorizacao-e-ativacao.md) | Catálogo de conexões de banco: DB Manager autoriza por sistema com teto de modo, dono ativa com alias próprio, `schema_admin` só no listener do agente | aceito |
