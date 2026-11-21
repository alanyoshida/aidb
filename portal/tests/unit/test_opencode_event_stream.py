"""O stream de eventos do opencode tem prazo de leitura: sem ele, um container recriado no meio
da execução prendia a thread da fila do sistema para sempre (achado no piloto com LLM real)."""

import httpx

from appaiforge.harness.base import RunEvent
from appaiforge.harness.opencode import OpencodeHarness


def test_stream_de_eventos_tem_prazo_de_leitura_e_falha_com_mensagem(monkeypatch):
    seen = {}

    def fake_stream(method, url, timeout=None):
        seen["timeout"] = timeout
        raise httpx.ReadTimeout("sem eventos")

    monkeypatch.setattr(httpx, "stream", fake_stream)
    events: list[RunEvent] = []
    OpencodeHarness(lambda _s: "http://x")._stream_events("http://x", "ses", events.append)
    assert isinstance(seen["timeout"], httpx.Timeout)
    assert seen["timeout"].read == OpencodeHarness.EVENT_READ_TIMEOUT
    assert [e.kind for e in events] == ["run_error"]
    assert "falha de comunicação" in events[0].text
