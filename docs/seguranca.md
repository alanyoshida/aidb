# Segurança

← [README](../README.md)

## Gate de operações destrutivas

Toda SQL que toca os bancos das conexões passa pelo **gate** (classificador canônico com sqlglot — [ADR 0017](adr/0017-gate-de-operacoes-destrutivas-com-classificador-sql.md), spec `destructive-gate`):

| Classe | Exemplo | Comportamento |
|---|---|---|
| **normal** | `DELETE FROM clientes WHERE id = $1` (escopo por chave) | executa sem atrito |
| **confirmável** | `DELETE FROM clientes` ou `WHERE cidade = 'X'` | **sempre recusada** em `enforce` ([ADR 0023](adr/0023-confirmavel-recusado-direto-sem-pedir-aprovacao.md)) |
| **bloqueada** | DDL (`DROP`/`TRUNCATE`/`ALTER`/...) | **sempre recusada** (exceto pelo agente em `schema_admin`, abaixo) |

Desde a etapa 4 do confinamento ([ADR 0021](adr/0021-gate-de-sql-no-data-plane-via-sidecar-proxy.md)), o gate roda no **data plane**: cada sistema com conexão Postgres/MySQL ganha um **sidecar** (`<slug>-dbgate`, mesmo network namespace do container do sistema) que fala o protocolo de fio do banco e classifica cada statement antes de repassá-la — não depende de reconhecer SQL dentro de texto de bash, e cobre tanto o agente quanto a app gerada. O container do sistema nunca vê a credencial real: `DATABASE_URL_<ALIAS>` e o comando do MCP recebem um DSN de loopback sem usuário/senha; só o sidecar guarda o segredo e abre a conexão de verdade.

- **Pelo agente/app**: dois listeners por conexão (um para o agente/MCP, outro para a app gerada via `DATABASE_URL_<ALIAS>`) atribuem a origem sem ambiguidade. Em `enforce`, `bloqueada` e `confirmável` têm o **mesmo tratamento**: nenhuma das duas chega ao banco, nenhuma pede decisão de ninguém — o proxy recusa na hora (erro de protocolo ao cliente). Achado ao vivo que motivou isso ([ADR 0023](adr/0023-confirmavel-recusado-direto-sem-pedir-aprovacao.md)): segurar `confirmável` e pedir aprovação por um card genérico deixava passar um `DELETE` sem `WHERE` disfarçado, se alguém aprovasse por hábito. Quando há uma run ativa do agente, a recusa aparece no chat com a statement e o motivo.
- **Dois modos, por flag** (`DB_GATE_MODE`): `enforce` (default) torna o proxy o gate de verdade — `bloqueada`/`confirmável` são recusadas na hora e os globs de SQL somem do `permission.bash` do agente (ficam só os não-SQL); `shadow` classifica e **audita sem bloquear nada**, útil pra observar um sistema específico antes de confiar nele (`appaiforge compare-gate-decisions`, ver [roadmap](roadmap-confinamento-do-agente.md)). Trocar entre os dois é mudança de configuração, não de código.
- **Na app gerada**: a camada `dbgate.py` (obrigatória nas guidelines) dispara um diálogo com a contagem estimada de linhas antes de executar operações confirmáveis; DDL é recusada — cinto-e-suspensório com o proxy, que já classifica a mesma statement antes dela chegar ao banco. Essa confirmação é da interface da app pros usuários dela, sem relação com o chat agente↔editor acima.
- **Auditoria**: toda decisão (aprovada/recusada/bloqueada/sombra/liberada) fica na seção "Gate de destrutivas" da página do sistema, com autor, SQL, origem e data.
- Apps geradas **antes** desta mudança migram para a camada na próxima edição pelo agente.

### Modos de acesso por sistema e `schema_admin`

As conexões ficam num catálogo gerido pelo DB Manager, que autoriza cada uma para um sistema
com um **teto** de modo de acesso; o dono do sistema ativa a conexão num modo igual ou abaixo
do teto ([ADR 0036](adr/0036-catalogo-de-conexoes-autorizacao-e-ativacao.md)). Os modos, em
ordem:

| Modo | MCP do agente | bash do agente (pelo proxy) | app gerada (pelo proxy) |
|---|---|---|---|
| `read_only` | só leitura | gate normal | gate normal |
| `read_write` | só leitura | gate normal | gate normal |
| `schema_admin` | só leitura | **DDL e DML em massa liberados** | gate normal (DDL recusada) |

- **`schema_admin` vale só para o agente.** O sidecar libera `bloqueada` e `confirmável` apenas
  no listener de origem `agente` de uma conexão nesse modo; o listener da app nunca recebe a
  liberação, e a camada `dbgate.py` da app continua recusando DDL. Serve para o agente criar e
  reestruturar tabelas no começo de um sistema.
- **Toda statement liberada é auditada** como decisão `liberada` no histórico do gate, com a
  classificação original (`bloqueada` ou `confirmável`). Não há aviso no chat: não é uma recusa.
- **O rebaixamento é manual.** Enquanto a conexão estiver em `schema_admin`, a página do sistema e
  a lista de autorizações do DB Manager mostram "DDL liberada desde <data>". O DB Manager pode
  rebaixar o teto a qualquer momento; o modo vigente cai junto e o sistema é reprovisionado.
- **Banco compartilhado.** Uma DDL feita por um sistema pode quebrar outro que usa o mesmo banco.
  Ao conceder `schema_admin` numa conexão autorizada para outros sistemas, o portal lista esses
  sistemas e pede confirmação.
- **Em modo `shadow` o `schema_admin` não muda nada**, porque em sombra nada é recusado.
- **BigQuery não tem `schema_admin`**: o MCP dele é só leitura e ele não passa pelo proxy.

**Limitação conhecida: `read_only` só vale no MCP.** O proxy não distingue `read_only` de
`read_write`: o bash do agente e a app gerada ainda conseguem escrever (DML escopado) numa
conexão ativa em `read_only`. Para isolamento real de leitura, cadastre no catálogo uma conexão
com um usuário de banco que só tenha permissão de leitura.

## Confinamento do agente

Cada sistema roda num container próprio sob um de três **modos de execução**, fixado na criação
e nunca trocado automaticamente ([ADR 0018](adr/0018-perfil-de-runtime-do-agente-e-identidade-reduzida.md),
[ADR 0019](adr/0019-sandbox-seccomp-landlock-no-supervisor.md), roadmap
[`roadmap-confinamento-do-agente.md`](roadmap-confinamento-do-agente.md)):

| Modo | Usuário | Capabilities | Landlock + seccomp |
|---|---|---|---|
| `legacy` | root | todas | não |
| `reduced` | `agent` (uid 1000) | nenhuma (`cap_drop: ALL`) | não |
| `sandboxed` | `agent` (uid 1000) | nenhuma | **sim** |

Sistema novo recebe `sandboxed` automaticamente se o host suporta Landlock; sem suporte, cai para
`reduced` com aviso (ou recusa a criação com `APPAIFORGE_REQUIRE_SANDBOX=true`, modo fail-closed
de produção). Sistemas criados antes do ADR 0018 ficam em `legacy` — ver "Migrar um sistema para
`sandboxed`" abaixo.

**Como o confinamento funciona** (modo `sandboxed`): o supervisor (`afsupervisor`, PID 1 do
container) aplica dois mecanismos auto-impostos e não-privilegiados no processo **filho** que vai
virar o agente (`opencode serve`), nunca em si mesmo — ambos são herdados por todo processo que o
agente gerar (bash, python, o script que ele escrever) e **irrevogáveis** depois de aplicados:

- **seccomp** nega um denylist de syscalls perigosas (`ptrace`, `bpf`, `mount`, `setns`,
  `perf_event_open`, `process_vm_readv`/`writev`, `pivot_root`, `io_uring_setup`, `unshare` com
  `CLONE_NEWUSER`) — tudo o mais é permitido.
- **Landlock de filesystem** nega acesso fora do declarado no perfil do agente
  (`appaiforge/agent_profiles.py`): leitura+execução só em `/workspace`, `/opencode-config`,
  `/usr`, `/lib`, `/opt`, `/proc`, `/dev` e um conjunto explícito de arquivos sob `/etc`
  (resolução de nome, fuso horário, cache do linker, cadeia de certificados — **não** o diretório
  inteiro); escrita só em `/workspace`, `/tmp` e os caches do `$HOME` do agente. Qualquer coisa
  fora dessas listas — `/etc/passwd`, `/etc/shadow`, `/root`, os workspaces de outros sistemas —
  fica negada pelo kernel, não por um pedido de permissão que o agente poderia simplesmente
  receber "sim" de um editor apressado.
- **Landlock de rede** ([ADR 0022](adr/0022-confinamento-de-rede-por-porta-tcp-via-landlock.md)),
  empilhado por cima do de filesystem: conexão TCP de saída só nas portas calculadas para o
  sistema — o `agent_port` de cada conexão cadastrada (proxy de gate de banco, etapa 4), a porta do
  broker de inferência quando habilitado, a porta do proxy HTTP(S) de saída (abaixo), e sempre 53
  (DNS por TCP). Fecha o bypass que as etapas 3/4 deixavam aberto: antes, um agente confinado por
  filesystem ainda alcançava o Postgres/MySQL real direto, por fora do proxy, bastando descobrir o
  endereço — a regra de porta do Landlock é agnóstica de endereço, então nega isso mesmo que o
  agente ache o host real.

**O que isso substitui**: a permissão `external_directory` do próprio opencode (pedia confirmação
no chat toda vez que o agente tocava um caminho fora do workspace, inclusive **falsos-positivos**
de caminho absoluto já dentro dele) hoje é liberada sem perguntar
(`permission.external_directory: "allow"`) — a barreira real passou a ser o Landlock, que o
sistema operacional aplica de verdade e não depende de ninguém clicar em "Aprovar".

**Proxy HTTP(S) de saída** ([ADR 0024](adr/0024-proxy-http-s-de-saida-obrigatorio-por-sistema.md)):
443 e 80 saíram da lista fixa do Landlock — a única saída HTTP(S) do agente passa por um sidecar
(`<slug>-httpsproxy`, mesmo network namespace do sistema), que só libera `CONNECT`/requisição HTTP
para um destino (`host:porta`) numa **allow-list calculada por sistema**: o host do provedor de LLM
configurado (quando o broker está desligado) ou o host:porta do broker (quando está ligado — nunca
os dois), mais os registros de pacote (`pypi.org`, `files.pythonhosted.org`, `registry.npmjs.org`).
`HTTP_PROXY`/`HTTPS_PROXY` são injetadas automaticamente no ambiente do container; o proxy nunca
decripta TLS, só faz o túnel.

- **Acesso à internet** (toggle na aba Configurações, por sistema): desligado, o proxy não libera
  nenhum destino externo — o broker de inferência (quando habilitado) não é afetado, porque nunca
  passou por este proxy.
- **Modo restrito** (toggle + aba Domínios, por sistema): ligado, a allow-list acima é **substituída
  por completo** pela lista de domínios cadastrada ali — nasce pré-populada com os registros de
  pacote, editável pelo editor do sistema (mesmo acesso da aba Conexões).

**Limites aceitos por ora**: exfiltração via LLM pelo próprio prompt é um limite irredutível (o
endpoint é legítimo, o agente pode mandar conteúdo do workspace por ele). Nenhuma das camadas de
Landlock cobre a app gerada, que roda sem confinamento desde sempre. Sistemas em `legacy`/`reduced`
não têm nenhuma (ou só a de filesystem) dessas garantias.

### Repositório git do sistema fora do workspace

O histórico de checkpoints de cada sistema vive **fora** do workspace (change
`isolate-workspace-repository`): o workspace é só a árvore de trabalho, e o repositório (objetos,
refs, config, hooks) fica onde o agente e a app gerada não alcançam:

| Driver | Onde fica o repositório | Quem monta |
|---|---|---|
| Docker | `APPAIFORGE_GITDIRS_DIR/<slug>` (volume `gitdirs`, padrão `/gitdirs`) | só o portal |
| Kubernetes | PVC `appaiforge-sys-<slug>-gitdir` | só o container auxiliar `git` do pod |

Toda operação git do portal (`appaiforge/git_backend.py`) roda com `GIT_DIR`/`GIT_WORK_TREE`
explícitos, ambiente construído do zero (`HOME` inexistente, `GIT_CONFIG_GLOBAL=/dev/null`,
`GIT_CONFIG_NOSYSTEM=1`) e com `core.hooksPath=/dev/null` e `core.fsmonitor=false` na linha de
comando. Por isso **nada que o agente escreva no workspace é executado pelo portal**: um hook,
um `core.fsmonitor`, um filtro declarado em `.gitattributes` ou um `.git` inteiro plantado não
são lidos — o git nunca rastreia um caminho `.git` da árvore de trabalho, e `.gitattributes` só
ativa um filtro que a config do repositório defina, o que a config escrita pelo portal nunca faz.

Antes dessa mudança, o portal rodava git dentro do `/workspace/.git` gravável pelo agente: hooks,
`core.fsmonitor` e filtros plantados ali executavam no processo do portal (driver Docker, como
root) ou por `exec` fora do Landlock (driver Kubernetes) — confirmado por
`tests/integration/test_workspace_repository_isolation.py` contra o código anterior.

O git roda com o uid do dono do workspace (o do agente em `reduced`/`sandboxed`, root em
`legacy`), então arquivos que o portal escreve numa restauração continuam editáveis pelo agente.
No driver Docker, antes de migrar o histórico e antes de cada restauração, o portal passa ao uid
do agente o que estiver com o root dentro do workspace (deixado por versões antigas ou pelo
`materialize` das guidelines), exceto o `.git` antigo. A varredura nunca segue link simbólico
(`os.fwalk` e `chown` relativo ao descritor do diretório), então um link plantado pelo agente não
leva a troca de dono para fora do workspace.

Sistemas anteriores à mudança têm o histórico migrado na primeira operação git: só os arquivos
de objeto do `.git` antigo são copiados, como dado, e a branch passa a apontar para o último
checkpoint **registrado pelo portal** — nunca para o que as refs do `.git` antigo dizem. O
`.git` antigo fica no workspace, intocado e sem uso pelo portal; o agente continua podendo lê-lo.

### Repositório remoto (GitLab)

Quando um sistema é vinculado a um repositório GitLab (aba **Repositório**, [ADR 0029](adr/0029-repositorio-remoto-por-retransmissao-no-portal.md)),
quem fala com o GitLab é o **portal**, nunca o container do sistema:

- A chave de implantação (ed25519, uma por sistema) e o token de API opcional ficam cifrados no
  banco do portal e nunca aparecem na interface, em respostas nem na auditoria. A chave só existe em
  arquivo durante a operação, num diretório temporário `0700` (em `tmpfs` quando há), apagado em
  seguida. Testes verificam que ela não aparece no sistema de arquivos, no ambiente nem nos
  processos dos containers do sistema.
- O envio sai de uma cópia bare de retransmissão do portal (`APPAIFORGE_GIT_RELAYS_DIR`), que troca
  pacotes git com o repositório do sistema. O `ssh` roda sem a config do portal (`-F /dev/null`),
  com `known_hosts` só com a chave do servidor que o editor confirmou; se o servidor apresentar outra
  chave, nada é enviado nem recebido. O git só aceita SSH como transporte.
- A rede do agente não muda: o agente confinado não alcança o servidor git.
- O portal nunca reescreve o histórico remoto (envio sem `--force`) e nunca envia `.gitlab-ci.yml`
  criado ou alterado no workspace — a definição do pipeline vem de um projeto separado.
- O GitLab registra push, merge request e pipeline em nome de quem cadastrou a chave e o token. A
  revisão humana é garantida pela branch de destino protegida, não pelo AIDB. Ver o
  [guia de preparação](gitlab.md).

### Migrar um sistema de `legacy` para `sandboxed`

Não existe CLI/UI para isso (modo é "fixado na criação e imutável" por desenho) — foi feito uma
vez, manualmente, para os sistemas que existiam antes do ADR 0018. Se precisar de novo: sistemas
`legacy` rodam como root, então o workspace inteiro é **dono de root** — trocar só o modo sem
corrigir isso prende o agente (agora uid 1000) fora dos próprios arquivos. A ordem importa:

```bash
# 1. dono do workspace para o uid do agente (ANTES de trocar o modo — enquanto
#    o container antigo ainda roda como root, o bind do host já está acessível
#    de fora dele via outro container efêmero com a mesma imagem)
docker run --rm --user root -v /opt/appaiforge/workspaces/<slug>:/workspace \
  appaiforge/base:1.11.0 chown -R 1000:1000 /workspace

# 2. dono do repositório git do sistema (fora do workspace) para o mesmo uid —
#    o portal passa a rodar o git como o agente depois da troca de modo
docker exec appaiforge-portal-1 chown -R 1000:1000 /gitdirs/<slug>

# 3. troca o modo no banco e recria o container (dentro do container do portal)
docker exec appaiforge-portal-1 python -c "
from appaiforge.db import session_scope
from appaiforge.models import System, ExecutionMode
from appaiforge.services.systems import get_system
from appaiforge.provisioning import provision_system

with session_scope() as s:
    row = s.query(System).filter(System.slug == '<slug>').one()
    row.execution_mode = ExecutionMode.sandboxed
    system_id = row.id

provision_system(get_system(system_id))
"
```

Recriar o container invalida qualquer sessão de chat aberta nesse sistema (reabre sozinha na
próxima mensagem). Confirme depois: `docker inspect appaiforge-sys-<slug> --format '{{.Config.User}}'`
deve mostrar `1000:1000`, e `docker exec appaiforge-sys-<slug> id` deve mostrar o usuário `agent`.

## Nenhum segredo nas imagens

Nenhuma imagem do projeto (portal, base e claude-code) chega ao registry com um segredo dentro. São três camadas: as duas primeiras evitam que o segredo entre, e a terceira bloqueia a imagem que o tenha mesmo assim.

1. **Contexto de build.** O `.dockerignore` da raiz e o de `base-image/` excluem `.env`, `*.env` (os `*.env.example` entram), chaves (`*.pem`, `*.key`, `*.p12`, `id_rsa*`, `id_ed25519*`), `.npmrc`, `.pypirc` e `.netrc`.
2. **Dockerfiles.** O teste `portal/tests/unit/test_container_hygiene.py` falha se um Dockerfile declarar `ARG` ou `ENV` com nome de segredo (`TOKEN`, `SECRET`, `PASSWORD`, `API_KEY` etc.), porque o valor ficaria no histórico da imagem. Ele também confere os padrões dos dois `.dockerignore`.
3. **Imagem construída.** O script `.github/scripts/scan-image-secrets.sh` roda dois detectores, e qualquer achado para a CI:
   - o detector de segredos do trivy, nas camadas e na configuração da imagem (`ENV`, labels, histórico de comandos);
   - o gitleaks, no sistema de arquivos exportado da imagem.

   Os valores saem mascarados. Na CI, ele roda em todo push e, na publicação, antes do `docker login` no GHCR, então uma imagem reprovada nunca tem como ser enviada. Para checar uma imagem local: `.github/scripts/scan-image-secrets.sh <imagem>`, a partir da raiz do repositório.

**Falso positivo.** Um achado da regra genérica num arquivo do sistema operacional ou do Node pode ser falso. Hoje, os casos conhecidos são cabeçalhos em `/usr/include/linux` e `/usr/local/include/node` e módulos do Perl. Esses caminhos ficam na allowlist de `.gitleaks-image.toml`. Um caminho novo entra lá numa PR revisada, nunca uma pasta do projeto. No histórico do repositório, `.gitleaks.toml` libera só os valores fictícios das fixtures de teste, cada um comentado.

Se um segredo real aparecer: revogue-o primeiro, depois tire-o do código. Um segredo que já foi commitado continua no histórico, e o gitleaks continua achando-o.


## Portal e Postgres no cluster

No chart, o portal e o Postgres rodam com contexto de segurança restrito: sem escalada de privilégio, perfil seccomp `RuntimeDefault` e raiz somente leitura.

- **Portal** (e o initContainer das migrações): sem nenhuma capability. Ele grava só em volumes `emptyDir`:
  - `/configs` e `/git-relays`, como antes;
  - `/tmp`;
  - `/dynamic`, a rota do portal para o Traefik do compose, que no cluster ninguém lê;
  - `/workspaces`, onde o harness fake grava a app de exemplo.

  Ele continua rodando com o usuário da imagem, root. No compose, o portal precisa de root para acertar o dono dos workspaces e rodar o git com o uid de cada sistema.
- **Postgres:** só as cinco capabilities de que o entrypoint da imagem oficial precisa para acertar o dono do diretório de dados e trocar para o usuário `postgres`: `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `SETGID` e `SETUID`. O socket e os temporários ficam em `emptyDir`, e os dados continuam na PVC.

Um upgrade de uma instalação anterior preserva o banco: o contexto muda, mas a PVC e o dono dos arquivos são os mesmos.
