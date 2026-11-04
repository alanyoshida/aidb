# Design

## Context

Ver proposal.md — Why.

O chat recebe os eventos da execução por um laço que consulta o buffer do agente e anexa cada novo evento ao log. Os eventos são de naturezas diferentes: mensagens do agente, marcadores de transição da execução, e o detalhe técnico — cada comando rodado e cada arquivo tocado.

Já existia um filtro para os comandos, feito por CSS sobre elementos marcados com uma classe, alternada por um interruptor. Os arquivos alterados ficaram de fora desse filtro.

## Goals / Non-Goals

**Goals:**

- Tratar comandos e arquivos alterados pelo mesmo critério, já que são o mesmo tipo de conteúdo para quem lê
- Alternar o filtro sem custo perceptível e sem perder o que já chegou

**Non-Goals:**

- Filtro por tipo individual de evento, ou níveis de verbosidade
- Preferência de debug persistida entre sessões; o interruptor volta ao padrão a cada carga
- Mudar o que o agente emite; o filtro é só de exibição

## Decisions

### Filtro por CSS sobre elementos já renderizados

O detalhe continua sendo renderizado e anexado ao log; o que muda é uma classe no container, que esconde os elementos marcados. Alternar o interruptor não re-renderiza nada.

Alternativa considerada: filtrar na origem, decidindo no momento de renderizar se o evento entra no log. Seria menos DOM, mas ligar o debug no meio de uma execução não traria de volta o que já passou — o editor veria apenas os eventos a partir dali. Como o uso típico do debug é justamente entender o que acabou de acontecer, perder o histórico anula o propósito.

### Conjunto de tipos em vez de comparação literal

A marcação passou a consultar um conjunto de tipos de evento. Incluir outro tipo no futuro é acrescentar um nome, sem tocar na lógica de renderização.

### Classes renomeadas de "command" para "debug"

Com arquivos alterados no mesmo grupo, um nome que falava em comando descreveria mal o que o grupo contém. O nome passou a refletir o critério — o que o modo debug controla — e não um dos seus membros.

## Risks / Trade-offs

- **O detalhe continua no DOM.** Execuções muito longas acumulam elementos ocultos, com custo de memória que um filtro na origem não teria. É o preço de poder ligar o debug retroativamente, e nada no uso atual sugere que esse custo importe.
- **Esconder por padrão pode atrasar o diagnóstico.** Quem não conhece o interruptor pode não perceber que há detalhe disponível. O rótulo nomeia os dois tipos justamente para reduzir isso.
