#!/usr/bin/env bash
# Checa se uma imagem construída tem segredo, antes de qualquer push (change add-ci-workflow,
# design D10). Dois detectores, os dois bloqueando:
#   1. trivy: camadas e configuração da imagem (ENV, labels, histórico de comandos);
#   2. gitleaks: o sistema de arquivos exportado da imagem, com .gitleaks-image.toml.
# Os valores achados saem mascarados. Sai com código diferente de zero em qualquer achado.
# Uso: scan-image-secrets.sh <imagem>   (rodar da raiz do repositório)
set -euo pipefail

IMAGE="${1:?uso: scan-image-secrets.sh <imagem>}"
TRIVY="aquasec/trivy:0.76.2@sha256:8f6bb947dbc528902e11f2f5be52f7b519f6a39d5d148f41166f2040499768fb"
ALPINE="alpine:3.22@sha256:49340b346798875b5592e5d420241f2f9cfba5f47e62ebb1446a1b34734e898f"
GITLEAKS="ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f"
CONFIG="$(pwd)/.gitleaks-image.toml"
WORK="$(mktemp -d)"
trap 'docker run --rm -v "$WORK":/w "$ALPINE" rm -rf /w/fs >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT

echo "== trivy: segredos nas camadas e na configuração de $IMAGE"
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock:ro "$TRIVY" image --quiet \
  --scanners secret --image-config-scanners secret --exit-code 1 --format table "$IMAGE"

echo "== gitleaks: segredos no sistema de arquivos de $IMAGE"
mkdir -p "$WORK/fs"
CID="$(docker create "$IMAGE")"
docker export "$CID" | tar -x -C "$WORK/fs" --no-same-owner --no-same-permissions 2>/dev/null || true
docker rm "$CID" >/dev/null
docker run --rm -v "$WORK/fs":/scan:ro -v "$CONFIG":/cfg.toml:ro -w /scan "$GITLEAKS" \
  dir . --config /cfg.toml --redact --no-banner --log-level warn

echo "== nenhum segredo em $IMAGE"
