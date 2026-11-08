---
name: AIDB
description: Portal que provisiona sistemas de agente de IA confinados sobre bancos de dados, gerando apps administrativas automaticamente
colors:
  accent-indigo: "#4f46e5"
  accent-teal: "#0f766e"
  accent-amber: "#b45309"
  accent-violet: "#6d4aff"
  bg: "#f1f2f8"
  surface: "#ffffff"
  surface-2: "#f8fafc"
  text: "#1e293b"
  muted: "#5b6878"
  border: "#e2e8f0"
  danger: "#dc2626"
  success: "#15803d"
  warning: "#b45309"
typography:
  title:
    fontFamily: "Roboto, -apple-system, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1.4
  body:
    fontFamily: "Roboto, -apple-system, Helvetica Neue, Arial, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Roboto, -apple-system, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.3
rounded:
  sm: "6px"
  md: "14px"
  pill: "22px"
  full: "50%"
  bubble-sent: "16px 16px 4px 16px"
  bubble-received: "4px 16px 16px 16px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
components:
  button-primary:
    backgroundColor: "{colors.accent-indigo}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.sm}"
  badge-status:
    backgroundColor: "{colors.accent-indigo}"
    textColor: "#ffffff"
    rounded: "{rounded.full}"
  chat-bubble-sent:
    backgroundColor: "{colors.accent-indigo}"
    textColor: "#ffffff"
    rounded: "{rounded.bubble-sent}"
    padding: "10px 14px"
  chat-bubble-received:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.bubble-received}"
    padding: "10px 14px"
  input-field:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text}"
    rounded: "6px 6px 0 0"
  input-chat:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text}"
    rounded: "{rounded.pill}"
---

# Design System: AIDB

## Overview

**Creative North Star: "O Caderno de Operador"**

AIDB é um painel técnico para quem opera sistemas de IA confinados sobre bancos de produção — não um produto de vitrine. A superfície fica quieta por padrão: fundo neutro, texto escuro sobre claro (ou o inverso no modo escuro), sem imagem, sem gradiente, sem textura. A cor aparece só onde carrega significado — um destaque de marca/ação, um estado (ativo, erro, aviso), uma origem (bolha do usuário vs. do agente). É a mesma lógica de um caderno de operador: a maior parte da página é anotação neutra; o grifo colorido é reservado pro que precisa de atenção.

O sistema não tem uma identidade tipográfica própria (Roboto, a fonte padrão do Material/Quasar, nunca foi substituída) nem motivo gráfico assinatura — a assinatura visual do produto é o próprio mecanismo de tema: 4 cores de destaque (Índigo, Teal, Âmbar, Violeta) × 3 modos (Light, Dark, Pastel) = 12 combinações, todas auditadas em contraste WCAG AA, trocáveis em runtime sem reload. Nenhuma combinação é "a identidade" — a identidade é o sistema de troca em si.

**Key Characteristics:**
- Neutro por padrão; cor só carrega significado (ação, estado, origem).
- 12 combinações de tema trocáveis em runtime, todas auditadas em contraste AA.
- Sem imagem, gradiente ou textura — tudo é cor sólida e tipografia.
- Curvas discretas e consistentes (campos, cards, bolhas de chat) em vez de cantos retos ou excesso de arredondamento.
- Sem elevação dramática: uma única sombra ambiente, usada com moderação.

## Colors

A paleta é funcional, não decorativa: cada token tem um papel (ação, estado ou origem), nunca é usado só pra preencher espaço.

### Primary
- **Índigo** (`#4f46e5` no modo claro, `#818cf8` no escuro): cor de destaque padrão (`DEFAULT_THEME = "light-indigo"`) — marca ("AIDB" na topbar), ação primária, aba ativa, bolha de mensagem do usuário no chat, foco.

### Alternate Accents (mesmo papel do Primary — escolha do usuário, não coexistem na mesma tela)
- **Teal** (`#0f766e` claro / `#2dd4bf` escuro)
- **Âmbar** (`#b45309` claro / `#fbbf24` escuro)
- **Violeta** (`#6d4aff` claro / `#a78bfa` escuro)

### Neutral (modo claro — modos escuro/pastel têm sua própria escala equivalente)
- **Fundo** (`#f1f2f8`): fundo da página.
- **Superfície** (`#ffffff`): cards, menus, painéis de aba.
- **Superfície 2** (`#f8fafc`): campos de formulário, fundo da bolha do agente.
- **Texto** (`#1e293b`): texto principal.
- **Secundário** (`#5b6878`): texto de apoio, rótulo — escolhido por contraste (>= 5:1), não o cinza padrão do Tailwind, que ficava abaixo de AA sobre fundos tingidos.
- **Borda** (`#e2e8f0`): divisores, contorno de card.

### Semantic
- **Erro** (`#dc2626` claro / `#fca5a5` escuro): ação destrutiva, exclusão, bloqueio.
- **Sucesso** (`#15803d` claro / `#4ade80` escuro): confirmação, agente livre.
- **Aviso** (`#b45309` claro / `#fbbf24` escuro): arquivamento, revogação, "contexto reiniciado".

### Named Rules
**The Significado, não Decoração Rule.** Toda cor fora de texto/fundo neutro precisa justificar um papel (ação, estado ou origem). Se a pergunta "essa cor está dizendo algo ao usuário?" não tem resposta clara, a cor não deveria estar ali.

**The Par "on-" Rule.** Toda cor semântica ou de destaque tem um par de texto-sobre-fundo (`--ap-on-accent`, `--ap-on-success`, etc.) calculado por modo, nunca branco fixo — no modo escuro as cores semânticas ficam claras, e texto branco sobre elas cai pra ~3:1. Nenhum componente novo deve assumir `color: white` sobre uma cor semântica sem checar o par "on-" do modo escuro.

## Typography

**Body Font:** Roboto (com fallback `-apple-system, Helvetica Neue, Arial, sans-serif`) — o padrão do Material/Quasar, nunca substituído.

**Character:** Sem identidade tipográfica própria — a função da fonte é ser invisível e legível. A hierarquia vem de peso e tamanho utilitário (Tailwind), não de uma escala type formal com múltiplas famílias.

### Hierarchy
- **Title** (500, `text-sm`/0.875rem, 1.4): título de sessão de chat, nome de conexão, rótulos de seção.
- **Body** (400, 1rem, 1.5): texto corrido, mensagens do chat, conteúdo de card.
- **Label** (400, `text-xs`/0.75rem, 1.3): rótulo de campo, badge, timestamp, botão denso (`text-xs` nos botões de ação secundária).
- Marca ("AIDB" na topbar) é a única ocorrência de peso 700/`text-xl` — não é um papel reutilizável, é a logo-texto.

### Named Rules
**The Sem Display Rule.** Não existe papel "display"/"headline" neste sistema — é um painel de operação (modo Operate), não uma landing page. Nenhuma tela deve introduzir texto hero ou headline de marketing.

## Layout

Layout é 100% flexbox (NiceGUI `ui.row`/`ui.column`) com larguras utilitárias Tailwind (`w-full`, `grow`) — não há grid nem container de largura fixa. Densidade é alta e consistente: `gap-1` (4px) entre itens relacionados de perto (ex.: botões de uma lista), `gap-2` (8px) entre blocos (ex.: header). Páginas de sistema usam abas (Chat, Editor, Conexões, Domínios, Checkpoints, Configurações, Auditoria) para segmentar funcionalidade em vez de scroll longo numa única tela. O painel de chat tem altura fixa (`h-96`/24rem) com scroll interno próprio, isolado do resto da página.

## Elevation & Depth

Quase plano. Existe uma única sombra ambiente (`--ap-shadow`) usada com moderação — cards, bolhas do chat recebidas, notificações. O modo escuro usa uma versão mais forte da mesma sombra (`rgba(0,0,0,0.5)` vs. `rgba(15,23,42,0.08)`) pra compensar o menor contraste de borda contra um fundo escuro. Não há elevação em camadas (z-index visual, sombras múltiplas) — profundidade vem de borda + leve sombra, uma vez só.

### Shadow Vocabulary
- **Ambiente** (`0 1px 3px rgba(15,23,42,0.08)` claro / `0 1px 3px rgba(0,0,0,0.5)` escuro): cards, bolha recebida do chat, notificações, popup de erro de conexão.

### Named Rules
**The Uma Sombra Só Rule.** Existe exatamente um token de sombra por modo. Um componente novo que "precisa" de uma sombra mais forte ou mais sutil é sinal de que a hierarquia deveria vir de cor/borda, não de uma segunda sombra.

## Shapes

Curvas discretas e consistentes, nunca cantos retos nem círculos em excesso — exceto onde a forma circular é o próprio significado (avatar, swatch de tema, indicador de disponibilidade).

- **Campos de formulário**: 6px só no topo (`6px 6px 0 0`) — o variant "standard" do Quasar é underline puro; o arredondamento dá volume de caixa sem virar um card.
- **Cards/superfícies**: radius padrão do Quasar (`q-card`), sem sobrescrita — levemente arredondado.
- **Bolhas de chat**: radius assimétrico, 4px no canto que aponta pra origem (substitui a "seta" de balão de fala que o Quasar desenha por padrão, removida via CSS) e 16px nos outros três — enviada (`16px 16px 4px 16px`) e recebida (`4px 16px 16px 16px`) são espelhadas.
- **Campo de chat**: pílula completa (22px) — único input totalmente arredondado do sistema, reforça que é "a" caixa de entrada.
- **Círculos**: avatares de chat (34px), swatch de cor do tema (24px), indicador de disponibilidade do agente (9px) — todos `border-radius: 50%`.

## Components

### Buttons
- **Shape:** 6px (padrão Quasar), nunca reto.
- **Primary:** fundo `{colors.accent}` (a cor de destaque ativa), texto no par "on-accent" calculado por modo (nunca branco fixo). Usado em ação de confirmação (enviar mensagem, salvar).
- **Ghost/Flat:** sem fundo, texto na cor secundária (`--ap-muted`); vira cor de destaque quando ativo (aba selecionada, ação em progresso).
- **Outline semântico:** borda + texto na cor semântica (`color=negative outline`, `color=warning outline`) — ações de risco médio (arquivar, revogar) que precisam de atenção sem o peso visual de um botão sólido.
- **Sólido semântico:** fundo semântico sólido — reservado pra confirmação final de uma ação destrutiva (excluir definitivamente, remover).
- **Denso (`text-xs`):** ações secundárias dentro de listas (nova sessão, renomear).

### Chips / Badges
- **Status** (`ui.badge`): pill de cor de destaque sólida — estado do sistema ("ativo"), modo de acesso de conexão ("somente-leitura"), linguagem de arquivo no Editor.
- **Neutro:** fundo `surface-2`, borda `border` — quando o badge é informativo, não um estado que precisa de destaque (ex.: linguagem de arquivo).

### Cards / Containers
- **Corner Style:** radius padrão do Quasar, sem sobrescrita.
- **Background:** `surface`.
- **Shadow Strategy:** a sombra ambiente única (ver Elevation).
- **Border:** 1px `border`, sempre presente — a borda é o principal recurso de separação, não a sombra.

### Inputs / Fields
- **Style:** fundo `surface-2`, sem borda visível exceto o underline do Quasar na cor `border`; radius só no topo.
- **Focus:** herda o comportamento padrão do Quasar (underline na cor de destaque); nenhuma sobrescrita própria.

### Navigation (abas)
- **Style:** inativa usa a cor secundária (`--ap-muted`), ativa usa a cor de destaque, com um indicador (`q-tab__indicator`) na cor de destaque sob a aba selecionada. Sem ícone decorativo — cada aba é só o rótulo em maiúsculas (transformação do Quasar).

### Bolha de Chat (componente assinatura)
Sent (usuário) alinhada à direita, cor de destaque sólida, radius `16px 16px 4px 16px`; received (agente) alinhada à esquerda, cor de superfície, radius espelhado `4px 16px 16px 16px`, borda 1px. Avatar circular de 34px com iniciais em SVG, cores do tema. Nome do remetente e timestamp em label (11px) acima da bolha.

### Indicador de Disponibilidade (componente assinatura)
Ponto de 9px: verde parado (`--ap-success`) quando o agente está livre, âmbar pulsando (`--ap-warning`, `animation: ap-pulse 1.4s`) quando há execução em curso. Respeita `prefers-reduced-motion` — a animação desliga, a cor continua comunicando o estado sozinha.

## Do's and Don'ts

### Do:
- **Do** calcular o par de texto "on-*" (`--ap-on-accent`, `--ap-on-success`, etc.) pra qualquer novo fundo semântico ou de destaque — nunca assumir branco.
- **Do** manter o scroll do chat isolado (altura fixa + scroll interno) em vez de deixar a página inteira rolar.
- **Do** usar o indicador de disponibilidade (ponto colorido, com variante pulsante) pra qualquer estado "em progresso" análogo, respeitando `prefers-reduced-motion`.
- **Do** manter a borda como principal separador visual entre superfícies; a sombra é só reforço opcional.

### Don't:
- **Don't** usar as classes de cor crua do Tailwind (`text-gray-500`, `text-red-600`, etc.) ou do Quasar (`bg-primary`, `text-green-10`) sem mapear pro token do tema — elas quebram contraste no modo escuro (achado ao vivo documentado em `theme.py`).
- **Don't** introduzir uma segunda sombra ou nível de elevação — um token de sombra por modo é o teto.
- **Don't** introduzir um papel tipográfico "display"/"headline" — este é um painel Operate, não uma landing page.
- **Don't** fixar uma das 4 cores de destaque como "a" cor da marca em código novo — todo componente deve ler `--ap-accent`/`{colors.accent}`, nunca um hex de cor específica.
