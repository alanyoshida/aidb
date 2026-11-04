# Design

## Abordagem

Toda a mudança se concentra em dois arquivos: `chat.py` (parser + renderização) e `guidelines.py` (instrução ao agente). Nenhuma mudança de banco, harness, fila ou rotas.

### Parsing de artifacts em `render_event()`

Quando `event.kind == "message"`, o texto da resposta passa por `parse_artifacts(text)` antes de ser renderizado. A função divide o texto em segmentos usando `re.split` com um padrão que captura blocos fenced:

```
```(echart|table|html)\n(.*?)```
```

Cada segmento é um de:
- `("text", conteúdo)` — renderizado como `ui.markdown`
- `("echart", json_str)` — tenta `json.loads`; renderiza `ui.echart(config)` ou cartão de erro
- `("table", json_str)` — tenta `json.loads`; valida que é lista; renderiza `ui.aggrid` ou cartão de erro
- `("html", html_str)` — renderiza `ui.html` em iframe sandboxed

`parse_artifacts` retorna `list[tuple[str, str]]`. A lógica de renderização fica em `render_artifact_segment()` dentro de `render_event()`.

### Cartão de erro para artifact inválido

```python
with ui.card().classes("w-full border-red-300 bg-red-50"):
    ui.label(f"Artifact inválido ({kind}): {err}").classes("text-xs text-red-700")
    with ui.expansion("Ver conteúdo bruto"):
        ui.code(raw_content, language="text")
```

### Iframe sandboxed para HTML

```python
encoded = base64.b64encode(html_str.encode()).decode()
ui.html(f'<iframe src="data:text/html;base64,{encoded}" '
        f'sandbox="allow-same-origin" '
        f'style="width:100%;min-height:200px;border:none;"></iframe>')
```

`sandbox` sem `allow-scripts` bloqueia JS; sem `allow-top-navigation` bloqueia navegação; sem `allow-forms` bloqueia envio de formulários.

### AG Grid para tabelas

```python
columns = [{"field": k, "filter": True, "sortable": True} for k in rows[0].keys()]
ui.aggrid({"columnDefs": columns, "rowData": rows}).classes("w-full h-48")
```

Colunas derivadas automaticamente das chaves do primeiro objeto.

### ECharts

```python
ui.echart(config).classes("w-full h-64")
```

`config` é o JSON parseado diretamente — Apache ECharts aceita o mesmo schema que o LLM naturalmente produz.

### Instrução ao agente em `guidelines.py`

Nova seção no `_DEFAULT` do `guidelines.py`:

```
## Visualizações no chat (artifacts)
Quando o editor pedir gráficos, tabelas ou visualizações, use os blocos abaixo para
que o resultado apareça renderizado diretamente no chat:

- Gráfico: bloco ```echart``` com JSON de configuração Apache ECharts
- Tabela:  bloco ```table``` com JSON array de objetos
- HTML/SVG: bloco ```html``` com HTML estático (sem JS externo)

Exemplo de gráfico de barras:
```echart
{"xAxis":{"type":"category","data":["Jan","Fev","Mar"]},"yAxis":{"type":"value"},"series":[{"type":"bar","data":[150,230,224]}]}
```

Use apenas quando o editor pedir explicitamente algo visual. Para respostas textuais, markdown normal.
```

### Onde o parser não afeta eventos de streaming

O evento `message` chega completo (texto final), não em streaming de tokens — o OpenCode emite `message.part.updated` com `ptype == "text"` e o harness agrega em `RunEvent("message", text=text)`. O parser atua sobre esse texto completo, não precisa lidar com chunks parciais.

## Arquivos alterados

| Arquivo | Mudança |
|---|---|
| `portal/appaiforge/ui/chat.py` | `parse_artifacts()`, `render_artifact_segment()`, update em `render_event()` |
| `portal/appaiforge/guidelines.py` | Seção de artifacts no `_DEFAULT` |

## Não incluído

- Nenhum tipo de artifact além de `echart`, `table`, `html`
- Sem cache ou persistência de artifacts renderizados
- Sem download de artifact como arquivo
- Sem edição inline de artifact
