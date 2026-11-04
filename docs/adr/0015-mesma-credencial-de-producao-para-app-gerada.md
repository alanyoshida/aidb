# 0015 — App gerada usa a mesma credencial de produção; gate de destrutivas adiado

* Status: aceito; a parte "sem gate" foi substituída pelo [0017](0017-gate-de-operacoes-destrutivas-com-classificador-sql.md)
* Data: 2026-11-01
* Decidida em: exploração `appai-forge-mvp` (decisões interativas; riscos registrados no design)

## Contexto

As conexões cadastradas apontam para bancos de produção com escrita. O usuário escolheu não adotar credencial separada restrita e aceitou adiar o gate de confirmação de operações destrutivas para change futura.

## Decisão (aceita com risco consciente)

A app gerada usa **a mesma credencial** da conexão cadastrada — o agente lê via MCP, a app lê e escreve via driver direto (ADR 0008). Sem gate de operações destrutivas (DELETE/DROP/TRUNCATE/UPDATE em massa) na v1.

## Alternativas consideradas

- **Usuário de banco restrito por schema/tabela para a app** — recomendado e registrado; será a change seguinte ao gate. Não bloqueia o MVP.
- **Apps read-only sobre produção + escrita em staging** — descartada pelo usuário: as apps precisam gerenciar os dados de produção.

## Consequências

Um bug na app gerada pode afetar produção — o gate não existe para contê-la. Mitigação operacional enquanto o gate não chega: primeiro sistema da plataforma aponta para banco de homologação; checkpoints (ADR 0009) protegem o código, não os dados.
