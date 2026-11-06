"""Unitários do token opaco de inferência por sistema (etapa 3, ADR 0020)."""

from appaiforge import inference_token


def test_emit_formato_system_id_assinatura():
    token = inference_token.emit("sys123", 0, secret="segredo")
    system_id, signature = token.split(".", 1)
    assert system_id == "sys123"
    assert len(signature) == 64


def test_emit_mesmo_sistema_versao_e_estavel():
    a = inference_token.emit("sys123", 2, secret="segredo")
    b = inference_token.emit("sys123", 2, secret="segredo")
    assert a == b


def test_emit_versao_diferente_muda_assinatura():
    a = inference_token.emit("sys123", 0, secret="segredo")
    b = inference_token.emit("sys123", 1, secret="segredo")
    assert a != b


def test_validate_token_valido_retorna_system_id():
    token = inference_token.emit("sys123", 0, secret="segredo")
    assert inference_token.validate(token, 0, secret="segredo") == "sys123"


def test_validate_token_adulterado_retorna_none():
    token = inference_token.emit("sys123", 0, secret="segredo")
    system_id, signature = token.split(".", 1)
    tampered = f"{system_id}.{'0' * 64}"
    assert inference_token.validate(tampered, 0, secret="segredo") is None


def test_validate_segredo_errado_retorna_none():
    token = inference_token.emit("sys123", 0, secret="segredo")
    assert inference_token.validate(token, 0, secret="outro") is None


def test_validate_versao_antiga_retorna_none():
    old = inference_token.emit("sys123", 0, secret="segredo")
    new = inference_token.emit("sys123", 1, secret="segredo")
    assert inference_token.validate(old, 1, secret="segredo") is None
    assert inference_token.validate(new, 1, secret="segredo") == "sys123"


def test_validate_formato_invalido_retorna_none():
    assert inference_token.validate("", 0, secret="s") is None
    assert inference_token.validate("sem-ponto", 0, secret="s") is None
    assert inference_token.validate(".assinatura", 0, secret="s") is None
    assert inference_token.validate("sys.", 0, secret="s") is None
