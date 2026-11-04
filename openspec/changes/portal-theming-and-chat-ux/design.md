# Design

## Context

Ver proposal.md — Why.

O portal é NiceGUI sobre Quasar. As duas camadas trazem paletas próprias: o Quasar pinta por variáveis CSS (`--q-primary`, `--q-positive`, …) e por classes utilitárias (`bg-warning`, `text-white`), e o NiceGUI injeta a própria paleta depois do `<head>` da página. Não havia camada de tema no projeto; as cores vinham desses padrões.

Restrições que moldam a abordagem:

- As páginas autenticadas já passam todas por um ponto comum, `render_header`, que é o único lugar onde dá para injetar tema sem tocar em cada página.
- Os horários são gravados em UTC no banco e o container roda em UTC, então exibir o valor bruto mostraria horas erradas para o usuário.
- Os eventos ao vivo do agente trafegam em memória, por um dataclass separado do registro persistido, e não carregavam horário.

## Goals / Non-Goals

**Goals:**

- Uma única fonte de cor para o portal inteiro, de onde chat, formulários, avisos e componentes do Quasar derivem
- Legibilidade verificável — contraste medível em vez de avaliado a olho
- Mudança de tema sem recarregar o app inteiro na mão de quem desenvolve

**Non-Goals:**

- Tema por sistema ou por app gerada; a preferência é do usuário do portal
- Temas definidos pelo usuário final; o conjunto de modos e cores é fechado
- Alternância automática pela preferência do sistema operacional

## Decisions

### Tokens CSS como fonte única, com as variáveis do Quasar derivadas delas

Cada combinação de modo e cor produz um conjunto de tokens (`--ap-*` para o portal, `--ch-*` para o chat). As variáveis de marca do Quasar são derivadas desses tokens em vez de estilizadas separadamente.

Alternativa considerada: sobrescrever as classes utilitárias do Quasar (`bg-positive`, `text-white`) por CSS. Descartada porque disputa especificidade com a folha do framework e perde de forma difícil de prever — redefinir a variável que o framework já lê alcança o mesmo resultado sem disputa.

Consequência operacional: o `ui.colors()` do NiceGUI preenche com os defaults dele toda cor de marca que não for passada. Passar apenas uma delas faz o NiceGUI reescrever as outras por cima dos tokens, então a chamada precisa enumerar a paleta inteira.

### Pares "on-" para texto sobre preenchimento

Cada cor usada como preenchimento tem um par que define a cor do texto por cima. No modo escuro o destaque e as cores semânticas são tons claros, e o branco que o framework assume cairia para cerca de 3:1.

Alternativa considerada: escurecer o destaque no modo escuro para que o texto branco servisse. Descartada porque o destaque também é usado como texto — em links e abas ativas — onde ele precisa ser claro para contrastar com o fundo. Preenchimento e texto são papéis diferentes e pedem valores diferentes.

### Preferência no perfil do usuário, aplicada no servidor

A escolha fica em `User.theme` e o CSS sai montado no `<head>` da resposta. Isso elimina o flash de cor errada sem script de inicialização, e faz a preferência acompanhar o usuário entre navegadores.

Alternativa considerada: `localStorage` com um script no `<head>`. Funciona para o flash, mas é por navegador e deixa o estado dos botões do seletor fora de sincronia com o que a página já renderizou.

### Troca de tema recarrega a página

Trocar o tema grava a preferência e recarrega. Como o `<head>` já sai com os tokens certos, a recarga não tem flash.

Alternativa considerada: trocar o bloco de variáveis por JavaScript, sem recarregar. É mais fluido, mas alguns elementos não são alcançáveis por variável — os avatares do chat são imagens geradas no servidor com as cores assadas dentro. A recarga garante que tudo fique consistente ao custo de uma troca pouco frequente.

### Fuso de exibição configurável, conversão na formatação

Os horários continuam gravados em UTC; a conversão acontece na hora de exibir, usando um fuso vindo da configuração. Mantém o armazenamento sem ambiguidade e permite ajustar a exibição sem migração.

### Horário no nome do remetente, não no carimbo do componente

O componente de mensagem do Quasar tem um campo de carimbo próprio, mas ele renderiza dentro da bolha. Como o horário deve aparecer fora dela, ele acompanha o nome do remetente, que já é renderizado acima da bolha.

### Notificações sem o tipo semântico do framework

As notificações do portal não usam o `type` do Quasar, que aplica uma classe de fundo própria. Em vez disso, levam uma classe do portal, e o significado vai no ícone e numa barra lateral colorida pelos tokens.

Alternativa considerada: manter o `type` e sobrescrever o fundo. Descartada pela mesma razão da primeira decisão — a classe do framework vence a sobrescrita.

### Contraste verificado por medição

A relação de contraste é calculada para cada par de texto e fundo das 12 combinações, e a interface renderizada é varrida calculando o fundo efetivo de cada texto visível. O limite é o WCAG AA: 4.5:1 para texto normal e 3:1 para texto grande.

A varredura cobre o que está renderizado no momento, então estados transitórios — dicas de ferramenta, menus abertos, foco e passagem do mouse — ficam fora e dependem dos tokens estarem corretos.

## Risks / Trade-offs

- **Dependência da estrutura interna do Quasar.** Parte do estilo mira classes do framework. Uma atualização que renomeie essas classes pode soltar regras sem erro visível. A varredura de contraste é a rede de proteção: ela acusa o efeito mesmo sem apontar a causa.
- **Recarga ao trocar de tema.** Perde a posição de rolagem do chat. Aceitável pela frequência da ação, mas é um incômodo real para quem experimenta temas.
- **Fuso único para todos.** Usuários em fusos diferentes veem os horários no fuso configurado no portal, não no deles. Resolver isso exigiria converter no navegador.
- **Cobertura da varredura.** Zero falhas significa zero falhas nas telas visitadas, nos estados em que estavam. Telas e estados não visitados não estão verificados.
