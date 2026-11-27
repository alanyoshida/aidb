---
version: 1
slug: "site"
primary_target: "site"
related_targets: []
---

# Site de apresentação e documentação (site/)

Escopo: GitHub Pages do AIDB. Página inicial em modo Persuade; documentação em modo Read (Astro Starlight).
Público: gestor que decide adotar o AIDB; depois, o time técnico que instala e audita a segurança.
Ação: ver o produto funcionando (screenshots reais com dados de demonstração) e seguir para a documentação.
Prova: só o que o produto faz de verdade; nada de clientes, números ou depoimentos inventados.
Restrições: pt-BR; versão lida de portal/pyproject.toml, nunca escrita à mão; docs/ continua a fonte da verdade da referência.

## Direction contract

THESIS: O padrão da categoria executado com rigor (régua: Tailscale e Teleport). Recusa o template de dev tool genérico com neon e glow: sobriedade de produto de segurança, prova pela interface real e por diagramas claros.

OWN-WORLD: Fundo quase preto azulado no escuro e papel frio no claro; um índigo como única cor de ação; verde e vermelho só para aprovado/recusado do gate. Grotesco de interface com números tabulares; mono só para comandos. Screenshots em moldura de navegador discreta, diagramas com traço fino.

STORY: O gestor entende em uma tela que o AIDB gera apps administrativas a partir de um chat sobre o banco real, e acredita que é seguro porque vê as camadas (kernel, gate de SQL, proxy, segredos) e a interface funcionando. Ele clica em Ver como funciona ou Instalar.

FIRST VIEWPORT: Título à esquerda em duas linhas, subtítulo de uma frase, dois botões (Começar / Ver a segurança). À direita, maior que o texto, o screenshot do chat gerando uma app, com uma recusa do gate visível. Faixa curta abaixo com os bancos suportados.

FORM: canon (padrão da categoria), escolhido pelo usuário na rodada de direção; seed:a34f65cd0bd5e3f2

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
