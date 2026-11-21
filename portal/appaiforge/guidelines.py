"""Guidelines de geração (ADR 0011): documento editável pelo admin, materializado
como AGENTS.md no workspace a cada execução seguinte."""

import os
import shutil

from sqlalchemy import select

from .config import get_settings
from .db import session_scope
from .models import Guideline, System
from .services import audit

_DEFAULT = """# Guidelines de geração do AIDB (PT-BR)

Você é o agente de código deste sistema. Siga estas regras em toda geração:

## Padrão de app
- UMA única app NiceGUI por sistema, em `app/` dentro do workspace, com entrada `app/main.py`.
- Backend e frontend em Python (NiceGUI). Sem frameworks de frontend JS.
- A app escuta em `0.0.0.0` na porta da env `PORT` (o supervisor injeta).
- **NÃO defina `root_path` no NiceGUI**: o proxy (Traefik) já provê o prefixo
  `/apps/<slug>` via header `X-Forwarded-Prefix` — definir root_path duplica o
  prefixo e quebra os assets (verificado no spike 6.1).
- Interface toda em português do Brasil (rótulos, mensagens, datas por extenso).

## Identidade do usuário (SSO do portal)
- O portal só deixa a requisição chegar à app depois de verificar a sessão e o acesso do
  usuário; então o edge injeta o header `X-AIDB-Identity` em TODA requisição: um JWT HS256
  assinado com `APP_IDENTITY_SECRET` (env), audiência `aidb-app:<slug>`, validade curta,
  com `sub`, `email`, `user_type` (admin/editor/app_user) e `groups`.
- Copie o helper canônico `appaiforge.app_template.identity` para a app e chame
  `install_identity(app)` logo no início; nas páginas, leia o usuário com
  `current_identity(request)`. Identidade ausente/inválida -> 401.
- NÃO crie sessão própria nem login na app: a identidade vale por requisição, e o logout
  ou a perda de acesso no portal precisam valer na requisição seguinte.
- Para testar com `curl`, gere um token local assinado com `APP_IDENTITY_SECRET` (HS256,
  `iss=aidb-portal`, `aud=aidb-app:<slug>`) e envie no header `X-AIDB-Identity`.

## Acesso a dados (OBRIGATÓRIO: camada dbgate)
- As conexões cadastradas chegam como envs `DATABASE_URL_<NOME>` (NOME em MAIÚSCULAS_COM_UNDERSCORE).
- TODO acesso ao banco passa pela camada `portal_templates/dbgate.py` (copie para a app):
  `db = DBGate(pool, connection_name="vendas")`; leitura com `db.fetch(...)`; escrita com
  `await db.execute(sql, *args)`.
- O dbgate classifica toda statement com o gate da plataforma (sqlglot):
  - DELETE/UPDATE escopado por chave (`id = $1`) executa direto;
  - DELETE/UPDATE em massa (sem WHERE restritivo) levanta `GateConfirmationRequired` com a
    contagem estimada de linhas — a UI DEVE mostrar o diálogo ("Isso afeta N linhas. Confirmar?")
    e só então chamar `await db.execute_confirmed(sql)`;
  - DDL (DROP/TRUNCATE/ALTER) levanta `GateBlocked` e nunca é enviada ao banco.
- Adicione a dependência no venv da app: `uv add sqlglot asyncpg`.
- Nunca use o pool/asyncpg diretamente para escrita, nunca grave credenciais em código.
- O banco é de produção: opere apenas o que foi pedido.

## Teste antes de concluir (OBRIGATÓRIO)
- Depois de gerar ou editar a app, SEMPRE valide antes de considerar o trabalho concluído:
  1. `python -m py_compile main.py` (e os demais módulos) para pegar erro de sintaxe cedo.
  2. Suba a app com tempo limitado, nunca em primeiro plano — `ui.run()` bloqueia e trava o
     agente se rodar sem limite: `timeout 15 .venv/bin/python main.py > /tmp/app_test.log 2>&1 &`.
  3. Depois de alguns segundos, bata num endpoint real com `curl` (com e sem o token de
     identidade, se a rota exigir) e **leia `/tmp/app_test.log`** — é o único lugar onde o
     erro aparece: o supervisor do container não guarda stdout/stderr da app.
- Se o log ou a resposta HTTP mostrar erro (traceback, 500, import faltando), corrija o
  código **proativamente**, sem esperar o editor relatar — e repita o teste até a resposta
  vir limpa antes de encerrar a execução.
- Nunca deixe o processo de teste rodando: o `timeout` acima já garante que ele termina
  sozinho; não suba a app sem limite de tempo em nenhuma hipótese.

## Mudanças planejadas com OpenSpec
- O workspace já vem com OpenSpec configurado: artefatos em `openspec/` (changes em
  `openspec/changes/`, specs em `openspec/specs/`) e os comandos do agente em `.opencode/`.
- Quando o editor pedir para planejar, propor, explorar, implementar ou arquivar uma mudança,
  use os comandos (no opencode o nome usa hífen, não dois-pontos):
  - `/opsx-explore` — pensar o problema junto com o editor antes de decidir;
  - `/opsx-propose <descrição>` — criar a change com proposta, specs, design e tarefas;
  - `/opsx-apply <change>` — implementar as tarefas da change, marcando cada uma ao concluir;
  - `/opsx-archive <change>` — arquivar a change concluída e sincronizar as specs.
- O projeto é `/workspace`: rode o CLI do OpenSpec sempre a partir dele
  (ex.: `cd /workspace && openspec list --json`), nunca do diretório em que o agente iniciou.
- Ajuste pontual sem pedido de planejamento pode ser feito direto, sem criar change.
- Nunca apague nem reescreva changes ou specs existentes em `openspec/` sem o editor pedir.

## Estilo
- CRUD administrativo: grade com busca + formulário modal + validação.
- Dashboards: NiceGUI + Plotly/ECharts embutidos.
- Código simples e direto; sem over-engineering; dependências sempre com `uv add <pacote>` dentro de `app/` (gera `app/pyproject.toml` e `app/uv.lock`, que vão junto no checkpoint); nunca `requirements.txt` nem `pip install`: a produção só instala o que está no `uv.lock`.

## Visualizações no chat (artifacts)
Quando o editor pedir gráficos, tabelas ou visualizações, use os blocos abaixo para que o resultado apareça renderizado diretamente no chat — sem precisar abrir a app:

**Gráfico (Apache ECharts):**
```echart
{"xAxis":{"type":"category","data":["Jan","Fev","Mar"]},"yAxis":{"type":"value"},"series":[{"type":"bar","data":[150,230,224]}]}
```

**Tabela:**
```table
[{"nome":"Alan","vendas":150},{"nome":"Maria","vendas":230}]
```

**HTML/SVG estático:**
```html
<svg width="200" height="100"><rect width="200" height="100" fill="#e0f2fe"/><text x="100" y="55" text-anchor="middle">OK</text></svg>
```

Regras:
- Use `echart` com JSON de configuração Apache ECharts válido (objeto com `series`, `xAxis`, `yAxis`, etc.).
- Use `table` com JSON array de objetos — as colunas são derivadas automaticamente das chaves.
- Use `html` apenas para SVG ou HTML estático simples, sem scripts externos.
- Use esses blocos **apenas quando o editor pedir explicitamente algo visual**. Para respostas textuais, markdown normal.
"""


def current_content() -> str:
    with session_scope() as s:
        row = s.execute(select(Guideline).order_by(Guideline.version.desc()).limit(1)).scalar_one_or_none()
        return row.content if row else _DEFAULT


def update_content(content: str, updated_by_id: str | None, updated_by_email: str | None = None) -> int:
    with session_scope() as s:
        latest = s.execute(select(Guideline.version).order_by(Guideline.version.desc()).limit(1)).scalar_one_or_none()
        row = Guideline(
            version=(latest or 0) + 1, content=content,
            updated_by_id=updated_by_id, updated_by_email=updated_by_email or "",
        )
        s.add(row)
        s.flush()
        version = row.version
    audit.record(
        actor_id=updated_by_id, actor_email=updated_by_email, action="guidelines.update",
        resource_type="guidelines", resource_id=str(version), details={"version": version},
    )
    return version


TEMPLATE_FILES = ["identity.py", "sqlgate.py", "dbgate.py"]
TEMPLATES_PACKAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_template")


def materialize(system: System) -> str:
    """Escreve AGENTS.md e os módulos canônicos (portal_templates/) no workspace.

    As cópias são byte a byte com os originais em appaiforge/app_template/ — um teste
    garante que não divergem. Devolve o caminho do AGENTS.md.

    Sob o driver Kubernetes, `workspaces_dir` não é o workspace real do sistema (a PVC só é
    visível de dentro do Pod) — escreve via exec no container do agente em vez de no filesystem
    local do portal (change `fix-k8s-workspace-materialize-delete`, achado real durante
    `deploy-portal-in-cluster`: sem este tratamento, os arquivos nunca chegavam ao agente).
    """
    if get_settings().provisioning_driver == "kubernetes":
        from .drivers.kubernetes_driver import write_workspace_files

        content = current_content().encode("utf-8")
        files = {"AGENTS.md": content}
        for name in TEMPLATE_FILES:
            with open(os.path.join(TEMPLATES_PACKAGE_DIR, name), "rb") as f:
                files[os.path.join("portal_templates", name)] = f.read()
        write_workspace_files(system, files)
        return "/workspace/AGENTS.md"

    system_dir = os.path.join(get_settings().workspaces_dir, system.slug)
    os.makedirs(system_dir, exist_ok=True)
    path = os.path.join(system_dir, "AGENTS.md")
    with open(path, "w") as f:
        f.write(current_content())

    templates_dir = os.path.join(system_dir, "portal_templates")
    os.makedirs(templates_dir, exist_ok=True)
    for name in TEMPLATE_FILES:
        shutil.copyfile(os.path.join(TEMPLATES_PACKAGE_DIR, name), os.path.join(templates_dir, name))
    return path
