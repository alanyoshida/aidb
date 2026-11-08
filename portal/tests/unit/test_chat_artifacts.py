"""Unitários: parse_artifacts e render_artifact_segment."""

import pytest

from appaiforge.ui.chat import parse_artifacts, render_artifact_segment


def test_parse_artifacts_texto_misto():
    """Texto antes + bloco echart + texto depois → 3 segmentos com tipos corretos."""
    text = "Aqui está o gráfico:\n```echart\n{\"type\":\"bar\"}\n```\nEspero que ajude."
    segments = parse_artifacts(text)
    assert len(segments) == 3
    assert segments[0] == ("text", "Aqui está o gráfico:\n")
    assert segments[1][0] == "echart"
    assert segments[1][1] == '{"type":"bar"}'
    assert segments[2] == ("text", "\nEspero que ajude.")


def test_parse_artifacts_sem_blocos():
    """Texto puro sem blocos fenced → segmento único de tipo text."""
    text = "Olá, posso ajudar com sua dúvida."
    segments = parse_artifacts(text)
    assert segments == [("text", text)]


def test_parse_artifacts_vazio():
    """String vazia → segmento único de tipo text vazio."""
    segments = parse_artifacts("")
    assert segments == [("text", "")]


def test_parse_artifacts_multiplos_blocos():
    """Dois blocos consecutivos com tipos diferentes são detectados."""
    text = "```echart\n{}\n```\n```table\n[]\n```"
    segments = parse_artifacts(text)
    kinds = [s[0] for s in segments]
    assert "echart" in kinds
    assert "table" in kinds


def test_render_artifact_segment_echart_invalido_nao_lanca(monkeypatch):
    """render_artifact_segment com echart e JSON inválido não levanta exceção."""
    import appaiforge.ui.chat as chat_mod

    class FakeBox:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def classes(self, *a, **kw):
            return self
        def props(self, *a, **kw):
            return self
        def style(self, *a, **kw):
            return self

    fb = FakeBox()
    monkeypatch.setattr(chat_mod.ui, "card", lambda **kw: fb)
    monkeypatch.setattr(chat_mod.ui, "label", lambda *a, **kw: fb)
    monkeypatch.setattr(chat_mod.ui, "expansion", lambda *a, **kw: fb)
    monkeypatch.setattr(chat_mod.ui, "code", lambda *a, **kw: fb)
    monkeypatch.setattr(chat_mod.ui, "echart", lambda *a, **kw: fb)
    monkeypatch.setattr(chat_mod.ui, "markdown", lambda *a, **kw: fb)

    box = FakeBox()
    # Não deve lançar nenhuma exceção
    render_artifact_segment(box, "echart", "isto não é json {{{")
