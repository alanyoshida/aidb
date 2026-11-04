# Tasks

> O código destes itens já existe na árvore de trabalho; o apply deve verificar
> cada um contra o comportamento descrito no spec antes de marcá-lo.

## 1. Filtro de detalhe técnico

- [ ] 1.1 Tratar comandos executados e arquivos alterados como um conjunto de tipos de evento de detalhe em `portal/appaiforge/ui/chat.py`, em vez de comparar com um tipo único. Verificar: inspecionar o DOM do chat e confirmar que os dois tipos recebem a mesma classe de detalhe.

- [ ] 1.2 Ajustar o rótulo do interruptor para refletir que ele controla comandos e arquivos alterados. Verificar: ler o rótulo renderizado na interface.

## 2. Verificação de comportamento

- [ ] 2.1 Confirmar que, com o debug desligado, nenhum comando e nenhum arquivo alterado fica visível, e que as mensagens do agente e os marcadores de transição permanecem. Verificar: medir a altura renderizada dos elementos de cada tipo numa sessão com histórico.

- [ ] 2.2 Confirmar que ligar o debug exibe os dois tipos sem recarregar a página nem refazer a execução. Verificar: contar os elementos de detalhe presentes no DOM antes de ligar e os visíveis depois, sem navegação entre as medições.

- [ ] 2.3 Rodar a suíte de testes do portal. Verificar: `pytest tests/unit/` passa inteira e o teste e2e de debug continua válido, já que depende do identificador do interruptor e do texto dos comandos.
