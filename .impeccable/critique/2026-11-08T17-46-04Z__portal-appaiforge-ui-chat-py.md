---
target: Chat tab (portal/appaiforge/ui/chat.py)
total_score: 15
max_score: 36
na_heuristics: 10
p0_count: 1
p1_count: 3
target_identity: "file:/home/alanyoshida/appdatabase/portal/appaiforge/ui/chat.py"
target_fingerprint: "sha256:0b61f9bc2dd8c185030f3202bca580d9ea5e479a3ce675c900c0761c63489739"
target_path: /home/alanyoshida/appdatabase/portal/appaiforge/ui/chat.py
timestamp: 2026-11-08T17-46-04Z
slug: portal-appaiforge-ui-chat-py
---
**Method: dual-agent (A: design review sub-agent · B: detector/browser-evidence sub-agent)**

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 0 | Trocar para uma sessão nova ainda renderiza a run em andamento de outra sessão no mesmo log_box. |
| 2 | Match System / Real World | 1 | A lista de sessões nunca marca qual está ativa. |
| 3 | User Control and Freedom | 2 | Sem desfazer uma interação feita sem querer na sessão errada. |
| 4 | Consistency and Standards | 2 | Só interrupt_btn tem aria-label. |
| 5 | Error Prevention | 1 | O vazamento entre sessões é uma condição ativa de erro, sem guarda. |
| 6 | Recognition Rather Than Recall | 3 | Tooltip no lápis, switch "Debug" autoexplicativo. |
| 7 | Flexibility and Efficiency | 1 | Trocar de sessão exige rolar além do log+input pra lista colapsada. |
| 8 | Aesthetic and Minimalist Design | 3 | "Quieto por padrão" bem executado visualmente. |
| 9 | Error Recovery | 2 | Aviso de contexto reiniciado explica bem o "quê" mas sem ação embutida. |
| 10 | Help and Documentation | n/a | Ferramenta interna Operate para editores treinados. |
| Total | | 15/36 | Poor (42%) |

## Design Specificity Verdict

Avaliação (Assessment A): Não é uma UI de chat genérica - bolhas assimétricas, sombra única, disciplina de cor por significado e o ponto pulsante de disponibilidade são autorais. Onde escorrega é no gerenciamento de sessão: lista, título e estado bloqueado se comportam como apêndice genérico.

Varredura determinística (Assessment B): scan por URL sem sessão só viu login (1 achado irrelevante). Autenticado com overlay: 10 achados modo claro (6x contraste baixo 3.7:1 nas 6 abas de navegação; 1x tight-leading; 3x nested-cards nas bolhas) e 5 no modo escuro (1x contraste crítico 1.7:1 na pergunta do agente; mesmos tight-leading/nested-cards).

Onde concordam: falha de disciplina de token em ambos (A achou cor Tailwind crua em _render_artifact_error; B achou contraste 1.69:1 que contraria a auditoria AA alegada no DESIGN.md).

O que o detector pegou e a revisão não cobriu: 6 abas de navegação com contraste baixo no modo claro, afetando toda página do sistema.

O que a revisão pegou e o detector não enxerga: vazamento de conteúdo entre sessões (comportamento de estado, não markup) e títulos em CAIXA ALTA por falta de no-caps.

Falso positivo provável: os 3x nested-cards nas bolhas do chat - padrão esperado de balão de mensagem num painel rolável.

## Overall Impression

A linguagem visual está bem executada e autoral. O problema real está na UI de sessão - bug de comportamento sério (vazamento entre sessões) e nenhuma indicação visual de qual sessão está ativa.

## What's Working

1. Disciplina do par "on-" - theme.py calcula texto-sobre-fundo por modo em vez de assumir branco.
2. Cor semântica nos cards de gate/pergunta - vocabulário escaneável sem ícones novos.
3. Ponto de disponibilidade pulsante respeita prefers-reduced-motion como o PRODUCT.md promete.

## Priority Issues

[P0] Vazamento de conteúdo entre sessões
O quê: criar/trocar para uma sessão nova e vazia ainda mostra e deixa interagir com a run em andamento de outra sessão do mesmo sistema.
Por que importa: usuário pode responder uma pergunta achando que é de outra sessão - mina a confiança de estado.
Fix: em refresh_state() (chat.py:516), escopar a run "em andamento" por chat_session_id == active_session["id"], não só por system.id.
Comando sugerido: $impeccable harden

[P1] Contraste crítico na pergunta do agente, modo escuro
O quê: texto #0d47a1 sobre fundo #1e293b = 1.69:1 (precisa 4.5:1) no card "PERGUNTA DO AGENTE".
Por que importa: contradiz a alegação de auditoria AA do DESIGN.md.
Fix: mapear essa classe Quasar crua pro token do tema, mesmo tratamento já aplicado a .text-blue-10.
Comando sugerido: $impeccable audit

[P1] Título da sessão nunca atualiza quando uma run em andamento é retomada
O quê: session_title_label fica vazio quando o conteúdo vem do pickup automático do refresh_state(), não de clique explícito.
Por que importa: viola heurística #1 - "de quem é essa conversa" não tem resposta na tela.
Fix: quando refresh_state() pegar run de sessão diferente, atualizar active_session["id"] e o título.
Comando sugerido: $impeccable audit

[P1] Contraste baixo nas 6 abas de navegação (modo claro)
O quê: 3.7:1 (precisa 4.5:1) em EDITOR/CONEXÕES/DOMÍNIOS/CHECKPOINTS/CONFIGURAÇÕES/AUDITORIA.
Por que importa: afeta toda página de sistema, não só o Chat.
Fix: ajustar token --ap-muted/cor de aba inativa no modo claro.
Comando sugerido: $impeccable audit

[P2] Controles só-ícone sem nome acessível
O quê: enviar, renomear e revogar não têm aria-label; campo de chat só tem placeholder.
Por que importa: leitor de tela ouve botão sem nome pra ação mais importante da tela.
Fix: adicionar aria-label usando o mesmo texto já escrito nos tooltips.
Comando sugerido: $impeccable harden

[P2] Lista de sessões enterrada + títulos em CAIXA ALTA
O quê: "Sessões" fica depois do input; títulos automáticos saem em caixa alta por falta de no-caps.
Por que importa: contradiz o North Star "quieto por padrão".
Fix: no-caps nos botões de sessão; considerar reposicionar a lista.
Comando sugerido: $impeccable polish

[P3] Aviso de contexto reiniciado sem ação embutida
O quê: a correção só existe no botão do topo, fora do banner.
Por que importa: atrito no momento de frustração do usuário.
Fix: botão "Nova sessão" dentro do próprio blocked_row.
Comando sugerido: $impeccable polish

## Persona Red Flags

Alex (Power User): lista de sessões atrás de expansão colapsada abaixo do input é regressão de eficiência, e é quem mais seria pego pelo vazamento entre sessões.

Sam (Acessibilidade): enviar, renomear e revogar são mudos pra tecnologia assistiva - a ação mais importante da tela não tem nome anunciado.

## Minor Observations

- _render_artifact_error usa cor Tailwind crua em vez de token - contraria a regra "Don't" do DESIGN.md.
- Trocar de tema parece reacionar o bug de título vazio.
- tight-leading (line-height 1.20, precisa >=1.3) numa linha do texto do agente.
- Possível criação duplicada de "Nova sessão" durante teste - atribuída a retry de clique da automação, não confirmado.
