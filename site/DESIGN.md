---
name: AIDB — site
description: Site de apresentação e documentação do AIDB, sobre Astro Starlight
colors:
  accent-light: "#4f46e5"
  accent-dark: "#7f88ff"
  accent-high-light: "#2c279a"
  accent-high-dark: "#c9ccff"
  ink-light: "#0c1017"
  ground-light: "#fcfcfd"
  ground-dark: "#0c1017"
  surface-light: "#ffffff"
  surface-dark: "#121722"
  line-light: "#e1e5ee"
  line-dark: "#252c3a"
  muted-light: "#4c5568"
  muted-dark: "#8790a1"
  ok-light: "#15803d"
  ok-dark: "#4ade80"
  no-light: "#be123c"
  no-dark: "#fb7185"
typography:
  display:
    fontFamily: "Geist Variable, -apple-system, Segoe UI, sans-serif"
    fontSize: "clamp(2.25rem, 1.3rem + 2.4vw, 3.4rem)"
    fontWeight: 680
    lineHeight: 1.04
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Geist Variable, -apple-system, Segoe UI, sans-serif"
    fontSize: "clamp(1.75rem, 1.1rem + 1.8vw, 2.5rem)"
    fontWeight: 660
    lineHeight: 1.1
    letterSpacing: "-0.025em"
  body:
    fontFamily: "Geist Variable, -apple-system, Segoe UI, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 400
    lineHeight: 1.6
  code:
    fontFamily: "Geist Mono Variable, ui-monospace, monospace"
    fontSize: "0.82rem"
    fontWeight: 400
    lineHeight: 1.45
rounded:
  control: "8px"
  surface: "12px"
  shot: "10px"
components:
  button-primary:
    backgroundColor: "{colors.accent-light}"
    textColor: "#ffffff"
    rounded: "{rounded.control}"
    height: "2.75rem"
    padding: "0 1.15rem"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-light}"
    rounded: "{rounded.control}"
    height: "2.75rem"
  product-shot:
    backgroundColor: "{colors.surface-light}"
    rounded: "{rounded.shot}"
---

# Design System: AIDB — site

Este arquivo descreve o site em `site/`. O portal tem o próprio sistema, em `../DESIGN.md`; os dois
não compartilham tokens.

## Overview

O padrão da categoria executado com rigor, com Tailscale e Teleport como régua: sobriedade de
produto de segurança, prova pela interface real e por diagramas, nenhum neon, glow ou gradiente
decorativo. A página inicial segue o tema do sistema operacional (claro ou escuro) e funciona nos
dois; a documentação é o Starlight com o mesmo tema.

## Colors

Restrito: neutros frios, um índigo de ação, e um par semântico usado só para o gate de SQL.

- **Índigo** (`#4f46e5` claro, `#7f88ff` escuro): botão primário, links, aba ativa, foco, seleção.
  Nenhuma outra cor faz papel de ação.
- **Neutros**: fundo quase branco (`#fcfcfd`) ou quase preto azulado (`#0c1017`); superfície
  (`#ffffff` / `#121722`); linhas (`#e1e5ee` / `#252c3a`).
- **Aprovado / recusado** (`#15803d`/`#4ade80` e `#be123c`/`#fb7185`, com fundos suaves): só nas
  decisões do gate e no `DROP` do título da seção do gate.

**A regra do par semântico.** Verde e vermelho significam "executa" e "recusada". Não aparecem como
decoração nem em estados genéricos de sucesso/erro da página.

## Typography

Geist Variable para tudo, Geist Mono Variable só para código e comandos SQL. Títulos com peso
640 a 680 e tracking negativo (-0.022em a -0.03em); corpo a 1.6 de entrelinha. Números em tabelas
com `tabular-nums`.

## Layout

Página inicial com largura de conteúdo de 76rem; seções separadas por espaço (4.5rem a 8rem), não
por cartões. Composições de duas colunas assimétricas (texto 4–5 frações, prova 7–8) que viram uma
coluna abaixo de 60rem. Grades sempre com `minmax(0, 1fr)`, para código e tabelas rolarem por
dentro em vez de alargar a página.

## Elevation & Depth

Uma sombra só (`--aidb-shadow`), usada nos screenshots do produto e no painel da demonstração do
gate. O resto se separa por linha de 1px.

## Shapes

Controles com 8px, superfícies com 12px, screenshots com 10px. Os pontos e marcas do gate são os
únicos círculos.

## Components

- **Screenshot do produto**: imagem real com borda de 1px, raio de 10px e a sombra única; o do hero
  ganha uma barra de navegador discreta com o endereço.
- **Demonstração do gate**: cada comando SQL passa por uma linha até o gate; aprovado segue em verde
  até o banco, recusado para no gate em vermelho e o trecho até o banco fica pontilhado. A animação
  só começa com JavaScript e some com `prefers-reduced-motion`.
- **Pilha de camadas**: lista com linhas divisórias, nome à esquerda e o que impede à direita; o
  hover desloca o texto e tinge o fundo com 7% do índigo.
- **Diagramas Mermaid**: nós na cor de superfície com contorno índigo, grupos em cinza translúcido,
  rótulos de aresta sobre o fundo da página.

## Do's and Don'ts

- **Do** usar screenshots reais, com dados de demonstração e a origem embutida no arquivo.
- **Do** escrever o limite junto da promessa: a área de segurança tem "Limites conhecidos".
- **Don't** inventar clientes, números de adoção ou depoimentos.
- **Don't** usar verde ou vermelho fora das decisões do gate.
- **Don't** escrever versão do produto à mão: ela vem de `portal/pyproject.toml` no build.
