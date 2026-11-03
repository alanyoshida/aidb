# Design

## Context

Ver `proposal.md — Why`. Estado atual relevante:

- `provisioning.write_opencode_config(system, workspace_dir)` escreve `opencode.json` em `workspace_dir`, que mapeia para `/workspace` no container do sistema.
- `afsupervisor/supervisor.py` inicia `opencode serve` sem `cwd` explícito, herdando o `WORKDIR=/workspace` do Dockerfile — opencode lê `opencode.json` do diretório corrente.
- O bind mount atual: `host_workspaces_dir/<slug>` → `/workspace` (rw). Um segundo bind por sistema seria necessário para expor o config dir ao container.
- O container roda como root; `DATABASE_URL_*` nas env vars é uma limitação conhecida fora do escopo desta change (ver proposal.md — Limitação conhecida).

## Goals / Non-Goals

**Goals:**
- Remover `opencode.json` do workspace, impedindo acesso por navegação de arquivos.
- Manter comportamento externo idêntico (o agente e a app continuam funcionando).

**Non-Goals:**
- Não remove a exposição via `printenv DATABASE_URL_*` (requer container não-root).
- Não altera o formato ou conteúdo do `opencode.json`.

## Decisions

### D1. Diretório de config fora do workspace, bind-mountado no container

`host_config_dir/<slug>/opencode.json` é bind-mountado como `/opencode-config` (read-only) no container. O supervisor inicia opencode com `cwd=/opencode-config`.

**Alternativas consideradas:**
- `~/.config/opencode/` no container: opencode pode ler global config de lá, mas o comportamento não é garantido pela API pública do opencode serve; muda entre versões.
- Path em `/root/` no container: acessível via bash (`cat /root/opencode.json`); resolve acidental mas não intencional.
- Variável de ambiente `OPENCODE_CONFIG`: opencode 1.19.x não documenta essa var; evitar dependência de comportamento não documentado.

A solução de bind separado é a mais previsível: o opencode lê sempre do cwd, o cwd não é o workspace, fim.

### D2. Bind read-only para o config

O container não precisa escrever no config dir. Read-only previne que o agente modifique o opencode.json mesmo que encontre o path.

### D3. Nova setting `host_config_dir` em `config.py`

Segue o padrão de `host_workspaces_dir` / `workspaces_dir`. O portal cria o diretório antes de escrever (já faz isso para o workspace).

## Risks / Trade-offs

- **Reprovisionamento obrigatório ao mudar conexões** — já existia; não piora. O container é recriado porque o bind mount do config dir é fixado na criação.
- **Dois binds por sistema** — custo marginal no Docker; sem impacto observável.
- **O agente determinado consegue o path** — se um editor souber que o config está em `/opencode-config/opencode.json` pode ler. O objetivo declarado é eliminar o acesso acidental e via "listar arquivos do projeto", não o acesso adversarial total (esse requer container não-root).

## Migration Plan

1. Criar `host_config_dir` nas settings com default `/var/lib/appaiforge/configs`.
2. Ajustar `provision_system` para criar o diretório de config e adicionar o bind mount.
3. Ajustar `write_opencode_config` para receber e usar o `config_dir` em vez do workspace dir.
4. Ajustar o supervisor para iniciar opencode com `cwd=/opencode-config`.
5. Sistemas existentes: o próximo `refresh_connections` ou reprovisionamento aplica a mudança (o container é recriado). Não há migração de dados.
6. Rollback: reverter os quatro pontos acima; containers existentes são recriados no próximo reprovisionamento.
