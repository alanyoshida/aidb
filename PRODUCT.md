# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Times/clientes multi-tenant que precisam dar a um agente de IA acesso a um banco de produção (PostgreSQL, MySQL ou BigQuery) sem abrir mão de controle sobre o que esse agente pode fazer. Dois papéis no portal: **admin** (gestão de provedores de LLM, chaves, sistemas de todos) e **editor** (cria e opera seus próprios sistemas: conecta bancos, conversa com o agente, revisa auditoria). Sistemas de diferentes times/clientes convivem no mesmo host sem confiar um no outro — por isso o confinamento (rede, banco, filesystem) é fronteira de segurança real entre tenants, não só defesa em profundidade para um usuário já confiável.

## Product Purpose

Cria, por sistema, um container isolado onde um agente de IA (OpenCode) conversa em PT-BR com o editor e gera uma app administrativa completa (NiceGUI, 100% Python) sobre o banco conectado — disponível em `/apps/<slug>`. Sucesso é o editor conseguir pedir "crie um CRUD de clientes com busca" e ter uma app funcional rodando minutos depois, com o agente nunca tendo acesso de fato irrestrito ao banco, à rede ou ao filesystem do host.

## Positioning

Dois mecanismos juntos, nenhum sozinho é o argumento completo: (1) confinamento real no nível do kernel — Landlock de filesystem e rede, seccomp, um sidecar que fala o protocolo de fio do banco e classifica cada statement antes dela chegar ao Postgres/MySQL real (o container do sistema nunca vê a credencial, só um DSN de loopback), e um proxy HTTP(S) de saída com allow-list por sistema; e (2) a app administrativa gerada automaticamente é o produto entregue, não uma resposta de chat. Um agente de IA genérico com acesso a banco entrega um ou outro — não as duas coisas com o mesmo rigor de confinamento.

## Operating Context

- Self-hosted via Docker Compose (`deploy/docker-compose.yml`): Traefik (edge) → portal FastAPI+NiceGUI → um container por sistema (supervisor + `opencode serve` + app gerada) → banco de produção do cliente.
- Fluxo do editor: login → criar sistema → aguardar badge "ativo" → cadastrar conexão (testada antes de salvar) → chat de geração em PT-BR → checkpoint automático → app servida com SSO por token HMAC.
- Modo fake (sem chave de LLM) deixa todo o resto do portal operável para teste/demo; modo real via GLM/Z.ai (provedor default) ou qualquer provedor OpenAI-compatible cadastrado pelo admin.
- Broker de inferência opcional (LiteLLM): quando ligado, o container do sistema carrega só um token opaco, nunca a chave do provedor.
- Toda a interface e documentação de produto (README, ADRs, specs) é em português.

## Capabilities and Constraints

- Conexões: PostgreSQL, MySQL, BigQuery; cada uma com estado de saúde monitorado.
- Gate de operações destrutivas (classificador canônico sqlglot): `normal` executa sem atrito; `confirmável` (DELETE/UPDATE sem WHERE restritivo) e `bloqueada` (DDL) são **sempre recusadas na hora** em modo enforce, sem pedir aprovação humana — achado ao vivo documentado no ADR 0023.
- Confinamento de rede por sistema (etapa 5, concluída em 2026-11-08): toggle de internet habilitada/desabilitada, modo restrito com allow-list de domínios editável (pré-semeada com registries de pacote comuns — PyPI, npm), proxy HTTP(S) de saída obrigatório.
- Checkpoints: qualquer ponto do código gerado pode ser restaurado; a app reinicia no estado restaurado.
- Painel "Editor": árvore de arquivos do workspace gerado, somente leitura, ao lado do chat.
- Aparência: 3 modos (Light/Dark/Pastel) × 4 cores de destaque, 12 combinações, todas com contraste WCAG AA — tokens centralizados em `portal/appaiforge/ui/theme.py`.
- Artifacts no chat: blocos ` ```echart `, ` ```table `, ` ```html ` renderizados como gráfico, tabela interativa e HTML em sandbox.
- Terminologia do domínio: "sistema" (= instância provisionada, não "projeto"); "editor" (papel de usuário, não o painel de código); "confinamento" (termo guarda-chuva para Landlock/seccomp/gate/proxy); "etapa" (fase numerada do roadmap de confinamento, `docs/roadmap-confinamento-do-agente.md`).

## Brand Commitments

Nome do produto: **AIDB**. Sem outras marcas, logos ou ativos visuais confirmados até agora.

## Evidence on Hand

Nenhum dado real de cliente, case study, depoimento ou imprensa — produto interno/em desenvolvimento ativo, sem evidência de uso em produção fora deste repositório. Trabalho futuro não deve inventar testemunhos, benchmarks ou clientes.

## Product Principles

1. Confinamento é fronteira de tenant, não enfeite de UI — qualquer decisão de produto que amplie o que um agente alcança (rede, banco, filesystem) precisa de justificativa de segurança, não só de conveniência.
2. A app gerada é o entregável, o chat é o meio — fluxos devem otimizar para "o editor tem uma app funcional rápido", não para a conversa em si.
3. Recusa sem ambiguidade bate aprovação com atrito — decisões de gate (destrutivo, domínio, rede) são claras e imediatas; evitar qualquer design que reintroduza um "pedir aprovação humana" para algo que já deveria ser auto-decidido.
4. PT-BR é a língua do produto, não uma tradução — texto de interface, erro e documentação nascem em português.
5. Self-hosted multi-tenant: nunca assumir que dois sistemas no mesmo host confiam um no outro.

## Accessibility & Inclusion

Contraste WCAG AA confirmado nas 12 combinações de tema (ver Capabilities). Animações respeitam preferência de movimento reduzido do sistema operacional (ex.: indicador de disponibilidade do agente no chat). Sem outro requisito de acessibilidade confirmado além destes.
