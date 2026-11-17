## 1. Config do agente

- [x] 1.1 `write_opencode_config` grava `"instructions": ["/workspace/AGENTS.md"]` no `opencode.json`
- [x] 1.2 Teste unitário em `tests/unit/test_llm_provisioning.py` cobrindo o campo

## 2. Contrato com o opencode pinado

- [x] 2.1 Teste de integração: `opencode serve` da imagem base, cwd fora do workspace, provedor falso que captura a requisição; com a config gerada pelo portal, o texto do `AGENTS.md` aparece no corpo enviado ao modelo
- [x] 2.2 No mesmo teste: alteração do `AGENTS.md` vale para a mensagem seguinte; `AGENTS.md` ausente não impede a resposta

## 3. Validação

- [x] 3.1 Rodar unit + integração afetada
- [x] 3.2 Recriar o sistema de validação no stack real e confirmar a config no container
