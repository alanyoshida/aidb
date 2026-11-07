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
