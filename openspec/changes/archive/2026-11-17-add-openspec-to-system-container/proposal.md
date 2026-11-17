# Proposal

## Why

O editor conversa com o agente de cada sistema pelo chat do portal, mas não tem como pedir que ele trabalhe de forma planejada — proposta, specs, design e tarefas — antes de mexer na app. O OpenSpec já é o fluxo usado no próprio repositório do portal, porém hoje o container do sistema não tem o CLI `openspec` nem os comandos `/opsx-*` no workspace: um `/opsx-propose` enviado pelo chat vira texto comum e o agente improvisa.

## What Changes

- A imagem base dos sistemas passa a trazer o CLI do OpenSpec em versão fixa, disponível no `PATH` do agente opencode, sem depender de rede em tempo de execução.
- Ao subir o container, o workspace do sistema é inicializado com OpenSpec já configurado para o opencode (diretório `openspec/`, comandos `/opsx-*` e skills em `.opencode/`), com artefatos em português do Brasil. A inicialização é idempotente: workspaces já inicializados são preservados e só têm comandos/skills atualizados para a versão do CLI da imagem.
- Sistemas existentes ganham o OpenSpec no próximo reinício/recriação do container, sem perder `openspec/changes` e `openspec/specs` que já existam.
- As guidelines padrão da plataforma passam a explicar ao agente quando e como usar os comandos `/opsx-*`.
- Os comandos `/opsx-*` enviados pelo chat do portal chegam ao opencode e são executados como comandos (comportamento observável).
- O campo do chat ganha autocomplete de comandos: ao digitar `/`, o editor vê os comandos disponíveis no agente daquele sistema (incluindo os `/opsx-*`), com descrição, e pode escolher um com teclado ou mouse. A lista vem do próprio harness, sem nomes fixos no portal.

## Capabilities

### New Capabilities
- `system-openspec`: OpenSpec disponível e pré-configurado no ambiente do agente de cada sistema — CLI presente, workspace inicializado de forma idempotente e comandos `/opsx-*` utilizáveis pelo chat do portal.

### Modified Capabilities
- `agent-harness`: as guidelines padrão de geração passam a incluir instruções de uso do OpenSpec pelo agente; o chat passa a sugerir os comandos disponíveis no agente ao digitar `/`.

## Impact

- **Imagem base** (`base-image/Dockerfile`): instalação do pacote npm do OpenSpec em versão pinada.
- **Supervisor** (`base-image/afsupervisor/supervisor.py`): passo de bootstrap do OpenSpec no workspace antes de iniciar o harness.
- **Guidelines** (`portal/appaiforge/guidelines.py`): nova seção sobre OpenSpec.
- **Harness/chat** (`portal/appaiforge/harness/base.py`, `opencode.py`, `fake.py`, `claude_code.py`, `ui/chat.py`): operação de listar comandos do agente e autocomplete no campo do chat.
- **Testes**: unitários do bootstrap no supervisor, integração com container real (driver Docker) e E2E pelo chat com harness fake (verificação de arquivos no workspace).
- **Fora do escopo**: perfil de agente `claude-code` (imagem própria), CLI do OpenSpec no portal, liberação do registry npm no proxy de saída.
