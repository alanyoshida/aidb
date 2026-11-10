# Tasks

## 1. Spike (fechar antes de codar o caminho crítico)

- [x] 1.1 Validar o relay `CONNECT` em Python asyncio contra um host HTTPS real (ex.: `httpbin.org` ou o host de um provedor de LLM) — handshake, tunelamento sem decriptar, e que o cliente (`curl`/`httpx` configurado com `HTTPS_PROXY`) recebe a resposta íntegra; registrar o comportamento observado em design.md
- [x] 1.2 Validar que `pip`/`npm`/`uv` de fato respeitam `HTTP_PROXY`/`HTTPS_PROXY` do ambiente sem flag adicional, e levantar a lista real de hosts que cada um toca numa instalação simples (não só o registro principal — CDN, mirror, checksum); registrar a lista em design.md (D2)

## 2. Proxy HTTP(S) de saída (sidecar)

- [x] 2.1 Implementar o parsing da primeira linha da requisição (`CONNECT host:porta HTTP/1.1` e `GET http://host/path HTTP/1.1`) em módulo novo na base-image, ao lado do `dbproxy` da etapa 4; testar com entradas válidas e malformadas
- [x] 2.2 Implementar a checagem de allow-list por `host:porta` (recusa com erro de proxy claro se fora da lista) e o relay cego de bytes nos dois sentidos para `CONNECT` aprovado; testar destino permitido (relay íntegro) e destino recusado (nenhuma conexão aberta com o destino)
- [x] 2.3 Implementar o relay para requisição HTTP absoluta (sem `CONNECT`, usado por ferramentas que não negociam TLS pelo proxy) com a mesma checagem de allow-list; testar com uma requisição HTTP simples
- [x] 2.4 Implementar o modo "allow-list vazia" (internet desabilitada, D6): o sidecar recusa todo destino sem nenhuma lista calculada; testar que todo `CONNECT` é recusado nesse modo

## 3. Allow-list padrão calculada por sistema

- [x] 3.1 Criar o mapa `provider_id -> host` para os provedores nativos sem host documentado hoje (`anthropic` → `api.anthropic.com`; confirmar `openrouter`/`openai` contra o que `catalog._DEFAULT_MODELS_URL` já usa) e a função que resolve o host do provedor configurado para um sistema (nativo via mapa, `glm`/OpenAI-compatible via `base_url`/`glm_base_url`); testar cada provedor do catálogo
- [x] 3.2 Calcular a allow-list padrão de um sistema: host do provedor resolvido (3.1) quando o broker está desligado, OU host:porta do broker quando ligado (nunca os dois); testar os dois casos e o caso de alternância (habilitar/desabilitar o broker recalcula a lista)
- [x] 3.3 Definir a lista estática de hosts de registro de pacote a partir do levantamento da tarefa 1.2, compartilhada por todo sistema; testar que a allow-list padrão de qualquer sistema a inclui

## 4. Controles por sistema: internet habilitada e modo restrito

- [x] 4.1 Adicionar os campos `internet_enabled` (default `true`) e `restricted_network` (default `false`) ao modelo do sistema, e uma tabela nova para os domínios cadastrados do modo restrito (`system_id`, `domain`, autor, timestamp); migration e testes do modelo
- [x] 4.2 Ao criar um sistema, ou ao ligar o modo restrito pela primeira vez para um sistema que não tem nenhum domínio cadastrado, pré-popular a lista com os hosts de registro de pacote da tarefa 3.3 (PyPI, npm); testar que a lista nasce com esses domínios e que ligar/desligar de novo não duplica nem apaga o que o editor já alterou
- [x] 4.3 Implementar a função que monta a allow-list final de um sistema para o proxy: `internet_enabled=false` → lista vazia; senão, `restricted_network=true` → só os domínios cadastrados; senão → a allow-list padrão (3.2 + 3.3); testar as três combinações e a prioridade de `internet_enabled` sobre `restricted_network`
- [x] 4.4 Adicionar os dois toggles na aba Configurações do sistema (chat UI) e uma aba nova para a lista de domínios do modo restrito, com o mesmo nível de acesso de edição da aba Conexões (editor do sistema); testar que editar os toggles ou a lista recalcula a allow-list do sidecar daquele sistema

## 5. Integração no provisionamento

- [x] 5.1 Criar o container do sidecar do proxy HTTP(S) por sistema (`network_mode: container:<id>`, porta própria), com a allow-list final calculada (4.3) passada por env; testar sidecar subindo junto do sistema
- [x] 5.2 Remover 443/80 de `connect_tcp_ports` estático do perfil `opencode` (`agent_profiles.py`) e somar a porta do novo proxy à lista calculada por sistema em `provisioning.write_agent_profile`, junto das já calculadas (banco, broker); testar que a lista final do perfil não contém 443/80 diretamente, só a porta do proxy
- [x] 5.3 Injetar `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` no ambiente do container do sistema, apontando para o loopback do sidecar; testar `docker exec <sys> env` mostrando as variáveis corretas
- [x] 5.4 Garantir que `refresh_connections`/a reconciliação recriam o sidecar e recalculam a allow-list quando o provedor, o `base_url`, o estado do broker ou os controles da seção 4 mudam para um sistema; testar troca de provedor e de toggle propagando a nova allow-list

## 6. Testes de aceitação

- [x] 6.1 Integração com Docker real: de dentro de um sistema `sandboxed`, `CONNECT` no proxy para o host do provedor configurado funciona (resposta íntegra, ex.: listar modelos); `CONNECT` direto na porta 443 real (contornando o proxy) falha pelo Landlock
- [x] 6.2 Integração com Docker real: `CONNECT` no proxy para um host fora da allow-list (ex.: um domínio arbitrário) é recusado com erro de proxy claro, sem nenhuma conexão de saída real
- [x] 6.3 Integração com Docker real: `pip install` e `npm install` de um pacote real funcionam de dentro do container do sistema, sem flag nem configuração manual além das variáveis de ambiente já injetadas
- [x] 6.4 Integração com Docker real: alternar o broker de inferência (ligado/desligado) para um sistema e confirmar que a allow-list recalculada reflete a troca (host do provedor sai/entra, host do broker entra/sai)
- [x] 6.5 Integração com Docker real: desligar "internet habilitada" recusa todo destino externo mas o broker (quando habilitado) continua funcionando; ligar "modo restrito" só libera os domínios cadastrados, mesmo um host que estaria na allow-list padrão
- [x] 6.6 E2E no stack dedicado (8081), sem apontar para o ambiente real: cobrir o caminho novo com o harness fake, verificando que o provisionamento sobe o sidecar, o ambiente do sistema tem as variáveis de proxy corretas, e os dois toggles + a aba de domínios funcionam pela UI

## 7. Documentação e decisão

- [x] 7.1 Registrar o ADR desta change (proxy HTTP(S) de saída obrigatório, allow-list por host calculada por sistema, os dois controles por sistema), referenciando o ADR 0022 (de onde 443/80 saem) e o ADR 0020 (de onde vem a resolução broker-vs-provedor)
- [x] 7.2 Atualizar a etapa 5 no `docs/roadmap-confinamento-do-agente.md`, fechando a parte que havia sido cortada de escopo (negar 443, proxy HTTP(S))
- [x] 7.3 Documentar no `README.md` o proxy HTTP(S) de saída, a allow-list calculada por sistema, os dois controles (internet habilitada, modo restrito) e as variáveis de ambiente novas
