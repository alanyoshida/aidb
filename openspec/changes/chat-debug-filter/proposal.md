# Proposal

## Why

O chat mistura dois tipos de conteúdo: a conversa com o agente e o detalhe técnico da execução — cada comando rodado e cada arquivo tocado. Em execuções longas o detalhe domina a tela e a conversa se perde. O portal já escondia os comandos atrás de um interruptor de debug, mas os arquivos alterados continuavam sempre visíveis, o que deixava o filtro pela metade e sem descrição em spec.

## What Changes

- Arquivos alterados passam a ser tratados como detalhe técnico, junto dos comandos executados: ambos só aparecem com o debug ligado
- O filtro passa a ser descrito em spec, incluindo a garantia de que alternar o interruptor não perde o histórico já recebido
- O requisito de streaming deixa de prometer a exibição dos eventos de detalhe, que agora dependem do filtro

## Capabilities

### New Capabilities
<!-- nenhuma -->

### Modified Capabilities
- `agent-harness`: novo requisito definindo o filtro de detalhe técnico do chat; o requisito de streaming passa a não prometer a exibição dos eventos que o filtro controla

## Impact

- `portal/appaiforge/ui/chat.py`: conjunto de tipos de evento tratados como detalhe, classes CSS do filtro e rótulo do interruptor
- Nenhuma mudança de dados, API ou dependência
