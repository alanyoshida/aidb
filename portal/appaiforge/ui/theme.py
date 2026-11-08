"""Tema do portal — 3 modos × 4 cores de destaque = 12 combinações.

A preferência fica em `User.theme` (chave "<modo>-<cor>"). O CSS é emitido no
head já com os tokens do usuário, então não há flash de cor errada na carga.
A troca em runtime reescreve apenas o bloco :root, sem recarregar a página.

Contraste: todas as combinações de texto/fundo abaixo foram escolhidas para
ficar em pelo menos 4.5:1 (WCAG AA para texto normal).
"""

from typing import Final

# base  -> destaque forte sobre fundo claro (texto branco por cima, >= 4.5:1)
# dark  -> destaque claro para o modo escuro (texto #0f172a por cima)
# soft  -> fundo tingido do modo pastel
# edge  -> borda tingida do modo pastel
ACCENTS: Final[dict[str, dict]] = {
    "indigo": {"name": "Índigo", "base": "#4f46e5", "dark": "#818cf8", "soft": "#eef2ff", "edge": "#c7d2fe"},
    "teal": {"name": "Teal", "base": "#0f766e", "dark": "#2dd4bf", "soft": "#f0fdfa", "edge": "#99f6e4"},
    "amber": {"name": "Âmbar", "base": "#b45309", "dark": "#fbbf24", "soft": "#fffbeb", "edge": "#fde68a"},
    "violet": {"name": "Violeta", "base": "#6d4aff", "dark": "#a78bfa", "soft": "#f5f3ff", "edge": "#ddd6fe"},
}

MODES: Final[tuple[str, ...]] = ("light", "dark", "pastel")
MODE_LABELS: Final[dict[str, str]] = {"light": "Light", "dark": "Dark", "pastel": "Pastel"}
MODE_ICONS: Final[dict[str, str]] = {"light": "light_mode", "dark": "dark_mode", "pastel": "palette"}
DEFAULT_THEME: Final[str] = "light-indigo"


def parse_key(key: str | None) -> tuple[str, str]:
    """Divide "<modo>-<cor>" validando contra os valores conhecidos."""
    mode, _, accent = (key or "").partition("-")
    if mode not in MODES or accent not in ACCENTS:
        return "light", "indigo"
    return mode, accent


# Secundário dos modos claros: #64748b ficava em 4.26:1 sobre os fundos tingidos,
# abaixo de AA. Este tom mantém a hierarquia visual com folga (>= 5:1).
_MUTED_LIGHT: Final[str] = "#5b6878"

# As iniciais do avatar são 12px: pintá-las com o destaque caía para 3.5:1 sobre
# os tints. O slate escuro passa com folga e o círculo segue carregando a cor.
_AVATAR_TXT_LIGHT: Final[str] = "#334155"

# Cores semânticas dos fundos claros (os tons escuros ficam inline no modo dark).
_SEMANTIC_LIGHT: Final[dict[str, str]] = {
    "--ap-danger": "#dc2626",
    "--ap-danger-bg": "#fef2f2",
    "--ap-danger-border": "#fecaca",
    "--ap-success": "#15803d",
    "--ap-warning": "#b45309",
    # nos fundos claros as cores semânticas são escuras, então texto branco serve
    "--ap-on-success": "#ffffff",
    "--ap-on-danger": "#ffffff",
    "--ap-on-warning": "#ffffff",
}


def tokens(mode: str, accent_id: str) -> dict[str, str]:
    """Tokens CSS de uma combinação. `--ap-*` = portal, `--ch-*` = chat."""
    a = ACCENTS[accent_id]

    if mode == "dark":
        accent, on_accent = a["dark"], "#0f172a"
        shared = {
            "--ap-bg": "#0b1220",
            "--ap-surface": "#1e293b",
            "--ap-surface-2": "#273449",
            "--ap-text": "#e2e8f0",
            "--ap-muted": "#94a3b8",
            "--ap-border": "#334155",
            "--ap-header-bg": "#0b1220",
            "--ap-header-text": "#e2e8f0",
            "--ap-shadow": "0 1px 3px rgba(0,0,0,0.5)",
            "--ap-danger": "#fca5a5",
            "--ap-danger-bg": "rgba(239,68,68,0.12)",
            "--ap-danger-border": "#991b1b",
            "--ap-success": "#4ade80",
            "--ap-warning": "#fbbf24",
            # no escuro as semânticas são claras: o texto por cima precisa ser escuro
            "--ap-on-success": "#0f172a",
            "--ap-on-danger": "#0f172a",
            "--ap-on-warning": "#0f172a",
            "--ch-chat-bg": "#0f172a",
            "--ch-agent-bg": "#1e293b",
            "--ch-agent-txt": "#e2e8f0",
            "--ch-agent-bdr": "#334155",
            "--ch-avatar-bg": "#334155",
            "--ch-avatar-txt": "#cbd5e1",
        }
    elif mode == "pastel":
        accent, on_accent = a["base"], "#ffffff"
        shared = {
            "--ap-bg": a["soft"],
            "--ap-surface": "#ffffff",
            "--ap-surface-2": a["soft"],
            "--ap-text": "#1e293b",
            "--ap-muted": _MUTED_LIGHT,
            "--ap-border": a["edge"],
            "--ap-header-bg": "#ffffff",
            "--ap-header-text": "#1e293b",
            "--ap-shadow": "0 1px 3px rgba(15,23,42,0.08)",
            **_SEMANTIC_LIGHT,
            "--ch-chat-bg": a["soft"],
            "--ch-agent-bg": "#ffffff",
            "--ch-agent-txt": "#1e293b",
            "--ch-agent-bdr": a["edge"],
            "--ch-avatar-bg": a["edge"],
            "--ch-avatar-txt": _AVATAR_TXT_LIGHT,
        }
    else:  # light
        accent, on_accent = a["base"], "#ffffff"
        shared = {
            "--ap-bg": "#f1f2f8",
            "--ap-surface": "#ffffff",
            "--ap-surface-2": "#f8fafc",
            "--ap-text": "#1e293b",
            "--ap-muted": _MUTED_LIGHT,
            "--ap-border": "#e2e8f0",
            "--ap-header-bg": "#ffffff",
            "--ap-header-text": "#1e293b",
            "--ap-shadow": "0 1px 3px rgba(15,23,42,0.08)",
            **_SEMANTIC_LIGHT,
            "--ch-chat-bg": "#fafbff",
            "--ch-agent-bg": "#ffffff",
            "--ch-agent-txt": "#1e293b",
            "--ch-agent-bdr": "#e8ecf0",
            "--ch-avatar-bg": "#e8eaf6",
            "--ch-avatar-txt": _AVATAR_TXT_LIGHT,
        }

    return {
        **shared,
        "--ap-accent": accent,
        "--ap-on-accent": on_accent,
        # Quasar pinta por estas variáveis: redefini-las acerta botões, badges e
        # ícones de uma vez, sem disputar especificidade com as classes bg-*/text-*.
        "--q-primary": accent,
        "--q-positive": shared["--ap-success"],
        "--q-negative": shared["--ap-danger"],
        "--q-warning": shared["--ap-warning"],
        "--q-info": accent,
        "--ch-user-bg": accent,
        "--ch-user-txt": on_accent,
    }


def css_vars(key: str) -> str:
    """Bloco `:root { ... }` de uma chave de tema."""
    mode, accent = parse_key(key)
    body = ";".join(f"{k}:{v}" for k, v in tokens(mode, accent).items())
    return f":root{{{body}}}"


# --- CSS do portal --------------------------------------------------------
# Tudo lê os tokens, então uma única folha serve aos 12 temas.
PORTAL_CSS: Final[str] = """
body, .nicegui-content, .q-layout, .q-page-container, .q-page {
  background: var(--ap-bg) !important;
  color: var(--ap-text);
}
.q-header { background: var(--ap-header-bg) !important; color: var(--ap-header-text) !important;
  border-bottom: 1px solid var(--ap-border); box-shadow: none !important; }
.q-header .q-btn, .q-header .q-icon { color: var(--ap-header-text) !important; }
.ap-brand { color: var(--ap-accent) !important; }

.q-card, .q-menu, .q-tab-panel, .q-tab-panels, .q-expansion-item__content {
  background: var(--ap-surface) !important; color: var(--ap-text) !important; }
.q-card { border: 1px solid var(--ap-border); box-shadow: var(--ap-shadow) !important; }
.q-separator { background: var(--ap-border) !important; }

/* Tabs: inativa usa o tom secundário, ativa o destaque. O Quasar aplica
   opacity:0.85 na aba inativa por cima da cor — suficiente pra derrubar
   --ap-muted (escolhido pra ficar >=5:1 em opacidade cheia) pra 3.7:1 no modo
   claro (achado do critique: #5b6878 a 85% sobre #f1f2f8 vira #727d8b). A
   hierarquia já vem da cor (--ap-muted vs. --ap-accent); a opacidade some. */
.q-tabs { color: var(--ap-muted) !important; }
.q-tab:not(.q-tab--active) { opacity: 1 !important; }
.q-tab--active { color: var(--ap-accent) !important; }
.q-tabs .q-tab__indicator { background: var(--ap-accent) !important; }

/* Campos de formulário. O variant padrão do Quasar é só um underline e por isso
   não tem padding lateral; ao pintar o fundo ele vira caixa, então é preciso
   devolver o respiro e arredondar. O underline nativo é preto e some no escuro. */
.q-field--standard .q-field__control {
  background: var(--ap-surface-2) !important;
  padding: 0 12px !important;
  border-radius: 6px 6px 0 0 !important; }
.q-field--standard .q-field__control::before {
  border-bottom-color: var(--ap-border) !important; }
.q-field__native, .q-field__input, .q-field__prefix, .q-field__suffix { color: var(--ap-text) !important; }
.q-field__label, .q-field__marginal { color: var(--ap-muted) !important; }

/* Tabelas / listas. */
.q-table, .q-table tbody td, .q-table thead th { background: var(--ap-surface) !important; color: var(--ap-text) !important; }
.q-table thead th { color: var(--ap-muted) !important; }
.q-item { color: var(--ap-text) !important; }
.q-item__label, .q-item__label--caption { color: var(--ap-text) !important; }
/* Árvore da aba Editor: o Quasar fixa a cor da .q-tree na própria raiz
   (preto) e só troca com body--dark, que este tema não usa. O rótulo do
   nó é um div sem classe, então a correção precisa ser na raiz da árvore. */
.q-tree { color: var(--ap-text) !important; }
.q-tree .q-tree__icon { color: var(--ap-text) !important; }
.q-tree .q-tree__node-header-content div { color: var(--ap-text) !important; }
.q-tree .q-tree__node--selected .q-tree__node-header-content {
  color: var(--ap-accent) !important; }
.q-tree .q-tree__node--selected .q-tree__node-header-content div {
  color: var(--ap-accent) !important; }

/* As utilitárias de cor do Tailwind quebrariam no modo escuro (vermelho escuro
   sobre fundo escuro, p.ex.): mapeia todas para tokens que acompanham o modo. */
.text-gray-300, .text-gray-400, .text-gray-500, .text-gray-600, .text-gray-700, .text-gray-800 {
  color: var(--ap-muted) !important; }
.text-red-400, .text-red-500, .text-red-600, .text-red-700 { color: var(--ap-danger) !important; }
.text-green-600, .text-green-700 { color: var(--ap-success) !important; }
.text-amber-600, .text-amber-700, .text-orange-600, .text-orange-700 { color: var(--ap-warning) !important; }
/* Os cards de gate/pergunta no chat usam o prop text-color do Quasar
   (ex.: ui.chat_message(...).props("text-color=green-10")), que gera estas
   classes fixas da paleta do Quasar — nunca foram pensadas pro tema escuro
   (green-10/blue-10 são tons escuros, pra fundo claro) e ficavam ilegíveis
   sobre a bolha escura do agente (achado ao vivo). Mesmo tratamento acima.

   Precisam de `@layer theme` (não só !important solto): o NiceGUI declara
   `@layer theme, base, quasar, nicegui, components, utilities, overrides,
   quasar_importants` no documento, e `.text-blue-10` etc. do próprio Quasar
   vivem dentro da layer `quasar_importants` com `!important`. Pela regra de
   cascata de layers, `!important` inverte a ordem (layer mais cedo vence) E
   qualquer coisa fora de layer nenhuma perde pra qualquer layer nomeada —
   aumentar especificidade sozinho não resolve, confirmado ao vivo (achado do
   critique: contraste 1.69:1 na "PERGUNTA DO AGENTE" no modo escuro, o
   `.text-blue-10` cru do Quasar vencendo mesmo com um seletor mais
   específico aqui). `theme` é a primeira layer declarada, então ganha de
   `quasar_importants` (a última) nessa inversão. */
@layer theme {
  .text-red-10 { color: var(--ap-danger) !important; }
  .text-orange-10 { color: var(--ap-warning) !important; }
  .text-green-10 { color: var(--ap-success) !important; }
  .text-blue-10 { color: var(--ap-accent) !important; }
  /* Mesmo card, metade do problema (achado de uma segunda rodada de
     critique): o fundo (`bg-color=orange-2` etc., mesmo prop do Quasar que
     gera o text-color acima) sofre do mesmo empate de layer — sem isto,
     fica o pastel claro cru do Quasar atrás de QUALQUER tema, inclusive o
     escuro. Em vez de tingir o fundo por classe (exigiria 4 tokens `-bg`
     novos), reusa a superfície neutra do tema — mesmo padrão já usado nas
     notificações (`.q-notification.ap-notify`, abaixo): o fundo é neutro,
     o significado semântico mora só na cor do texto (já corrigida acima). */
  .bg-red-2, .bg-orange-2, .bg-green-2, .bg-blue-2 { background: var(--ap-surface-2) !important; }
}
.bg-red-50 { background: var(--ap-danger-bg) !important; }
.border-red-300, .border-red-400 { border-color: var(--ap-danger-border) !important; }
.border-orange-400 { border-color: var(--ap-warning) !important; }
.text-blue-700 { color: var(--ap-accent) !important; }
.border-blue-400 { border-color: var(--ap-accent) !important; }
.bg-white { background: var(--ap-surface) !important; }
.text-primary { color: var(--ap-accent) !important; }

/* Notificações: o padrão do Quasar põe texto branco sobre ciano (1.9:1) e verde
   (2.4:1). Aqui o fundo é a superfície do tema e a cor semântica vai para o
   ícone e para a barra lateral, o que mantém o significado e a legibilidade.
   O seletor composto é preciso de propósito: precisa vencer o .text-white que
   o Quasar aplica na raiz da notificação. */
.q-notification.ap-notify {
  background: var(--ap-surface) !important; color: var(--ap-text) !important;
  border: 1px solid var(--ap-border) !important; border-left-width: 4px !important;
  box-shadow: var(--ap-shadow) !important; }
.q-notification.ap-notify .q-notification__message { color: var(--ap-text) !important; }
/* Mais específicas que a regra base acima, senão o `border` dela vence a barra. */
.q-notification.ap-notify.ap-notify--info { border-left-color: var(--ap-accent) !important; }
.q-notification.ap-notify.ap-notify--positive { border-left-color: var(--ap-success) !important; }
.q-notification.ap-notify.ap-notify--negative { border-left-color: var(--ap-danger) !important; }
.q-notification.ap-notify.ap-notify--warning { border-left-color: var(--ap-warning) !important; }
.ap-notify--info .q-icon { color: var(--ap-accent) !important; }
.ap-notify--positive .q-icon { color: var(--ap-success) !important; }
.ap-notify--negative .q-icon { color: var(--ap-danger) !important; }
.ap-notify--warning .q-icon { color: var(--ap-warning) !important; }

/* Texto sobre preenchimentos coloridos. O Quasar assume branco, mas no modo
   escuro o destaque e as semânticas são tons claros — branco cai para ~3:1.
   Cada preenchimento usa o seu par "on-". O seletor desce até os filhos de
   propósito: na raiz do botão a regra perde para o .text-white do Quasar,
   mas a descendente vence. */
.q-btn.bg-primary, .q-badge.bg-primary, .q-chip.bg-primary,
.q-btn.bg-primary .q-btn__content, .q-btn.bg-primary .q-btn__content *,
.q-badge.bg-primary *, .q-chip.bg-primary * { color: var(--ap-on-accent) !important; }
.q-btn.bg-positive, .q-badge.bg-positive, .q-chip.bg-positive,
.q-btn.bg-positive .q-btn__content, .q-btn.bg-positive .q-btn__content *,
.q-badge.bg-positive *, .q-chip.bg-positive * { color: var(--ap-on-success) !important; }
.q-btn.bg-negative, .q-badge.bg-negative, .q-chip.bg-negative,
.q-btn.bg-negative .q-btn__content, .q-btn.bg-negative .q-btn__content *,
.q-badge.bg-negative *, .q-chip.bg-negative * { color: var(--ap-on-danger) !important; }
.q-btn.bg-warning, .q-badge.bg-warning, .q-chip.bg-warning,
.q-btn.bg-warning .q-btn__content, .q-btn.bg-warning .q-btn__content *,
.q-badge.bg-warning *, .q-chip.bg-warning * { color: var(--ap-on-warning) !important; }

/* Badges neutros do Quasar (grey/blue-grey) ficavam branco sobre cinza médio. */
.q-badge.bg-grey, .q-badge.bg-blue-grey, .q-chip.bg-grey, .q-chip.bg-blue-grey {
  background: var(--ap-surface-2) !important; color: var(--ap-text) !important;
  border: 1px solid var(--ap-border) !important; }

/* Aviso de conexão perdida do NiceGUI: o fundo branco é dele, mas o texto herda
   o do tema — no modo escuro isso dava claro sobre branco. Mesmo tratamento das
   notificações. */
.nicegui-error-popup {
  background: var(--ap-surface) !important; color: var(--ap-text) !important;
  border: 1px solid var(--ap-border) !important;
  border-left: 4px solid var(--ap-warning) !important;
  box-shadow: var(--ap-shadow) !important; }
.nicegui-error-popup .q-icon, .nicegui-error-popup svg { color: var(--ap-warning) !important; }

/* Indicador de disponibilidade do agente: verde parado quando livre, âmbar
   pulsando quando há trabalho em curso. */
.ap-dot { width: 9px; height: 9px; border-radius: 50%; flex: none; display: inline-block;
  background: var(--ap-success); transition: background 200ms ease; }
.ap-dot--busy { background: var(--ap-warning); animation: ap-pulse 1.4s ease-in-out infinite; }
@keyframes ap-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.72); }
}
@media (prefers-reduced-motion: reduce) { .ap-dot--busy { animation: none; } }

/* Seletor de tema na topbar: o botão do Quasar traz padding/altura próprios,
   então as medidas precisam vencer para o swatch sair redondo. */
.ap-swatch { width: 24px !important; height: 24px !important;
  min-width: 24px !important; min-height: 24px !important;
  padding: 0 !important; border-radius: 50% !important; }
.ap-swatch .q-btn__content { display: none; }
.ap-swatch--on { box-shadow: 0 0 0 2px var(--ap-surface), 0 0 0 4px var(--ap-text) !important; }
"""

# --- CSS do chat ----------------------------------------------------------
CHAT_CSS: Final[str] = """
.af-chat-scroll, .af-chat-scroll .q-scrollarea__content {
  background: var(--ch-chat-bg) !important; }
.af-chat-scroll { border: 1px solid var(--ap-border) !important; border-radius: 14px !important; }

/* Mesma causa do bug de truncamento da sidebar (ver .af-chat-sidebar abaixo):
   o `.q-scrollarea__content` do log cresce pra caber o conteúdo (é assim que
   a QScrollArea sabe que precisa rolar) — sem travar a largura em 100%, uma
   bolha de mensagem um pouco mais longa empurrava o conteúdo da área de
   scroll pra mais largo que a viewport, cortando a mensagem fora da tela em
   vez de quebrar linha (achado ao vivo, mais grave no mobile: bolha e
   resultado de comando ficavam ilegíveis sem rolar na horizontal). O Quasar
   já tem `word-break: break-word` em `.q-message-text`, então só faltava a
   largura disponível ser real. */
.af-chat-scroll .q-scrollarea__content { max-width: 100%; }

/* Bloco ```código``` dentro de uma resposta markdown (ex.: saída de um
   comando): `<pre>` tem `white-space: pre` por padrão — não quebra linha,
   então ainda estourava a bolha mesmo com o fix acima. Rolagem própria,
   contida no bloco (comportamento esperado pra código), em vez de crescer e
   levar a bolha/página inteira junto. */
.q-message-text pre { max-width: 100%; overflow-x: auto; }

/* Sem as "setas" padrão do Quasar: o visual é de cartão. */
.q-message-text::before, .q-message-text::after { display: none !important; }

/* A coluna do NiceGUI usa align-items:flex-start, então a bolha do usuário
   precisa se alinhar sozinha à direita. */
.q-message-sent { align-self: flex-end !important; }
.q-message-received { align-self: flex-start !important; }

.q-message-received .q-message-text--received {
  background: var(--ch-agent-bg) !important; color: var(--ch-agent-txt) !important;
  border: 1px solid var(--ch-agent-bdr) !important;
  border-radius: 4px 16px 16px 16px !important;
  box-shadow: var(--ap-shadow) !important; padding: 10px 14px !important; }

/* O Quasar fixa color:#000 neste div interno, que vence a cor da bolha e deixa
   o texto do agente preto no fundo escuro. Os filhos herdam daqui. */
.q-message-text-content--received { color: var(--ch-agent-txt) !important; }
.q-message-text-content--sent { color: var(--ch-user-txt) !important; }

.q-message-sent .q-message-text--sent {
  background: var(--ch-user-bg) !important; color: var(--ch-user-txt) !important;
  border-radius: 16px 16px 4px 16px !important;
  padding: 10px 14px !important; }
.q-message-sent .q-message-text--sent > div { color: var(--ch-user-txt) !important; }

.q-message-avatar { width: 34px !important; height: 34px !important; min-width: 34px !important; }
.q-message-name { font-size: 11px !important; color: var(--ap-muted) !important; margin-bottom: 3px !important; }

.af-chat-input .q-field__control { border-radius: 22px !important; background: var(--ap-surface-2) !important;
  padding: 0 16px !important; border: 1px solid var(--ap-border) !important; }
.af-chat-send { background: var(--ap-accent) !important; color: var(--ap-on-accent) !important; }
.af-chat-send .q-icon { color: var(--ap-on-accent) !important; }

/* Botão de sessão na sidebar: um título longo (+ " · horário" concatenado)
   só cortava sem reticências. Duas causas empilhadas: (1) o texto real do
   Quasar mora dentro de `.q-btn__content > .block`, não no `<button>` em
   si, então `overflow`/`text-overflow` no botão não tinha efeito nenhum;
   (2) o `.q-scrollarea__content` da lista de sessões cresce pra caber o
   conteúdo (é assim que a QScrollArea sabe que precisa rolar) — sem travar
   a largura em 100%, o botão simplesmente empurrava o conteúdo da área de
   scroll pra mais largo que os 256px da sidebar, cortando o texto fora da
   viewport em vez de truncar com reticências. */
.af-chat-sidebar .q-scrollarea__content { max-width: 100%; }
.af-session-btn .q-btn__content { min-width: 0; flex-wrap: nowrap; }
.af-session-btn .q-btn__content > .block {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }

/* Sidebar de sessões do Chat: coluna fixa à esquerda no desktop. Abaixo de
   700px ela não cabe ao lado do chat sem empurrar tudo pra baixo (achado do
   critique) — vira um drawer deslizante, escondido por padrão, com um botão
   de hambúrguer (só visível nessa largura) e um fundo escurecido pra fechar
   ao tocar fora. */
.af-chat-sidebar-toggle, .af-chat-backdrop { display: none; }

@media (max-width: 700px) {
  .af-chat-sidebar-toggle { display: inline-flex !important; }
  .af-chat-sidebar {
    /* 2100/2050: o header do NiceGUI (.q-header) usa z-index 2000 — abaixo
       disso o drawer "abria" de verdade (classe e transform certos) mas
       ficava pintado por baixo do header, invisível na prática. */
    position: fixed; top: 0; left: 0; height: 100vh; z-index: 2100;
    max-width: 85vw; margin: 0 !important;
    background: var(--ap-surface); border-right: 1px solid var(--ap-border);
    box-shadow: var(--ap-shadow);
    padding: 16px 12px; overflow-y: auto;
    transform: translateX(-100%);
    transition: transform .2s ease;
  }
  .af-chat-sidebar.af-open { transform: translateX(0); }
  .af-chat-backdrop.af-open {
    display: block; position: fixed; inset: 0; z-index: 2050;
    background: rgba(15, 23, 42, 0.4);
  }
}
"""


def head_html(key: str) -> str:
    """Tokens do usuário + folhas do portal/chat, emitidos no head (sem flash)."""
    return (
        f'<style id="aidb-theme">{css_vars(key)}</style>'
        f"<style>{PORTAL_CSS}{CHAT_CSS}</style>"
    )


def avatar_svg(bg: str, fg: str, letters: str) -> str:
    """data-URI de um avatar circular com iniciais, nas cores do tema."""
    bg, fg = bg.replace("#", "%23"), fg.replace("#", "%23")
    return (
        "data:image/svg+xml,%3Csvg width='34' height='34' xmlns='http://www.w3.org/2000/svg'%3E"
        f"%3Ccircle cx='17' cy='17' r='17' fill='{bg}'/%3E"
        "%3Ctext x='17' y='22' font-family='sans-serif' font-size='12' font-weight='700' "
        f"fill='{fg}' text-anchor='middle'%3E{letters}%3C/text%3E%3C/svg%3E"
    )
