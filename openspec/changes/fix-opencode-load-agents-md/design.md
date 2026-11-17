## Context

- O perfil `opencode` sobe `opencode serve` com `cwd=/opencode-config` (bind só-leitura com o `opencode.json` gerado pelo portal). Isso impede o agente de alterar a própria config, mas também tira o workspace da busca de arquivos de regras do opencode (ele procura `AGENTS.md` a partir do diretório do projeto).
- `guidelines.materialize` escreve `/workspace/AGENTS.md` antes de cada execução, nos drivers Docker e Kubernetes.
- Verificado no opencode 1.19.5 com um provedor falso que captura a requisição: sem `instructions`, o texto do `AGENTS.md` não aparece no corpo enviado ao modelo; com `"instructions": ["/tmp/ws/AGENTS.md"]` (caminho absoluto fora do cwd), aparece.

## Goals / Non-Goals

**Goals:**
- Guidelines da plataforma no prompt do agente opencode, nos dois drivers.
- Manter o confinamento: nenhuma config de projeto do workspace passa a ser lida.

**Non-Goals:**
- Perfil `claude-code` (roda com `cwd=/workspace` e tem mecanismo próprio de instruções; verificar à parte).
- Recriar automaticamente os containers existentes.

## Decisions

### D1. `instructions` com caminho absoluto na config gerada
`write_opencode_config` adiciona `"instructions": ["/workspace/AGENTS.md"]`. O campo só aponta arquivos de texto incorporados ao prompt; não muda o diretório do projeto nem habilita config do workspace.

*Alternativas*: rodar o opencode em `/workspace` ou mandar `directory=/workspace` na API — rejeitadas, carregariam `/workspace/.opencode/opencode.json`, gravável pelo agente (mesmo motivo registrado na change `add-openspec-to-system-container`). Symlink de `~/.config/opencode/AGENTS.md` no supervisor — funciona, mas espalha a decisão em dois lugares (portal e imagem) quando a config já é do portal.

### D2. Caminho do workspace
`/workspace` é o ponto de montagem fixo nos dois drivers (`docker_driver`, `kubernetes_driver`) e já aparece nas listas de escrita dos perfis. Usar uma constante no módulo de provisionamento, sem novo campo no perfil.

## Risks / Trade-offs

- [Arquivo ausente no primeiro start, antes da primeira execução] → o opencode ignora entrada de `instructions` inexistente (verificar no teste de contrato); a materialização acontece antes de cada execução.
- [Guidelines grandes aumentam tokens por mensagem] → é o comportamento pretendido do requisito; o texto padrão é curto.
- [Mudança de comportamento do agente em sistemas existentes ao serem recriados] → efeito desejado: passam a seguir as guidelines que já deveriam seguir.

## Migration Plan

Deploy do portal. Cada sistema ganha a config nova quando o container for recriado (reprovisionamento, troca de conexão, reconciliação). Rollback: remover o campo.
