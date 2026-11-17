"""Guidelines padrão ensinam o fluxo OpenSpec ao agente (change add-openspec-to-system-container,
task 3.1; spec agent-harness — "Guidelines incluem instruções de uso do OpenSpec")."""

from appaiforge import guidelines


def test_guidelines_padrao_citam_os_quatro_comandos_do_opencode():
    content = guidelines._DEFAULT
    for cmd in ("/opsx-propose", "/opsx-explore", "/opsx-apply", "/opsx-archive"):
        assert cmd in content
    assert "openspec/changes/" in content
    assert "/opsx:" not in content  # nome do opencode usa hífen


def test_conteudo_atual_sem_edicao_do_admin_inclui_openspec(clean_db):
    assert "/opsx-propose" in guidelines.current_content()
