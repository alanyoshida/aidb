# Tasks

## 1. CLI na imagem base

- [x] 1.1 Adicionar `ARG OPENSPEC_VERSION=1.15.0`, `npm install -g @fission-ai/openspec@${OPENSPEC_VERSION}` e `ENV OPENSPEC_TELEMETRY=0` ao `base-image/Dockerfile`; verificar com `docker run --rm --network none <imagem> openspec --version` imprimindo 1.15.0 como o usuário não-root da imagem

## 2. Bootstrap no supervisor

- [x] 2.1 Implementar `ensure_openspec(workspace)` no supervisor (init com `--tools opencode --language pt-BR` quando não há `openspec/`, `update` quando há, timeout de 30s, erro só logado) e chamá-lo antes de `start_harness` com a identidade do harness; verificar com testes unitários usando `ProcessRunner` fake (workspace vazio -> init; inicializado -> update; falha/timeout -> harness inicia mesmo assim)
- [x] 2.2 Teste de integração com container real (driver Docker): sistema novo sobe com `openspec/` e `.opencode/commands/opsx-propose.md` no workspace; criar uma change à mão, recriar o container e verificar que ela continua lá; verificar com `pytest tests/integration -k openspec`

## 3. Guidelines

- [x] 3.1 Adicionar a seção de OpenSpec ao `_DEFAULT` de `portal/appaiforge/guidelines.py` (nomes `/opsx-*` do opencode, quando usar, artefatos em `openspec/`); verificar com teste unitário que o conteúdo padrão contém os quatro comandos

## 4. Autocomplete de comandos no chat

- [x] 4.1 Confirmar na versão pinada do opencode (1.19.5) o endpoint que lista comandos e como um prompt `/<comando> args` é executado como comando; registrar o resultado no design.md (D5); verificar com chamada real a um container de sistema
- [x] 4.2 Adicionar `list_commands` ao `HarnessPort` e implementar no `opencode.py` (endpoint confirmado), `fake.py` (lê `.opencode/commands/`) e `claude_code.py` (lista vazia), com cache por sistema de 60 s e timeout de 2 s; verificar com testes unitários (formato, cache, falha -> lista vazia) e teste de contrato do opencode
- [x] 4.3 Se 4.1 mostrar que o envio atual não executa comandos, ajustar o adapter opencode para enviar `/<comando> args` pelo endpoint de comando; verificar com teste unitário do adapter
- [x] 4.4 Implementar o menu de sugestões no campo do chat (`ui/chat.py`): abre com `/` no início, filtra por prefixo, setas/Enter/Tab completam sem enviar, Esc fecha, Enter com menu fechado envia como hoje; verificar com E2E (harness fake) cobrindo os cenários da spec: sugestões ao digitar `/`, filtro `/opsx-ap`, escolha por teclado, mensagem sem `/` sem sugestões

## 5. Verificação ponta a ponta

- [x] 5.1 E2E com harness fake: criar sistema no stack E2E e verificar, pela API de arquivos do workspace (visualizador), que `openspec/config.yaml` e `.opencode/commands/opsx-propose.md` existem; verificar com `pytest tests/e2e -k openspec`
- [x] 5.2 Validação manual com opencode real (llm_real): enviar `/opsx-propose adicionar filtro por data` no chat de um sistema usando o autocomplete, e confirmar a change em `openspec/changes/` e no checkpoint; registrar o resultado no PR
- [x] 5.3 Documentar no README (seção do agente do sistema) que os comandos `/opsx-*` estão disponíveis no chat com autocomplete ao digitar `/`; verificar que o trecho cita a versão pinada
