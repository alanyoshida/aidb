"""Unitários do registro de perfis de runtime de agente (tasks 1.1/1.2)."""

import pytest

from appaiforge.agent_profiles import FROM_PROVIDER, UnknownProfile, get_profile, resolve_credential_env
from appaiforge.services import catalog


def test_perfil_padrao_resolvido_pelo_nome():
    profile = get_profile("opencode")
    assert profile["agent"] == "opencode"
    assert profile["command"][0] == "opencode"
    assert profile["cwd"] == "/opencode-config"
    assert profile["harness_port"] == 4096
    assert "/workspace" in profile["writable_paths"]
    assert "/opencode-config" in profile["readable_paths"]


def test_perfil_declara_imagem_mount_path_e_protocolo_de_harness():
    """change generalize-agent-runtime-plumbing: estes três campos substituem
    settings.base_image, o literal "/opencode-config" e settings.opencode_port
    (removido) que o provisionamento usava fixo antes desta mudança."""
    profile = get_profile("opencode")
    assert profile["image"] == "appaiforge/base:0.1.0"
    assert profile["config_mount_path"] == "/opencode-config"
    assert profile["harness_protocol"] == "opencode-http"


def test_perfil_opencode_e_bit_a_bit_igual_aos_literais_que_substituiu():
    """Regressão dedicada (design.md - "zero mudança de comportamento para
    sistemas existentes"): a imagem do perfil padrão tem que continuar igual
    a settings.base_image - só os sidecars (dbgate/httpsproxy) ainda leem
    esse setting direto; o container do agente passa a usar o perfil."""
    from appaiforge.config import get_settings

    profile = get_profile("opencode")
    assert profile["image"] == get_settings().base_image
    assert profile["config_mount_path"] == "/opencode-config"
    assert profile["harness_port"] == 4096


def test_connect_tcp_ports_estaticas_so_tem_dns():
    """443/80 saíram da lista estática (change agent-https-forward-proxy):
    toda saída HTTP(S) do agente passa a depender do proxy de saída, cuja
    porta é calculada por sistema em provisioning.write_agent_profile, não
    aqui. 53 continua: é o fallback raro de DNS por TCP. As portas do proxy
    de gate de banco e do broker também são dinâmicas, calculadas lá."""
    profile = get_profile("opencode")
    assert profile["connect_tcp_ports"] == [53]


def test_readable_paths_inclui_proc_achado_da_verificacao_real_da_etapa_2():
    """Sem /proc legível, o runtime Bun do opencode aborta sob Landlock
    (achado da task 7 — ver docs/roadmap-confinamento-do-agente.md, etapa 2)."""
    profile = get_profile("opencode")
    assert "/proc" in profile["readable_paths"]


def test_readable_paths_inclui_resolucao_de_rede_sem_liberar_etc_inteiro():
    """Revisão do achado original da etapa 2 (liberava /etc inteiro): um
    `strace -f` real (`opencode serve` + sessão + prompt) mostrou exatamente
    o que é lido sob /etc — resolução de nome (NSS/glibc), fuso horário,
    cache do linker e cadeia de certificados TLS — sem nenhuma leitura de
    /etc/passwd ou /etc/group. A lista é explícita em vez de liberar o
    diretório inteiro (ver teste abaixo)."""
    profile = get_profile("opencode")
    for caminho in ("/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf", "/etc/ssl/certs"):
        assert caminho in profile["readable_paths"]


def test_readable_paths_nao_libera_etc_inteiro_nem_passwd_ou_group():
    """Pedido do operador: bloquear leitura de arquivos sensíveis como
    /etc/passwd sob Landlock, sem depender do agente nunca pedir (gate de
    permissão do opencode é por fora do Landlock e é best-effort)."""
    profile = get_profile("opencode")
    assert "/etc" not in profile["readable_paths"]
    assert "/etc/passwd" not in profile["readable_paths"]
    assert "/etc/group" not in profile["readable_paths"]


def test_readable_paths_inclui_dev_achado_da_verificacao_real_da_etapa_2():
    """Sem /dev legível, `uv sync` falhava ao detectar a glibc do sistema
    (provavelmente precisa de /dev/null para um subprocesso de sondagem) e
    nenhuma dependência da app gerada era instalada."""
    profile = get_profile("opencode")
    assert "/dev" in profile["readable_paths"]


def test_writable_paths_inclui_mapa_real_de_escrita_da_etapa_1():
    """Task 3.1 da etapa 2: sem esses caminhos, o Landlock negaria escrita que
    o agente legitimamente precisa (mapa observado numa geração real)."""
    profile = get_profile("opencode")
    for caminho in (
        "/workspace",
        "/home/agent/.cache/opencode",
        "/home/agent/.cache/uv",
        "/home/agent/.npm",
        "/home/agent/.config",
        "/home/agent/.local",
        "/tmp",
    ):
        assert caminho in profile["writable_paths"]


def test_sem_nome_devolve_perfil_padrao_da_plataforma():
    assert get_profile() == get_profile("opencode")


def test_nome_desconhecido_falha_explicitamente():
    with pytest.raises(UnknownProfile):
        get_profile("agente-inexistente")


def test_perfil_declara_credential_env_delegado_ao_provedor():
    profile = get_profile("opencode")
    assert profile["credential_env"] == FROM_PROVIDER


@pytest.fixture()
def presets(clean_db):
    catalog.ensure_presets()


def test_resolve_credential_env_glm_para_zhipu(presets):
    profile = get_profile("opencode")
    assert resolve_credential_env(profile, "glm") == "ZHIPU_API_KEY"


def test_resolve_credential_env_anthropic(presets):
    profile = get_profile("opencode")
    assert resolve_credential_env(profile, "anthropic") == "ANTHROPIC_API_KEY"


def test_resolve_credential_env_provedor_desconhecido_cai_no_padrao(presets):
    profile = get_profile("opencode")
    assert resolve_credential_env(profile, "foo") == "FOO_API_KEY"


def test_resolve_credential_env_literal_nao_delega(presets):
    """Perfil com credential_env literal (ex.: futuro agente claude-code) não consulta o catálogo."""
    profile = {"credential_env": "ANTHROPIC_API_KEY"}
    assert resolve_credential_env(profile, "qualquer-coisa") == "ANTHROPIC_API_KEY"


def test_create_system_persiste_perfil_padrao_quando_omitido(clean_db):
    """change generalize-agent-runtime-plumbing, spec agent-runtime -
    "Perfil de runtime por sistema": determinado no provisionamento (aqui,
    na criação), nunca mais re-resolvido depois."""
    from appaiforge import auth
    from appaiforge.models import UserType
    from appaiforge.services.systems import create_system

    editor = auth.create_user("profile1@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Sistema", "sistema-perfil-padrao")
    assert system.agent_profile == "opencode"


def test_create_system_persiste_perfil_informado_explicitamente(clean_db):
    from appaiforge import auth
    from appaiforge.models import UserType
    from appaiforge.services.systems import create_system

    editor = auth.create_user("profile2@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Sistema", "sistema-perfil-explicito", agent_profile="opencode")
    assert system.agent_profile == "opencode"


def test_create_system_recusa_perfil_desconhecido(clean_db):
    """Falha explícita na criação - nunca persiste um perfil que `get_profile`
    não conseguiria resolver depois, no provisionamento."""
    from appaiforge import auth
    from appaiforge.models import UserType
    from appaiforge.services.systems import create_system

    editor = auth.create_user("profile3@t.local", "pw", UserType.editor.value)
    with pytest.raises(UnknownProfile):
        create_system(editor, "Sistema", "sistema-perfil-invalido", agent_profile="agente-inexistente")


# --- change add-claude-code-agent-profile (etapa 7 do roadmap) ---


def test_perfil_claude_code_resolvido_pelo_nome():
    profile = get_profile("claude-code")
    assert profile["agent"] == "claude-code"
    assert profile["cwd"] == "/workspace"
    assert profile["harness_port"] == 8091
    assert "/workspace" in profile["writable_paths"]


def test_perfil_claude_code_declara_imagem_mount_path_e_protocolo_de_harness():
    profile = get_profile("claude-code")
    assert profile["image"] == "appaiforge/claude-code:0.1.0"
    assert profile["config_mount_path"] == "/claude-code-config"
    assert profile["config_path"] == "/claude-code-config/settings.json"
    assert profile["config_format"] == "claude-code-settings"
    assert profile["harness_protocol"] == "claude-code-headless"


def test_perfil_claude_code_credential_env_e_literal_api_key():
    """Achado real do spike (task 1.3): ANTHROPIC_API_KEY (x-api-key), não
    ANTHROPIC_AUTH_TOKEN - é o header que o broker já sabe trocar pro
    dialeto anthropic (mesmo do perfil opencode)."""
    profile = get_profile("claude-code")
    assert profile["credential_env"] == "ANTHROPIC_API_KEY"


def test_resolve_credential_env_claude_code_nao_delega_ao_catalogo(presets):
    profile = get_profile("claude-code")
    assert resolve_credential_env(profile, "qualquer-coisa") == "ANTHROPIC_API_KEY"


def test_perfil_claude_code_writable_paths_inclui_achados_reais_do_strace():
    """Task 1.4: além de ~/.claude/**, a CLI também usa ~/.claude.json
    (config global) e ~/.config/anthropic (achado novo, não previsto no
    design original)."""
    profile = get_profile("claude-code")
    for caminho in (
        "/home/agent/.claude",
        "/home/agent/.claude.json",
        "/home/agent/.config/anthropic",
    ):
        assert caminho in profile["writable_paths"]


def test_perfil_claude_code_connect_tcp_ports_so_tem_dns():
    profile = get_profile("claude-code")
    assert profile["connect_tcp_ports"] == [53]


def test_create_system_persiste_perfil_claude_code(clean_db):
    """Spec agent-runtime, "Conjunto de perfis extensível" - registrar um
    perfil novo habilita o agente correspondente sem mudança em
    create_system/UnknownProfile (já genérico desde a change anterior)."""
    from appaiforge import auth
    from appaiforge.models import UserType
    from appaiforge.services.systems import create_system

    editor = auth.create_user("profile4@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Sistema", "sistema-perfil-claude-code", agent_profile="claude-code")
    assert system.agent_profile == "claude-code"
