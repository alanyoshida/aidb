"""Tratamento da borda das apps no Collector (change edge-app-tracing, design D8).

Sobe o Collector 0.112.0 com os processors da borda do perfil Elastic, um receiver OTLP/HTTP e um
exporter de arquivo, manda spans como os que o Traefik gera e confere a saída. Os caminhos que o
Traefik vê (`/apps/<slug>/...`) são os mesmos nos três modos de rota, então isto vale para todos.
Pula sem Docker."""

import json
import os
import shutil
import subprocess
import time
import urllib.request

import pytest
import yaml

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
ELASTIC = os.path.join(ROOT, "deploy", "observability", "otel-collector-elastic.yaml")
IMAGE = "otel/opentelemetry-collector-contrib:0.112.0"

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker não instalado")


def _attrs(**values):
    return [{"key": k.replace("__", "."), "value": {"stringValue": v}} for k, v in values.items()]


def _span(span_id, name, kind, **attrs):
    return {
        "traceId": "5b8efff798038103d269b633813fc60c",
        "spanId": span_id,
        "name": name,
        "kind": kind,
        "startTimeUnixNano": "1700000000000000000",
        "endTimeUnixNano": "1700000000100000000",
        "attributes": _attrs(**attrs),
    }


SERVER, CLIENT = 2, 3

TRAEFIK_SPANS = [
    _span("0000000000000001", "GET", SERVER, url__path="/apps/crm/clientes/42",
          url__query="cpf=12345678900", url__full="http://h/apps/crm/clientes/42?cpf=12345678900",
          http__request__method="GET"),
    _span("0000000000000002", "GET", SERVER, url__path="/apps/crm/", url__full="http://h/apps/crm/",
          http__request__method="GET"),
    _span("0000000000000003", "GET", SERVER, url__path="/apps/crm/_nicegui/3.18.0/static/app.js",
          http__request__method="GET"),
    _span("0000000000000004", "GET", SERVER, url__path="/login", url__full="http://h/login?next=%2F",
          http__request__method="GET"),
    _span("0000000000000005", "ReverseProxy", CLIENT,
          url__full="http://10.0.0.1:8080/_nicegui/3.18.0/static/vue.js"),
    _span("0000000000000009", "ReverseProxy", CLIENT,
          url__full="http://portal:8080/_nicegui_ws/socket.io/?EIO=4&transport=websocket"),
    _span("0000000000000006", "POST", SERVER,
          url__path="/apps/crm/pedidos/3f2a9c1e-8b7d-4e21-9c3a-1234567890ab", http__request__method="POST"),
    _span("0000000000000007", "ReverseProxy", CLIENT,
          url__full="http://10.0.0.1:8080/clientes/42?cpf=12345678900"),
]

PORTAL_SPANS = [
    _span("0000000000000008", "GET /apps/crm/x", SERVER, url__path="/apps/crm/x", http__request__method="GET"),
]


def _payload():
    def resource(service, spans):
        return {"resource": {"attributes": _attrs(service__name=service)},
                "scopeSpans": [{"scope": {"name": "teste"}, "spans": spans}]}
    return {"resourceSpans": [resource("traefik", TRAEFIK_SPANS), resource("appaiforge-portal", PORTAL_SPANS)]}


def _config() -> dict:
    elastic = yaml.safe_load(open(ELASTIC))
    names = elastic["service"]["pipelines"]["traces"]["processors"]
    return {
        "receivers": {"otlp": {"protocols": {"http": {"endpoint": "0.0.0.0:4318"}}}},
        "processors": {n: elastic["processors"][n] for n in names},
        "exporters": {"file": {"path": "/out/spans.json"}},
        "service": {"pipelines": {"traces": {"receivers": ["otlp"], "processors": names, "exporters": ["file"]}}},
    }


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    work = tmp_path_factory.mktemp("edge")
    out = work / "out"
    out.mkdir()
    os.chmod(out, 0o777)  # o Collector roda sem root
    (work / "config.yaml").write_text(yaml.safe_dump(_config(), sort_keys=False))
    container = subprocess.run(
        ["docker", "run", "-d", "--rm", "-p", "127.0.0.1::4318",
         "-v", f"{work / 'config.yaml'}:/etc/c.yaml:ro", "-v", f"{out}:/out",
         IMAGE, "--config=/etc/c.yaml"],
        capture_output=True, text=True, check=True).stdout.strip()
    try:
        port = subprocess.run(["docker", "port", container, "4318"], capture_output=True, text=True,
                              check=True).stdout.split(":")[-1].strip()
        body = json.dumps(_payload()).encode()
        deadline = time.monotonic() + 30
        while True:
            try:
                request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/traces", data=body,
                                                 headers={"Content-Type": "application/json"})
                urllib.request.urlopen(request, timeout=5)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.5)
        target = out / "spans.json"
        deadline = time.monotonic() + 30
        while not (target.exists() and target.read_text().strip()):
            assert time.monotonic() < deadline, subprocess.run(
                ["docker", "logs", container], capture_output=True, text=True).stderr[-2000:]
            time.sleep(0.5)
        time.sleep(1)  # o batch pode chegar em mais de uma escrita
        spans = {}
        for line in target.read_text().splitlines():
            for rs in json.loads(line)["resourceSpans"]:
                service = next(a["value"]["stringValue"] for a in rs["resource"]["attributes"]
                               if a["key"] == "service.name")
                for ss in rs["scopeSpans"]:
                    for span in ss["spans"]:
                        attrs = {a["key"]: a["value"].get("stringValue") for a in span.get("attributes", [])}
                        spans[span["spanId"]] = {"service": service, "name": span["name"], "attrs": attrs}
        return spans
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)


def test_pedido_de_app_vira_servico_com_nome_normalizado_e_sem_query(exported):
    span = exported["0000000000000001"]
    assert span["service"] == "crm"
    assert span["name"] == "GET /clientes/{id}"
    assert "url.query" not in span["attrs"]
    assert span["attrs"]["url.full"] == "http://h/apps/crm/clientes/42"
    assert "appaiforge.slug" not in span["attrs"]  # foi para o recurso


def test_pagina_inicial_da_app(exported):
    assert (exported["0000000000000002"]["service"], exported["0000000000000002"]["name"]) == ("crm", "GET /")


def test_uuid_vira_id(exported):
    span = exported["0000000000000006"]
    assert (span["service"], span["name"]) == ("crm", "POST /pedidos/{id}")


def test_assets_e_reverse_proxy_de_asset_descartados(exported):
    assert "0000000000000003" not in exported
    assert "0000000000000005" not in exported
    assert "0000000000000009" not in exported  # websocket do portal


def test_pedido_ao_portal_continua_no_traefik_sem_query(exported):
    span = exported["0000000000000004"]
    assert (span["service"], span["name"]) == ("traefik", "GET")
    assert span["attrs"]["url.full"] == "http://h/login"


def test_reverse_proxy_de_app_fica_no_traefik_sem_query(exported):
    span = exported["0000000000000007"]
    assert span["service"] == "traefik"
    assert span["attrs"]["url.full"] == "http://10.0.0.1:8080/clientes/42"


def test_spans_de_outros_servicos_nao_mudam(exported):
    span = exported["0000000000000008"]
    assert (span["service"], span["name"]) == ("appaiforge-portal", "GET /apps/crm/x")


def test_nenhum_valor_de_query_sai(exported):
    assert "12345678900" not in json.dumps(exported)
