"""Smoke E2E: portal responde através do Traefik (task 1.5)."""

import urllib.request


def test_portal_responde_via_edge(base_url):
    with urllib.request.urlopen(f"{base_url}/api/health", timeout=10) as resp:
        assert resp.status == 200
        body = resp.read().decode()
        assert '"status": "ok"' in body or '"status":"ok"' in body
