"""Regra de dono de um container existente (change add-production-portal-install, task 2.2)."""

from appaiforge.installation import INSTALLATION_LABEL, owner_description

ME, OTHER, SYS = "a" * 32, "b" * 32, "sys1"


def _labels(**extra):
    return {"appaiforge.managed": "true", "appaiforge.system_id": SYS, **extra}


def test_rotulo_desta_instalacao_e_mesmo_sistema_e_deste_portal():
    assert owner_description(_labels(**{INSTALLATION_LABEL: ME}), SYS, ME) is None


def test_rotulo_de_outra_instalacao_e_alheio():
    owner = owner_description(_labels(**{INSTALLATION_LABEL: OTHER}), SYS, ME)
    assert owner and "outra instalação" in owner


def test_sem_rotulo_e_mesmo_sistema_e_deste_portal():
    assert owner_description(_labels(), SYS, ME) is None


def test_sem_rotulo_e_outro_sistema_e_alheio():
    assert owner_description(_labels(), "outro", ME) == "outro sistema"


def test_mesma_instalacao_mas_outro_sistema_e_alheio():
    assert owner_description(_labels(**{INSTALLATION_LABEL: ME}), "outro", ME) == "outro sistema"


def test_container_nao_gerenciado_e_alheio():
    owner = owner_description({"appaiforge.system_id": SYS}, SYS, ME)
    assert owner == "um container que o portal não criou"
    assert owner_description(None, SYS, ME) == "um container que o portal não criou"
