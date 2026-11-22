# Tasks

## 1. Conferência da divisão

- [x] 1.1 Conferir que nenhum comportamento se perdeu nem mudou. Para cada um dos quatro requisitos originais, verificar com um script que compara as specs atuais com o delta:
  - cada frase com SHALL ou SHALL NOT aparece, com o mesmo texto, em exatamente um requisito do delta;
  - os cenários do requisito modificado são os mesmos do original, com o mesmo texto.

  A saída não pode ter nenhuma frase ou cenário faltando. Ler os cenários novos e confirmar que cada um só exercita uma frase normativa que já existia.
- [x] 1.2 Verificar com `openspec validate split-long-requirements --strict`, sem erro nem aviso. Nenhum requisito do delta pode passar de 500 caracteres.

## Workflow follow-up

- Arquivar a change (sincronizando as três specs) na mesma branch, antes de abrir a PR. Depois do arquivamento, `openspec validate --all --strict` deve ficar com 29 de 29.
- A PR sai junto com a da change `version-alignment`, na mesma branch.
