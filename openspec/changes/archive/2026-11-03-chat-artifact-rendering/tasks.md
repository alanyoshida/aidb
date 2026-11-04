# Tasks

## 1. Parser de artifacts

- [x] 1.1 Em `portal/appaiforge/ui/chat.py`, criar função `parse_artifacts(text: str) -> list[tuple[str, str]]` que divide o texto em segmentos usando regex para detectar blocos fenced `echart`, `table` e `html`, retornando lista de `("text"|"echart"|"table"|"html", conteúdo)`.

- [x] 1.2 Criar função `render_artifact_segment(box, kind: str, raw: str) -> None` que renderiza cada segmento: texto como `ui.markdown`, echart com `ui.echart(json.loads(raw))`, table com `ui.aggrid`, html em iframe sandboxed via `ui.html`. Em caso de falha no parse do JSON (echart/table), renderiza cartão de erro com conteúdo bruto colapsado.

## 2. Renderização de cada tipo

- [x] 2.1 **echart**: em `render_artifact_segment()`, para kind `echart`, chamar `json.loads(raw)`, criar `ui.echart(config).classes("w-full h-64")`. Se `json.loads` lançar `json.JSONDecodeError` ou `config` não for dict, exibir cartão de erro.

- [x] 2.2 **table**: para kind `table`, chamar `json.loads(raw)`, validar que é `list` não-vazia, derivar `columnDefs` das chaves do primeiro elemento com `filter: True, sortable: True`, criar `ui.aggrid({"columnDefs": ..., "rowData": rows}).classes("w-full h-48")`. Lista vazia renderiza tabela sem linhas. JSON inválido ou não-lista: cartão de erro.

- [x] 2.3 **html**: para kind `html`, se conteúdo não-vazio, codificar em base64 e renderizar `ui.html(f'<iframe src="data:text/html;base64,{encoded}" sandbox="allow-same-origin" style="width:100%;min-height:200px;border:none;"></iframe>')`. Conteúdo vazio: não renderizar nada.

## 3. Integrar parser em `render_event()`

- [x] 3.1 Em `render_event()` dentro do bloco `if event.kind == "message":`, substituir a renderização direta de `ui.markdown(event.text)` por um loop sobre `parse_artifacts(event.text)` que chama `render_artifact_segment(box, kind, raw)` para cada segmento.

## 4. Guidelines — instrução ao agente

- [x] 4.1 Em `portal/appaiforge/guidelines.py`, adicionar nova seção `## Visualizações no chat (artifacts)` ao final do `_DEFAULT`, com instruções de uso dos blocos ```echart```, ```table``` e ```html```, exemplo de configuração ECharts mínima, e orientação para usar apenas quando o editor pedir algo visual.

## 5. Testes

- [x] 5.1 Adicionar teste unitário em `portal/tests/unit/` verificando que `parse_artifacts` divide corretamente texto misto (texto + bloco echart + texto) em 3 segmentos com os tipos corretos.

- [x] 5.2 Adicionar teste verificando que `parse_artifacts` retorna segmento de texto único quando não há blocos fenced especiais.

- [x] 5.3 Adicionar teste verificando que `render_artifact_segment` com kind `echart` e JSON inválido não lança exceção (exibe cartão de erro em vez de quebrar o chat).
