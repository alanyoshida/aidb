# Design

## Context

- `portal/appaiforge/__init__.py` fixa `__version__ = "0.1.0"`, e o `pyproject.toml` repete o valor. O `__version__` alimenta:
  - o título do OpenAPI e o `/health` (`main.py`);
  - o `service.version` padrão da telemetria (`telemetry.build_resource`).
- `config.py` fixa `appaiforge/base:0.1.0` e `appaiforge/claude-code:0.1.0`.
- **Chart:**
  - `Chart.yaml` tem `version` e `appVersion` em `0.1.0`;
  - `values.yaml` e `values-production.yaml` fixam `image.tag: "0.1.0"`;
  - o `service.version` do portal no Kubernetes vem de `image.tag`.
- **Imagem do portal:** instala o pacote com `pip install ./portal`, sem modo editável. Os metadados do pacote existem no container e no ambiente do `uv` dos testes.
- **Reconciliação:** no Kubernetes, ela compara a imagem dos Pods de sistema com a esperada e recria os que diferem. No Docker, ela só recria um container ausente, e não compara imagens.
- **Releases:** são uma tag e notas no GitHub, criadas com `gh release create`. Não há CI de release.

## Goals / Non-Goals

**Goals:**
- uma fonte da versão no código e um teste que pega qualquer cópia desalinhada;
- o padrão das imagens de sistema segue a versão sem uma segunda edição.

**Non-Goals:**
- derivar a versão da tag do git em tempo de build (`setuptools-scm` e afins);
- mudar o `image.tag` do chart para cair no `appVersion` quando vazio.

## Decisions

### D1. Fonte única: o `version` do `pyproject.toml`

`__version__ = importlib.metadata.version("appaiforge-portal")`. Se os metadados não existirem (código importado sem instalar o pacote), o valor é `"0+desconhecida"`, para nunca mentir uma versão.

Alternativa descartada: manter a constante e um teste de igualdade com o `pyproject`. Seriam duas edições por release em vez de uma.

### D2. Imagens padrão derivadas da versão

`base_image` e `claude_code_image` passam a ter padrão `appaiforge/base:{__version__}` e `appaiforge/claude-code:{__version__}`. A configuração por ambiente continua prevalecendo.

### D3. Chart com valores explícitos, conferidos por teste

`Chart.yaml` (`version` e `appVersion`) e o `image.tag` dos dois arquivos de valores recebem a versão literal. O Helm não lê o `pyproject`, e um padrão vazio que caísse no `appVersion` exigiria mudar o template do `service.version` e o da imagem. O teste de alinhamento (D5) torna essa cópia segura.

### D4. Versão 1.11.0

A v1.10.0 já existe com `0.1.0` no código. Esta change leva a versão da release que vai publicá-la. Ela é minor, porque muda o padrão das imagens dos sistemas, o que pede ação do operador. Daqui em diante, o primeiro passo de cada release é subir a versão.

### D5. Teste de alinhamento

Um teste unitário lê a versão do `pyproject.toml` e confere que é igual a:
- `__version__`;
- o pacote `appaiforge-portal` no `uv.lock`;
- `version` e `appVersion` do `Chart.yaml`;
- `image.tag` de `values.yaml` e de `values-production.yaml`;
- toda referência `appaiforge/(portal|base|claude-code):<semver>` na documentação e nos comentários dos valores do chart.

Tags que não são semver ficam de fora: `pilot`, `latest`, e as do registro de exemplo do piloto, que levam o host na frente.

### D6. Procedimento de release em `docs/operacao.md`

Uma seção curta com os passos de uma release:
1. subir o `version` do `pyproject`, rodar `uv lock`, e atualizar o chart e os docs, guiado pelo teste;
2. abrir a PR e fazer o merge;
3. `gh release create v<versão>` no merge commit, com as notas.

Também diz como reconstruir as imagens dos sistemas com a tag nova.

## Risks / Trade-offs

- **[Imagem nova ausente no host Docker]:** um container recriado falha com imagem inexistente, e o sistema fica em erro com o motivo. → Notas de release e `docs/operacao.md` mandam construir as imagens antes de subir o portal. A falha é visível e não destrutiva: basta construir a imagem, e a reconciliação recria o container.
- **[Kubernetes recria os Pods de todos os sistemas no upgrade]:** é o comportamento já documentado ao trocar imagens. → As notas de release avisam, e pedem que as imagens estejam no registro antes.
- **[Esquecer de subir a versão numa release]:** o teste não pega isso, porque tudo continua igual entre si. → O procedimento põe a versão como primeiro passo, e as notas de release citam a versão.

## Migration Plan

1. **Docker:** construa `appaiforge/base:1.11.0` e `appaiforge/claude-code:1.11.0` no host, depois suba o portal novo. Os containers existentes seguem na imagem antiga até serem recriados.
2. **Kubernetes:** publique as duas imagens no registro (ou defina `portal.baseImage` e `portal.claudeCodeImage`), depois rode o `helm upgrade`.
3. **Rollback:** volte a versão do portal. As imagens `0.1.0` continuam válidas, e os containers recriados voltam a usá-las.
