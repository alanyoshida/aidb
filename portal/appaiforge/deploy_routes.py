"""Webhook do GitLab para sistemas só implantação (change add-deploy-only-system, D7).

Fora da autenticação de sessão: a única credencial é o segredo do sistema no `X-Gitlab-Token`,
comparado em tempo constante. Um webhook válido só agenda a mesma verificação da consulta
periódica; o corpo da chamada nem é lido.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import deploy

router = APIRouter()


@router.post("/hooks/gitlab/{system_id}")
def gitlab_hook(system_id: str, request: Request) -> JSONResponse:
    if not deploy.matches_webhook_secret(system_id, request.headers.get("x-gitlab-token", "")):
        return JSONResponse({"error": "não autorizado"}, status_code=401)
    deploy.schedule_webhook_check(system_id)
    return JSONResponse({"status": "verificação agendada"}, status_code=202)
