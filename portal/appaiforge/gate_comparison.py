"""Comparação do spike S5 (task 6.2, change db-proxy-gate-data-plane): mede
o que o caminho antigo (globs do `permission.bash` + protocolo de permissão
do harness) pegaria vs o que o proxy no data plane (modo sombra) classifica
pra toda statement que atravessa a conexão — antes de virar o default
enforcing (etapa 7).

Os dois caminhos classificam com o MESMO classificador canônico (sqlgate) —
não há "quem classifica melhor" a comparar diretamente. O que diverge é
COBERTURA: o caminho antigo só pergunta quando o comando de bash bate um dos
globs (`*psql*`, `*DELETE FROM*`, ...); o proxy vê toda statement que
atravessa a conexão, não importa como foi emitida (ADR da etapa 4;
proposal.md cita `psql -f arquivo.sql` como o furo que isso fecha).

Casamento: os dois caminhos registram `GateDecision` pra a MESMA ação do
agente, perto no tempo, dentro do mesmo run. Casa por `run_id` + janela de
tempo (nearest-neighbor guloso) — não casa por texto de SQL porque o
caminho antigo extrai o SQL por regex do comando de bash
(`gate.extract_sql`) e pode divergir do texto exato que trafegou no wire
protocol.

Categorias do resultado:
- `escapes`: statement sombra (confirmável/bloqueada) sem pedido antigo
  correspondente — o glob NUNCA perguntou. É o caso que a etapa 4 existe
  pra fechar.
- `sem_correspondencia_antiga`: pedido antigo (confirmável/bloqueada) sem
  sombra correspondente — glob perguntou mas o tráfego da conexão não
  bateu (revisão manual: pode ser timing, conexão fora do proxy, ou FP
  genuíno do glob).
- `discordancia`: casados, mas classificação diferente — sinal de que
  `extract_sql` (regex) capturou um texto diferente do que foi pro banco.
- concordância (só a contagem): casados e com a mesma classificação — os
  dois caminhos bateram.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .db import session_scope
from .models import GateDecision

_FRICTION_CLASSES = ("confirmavel", "bloqueada")


@dataclasses.dataclass
class ComparisonReport:
    escapes: list[dict]
    sem_correspondencia_antiga: list[dict]
    discordancia: list[dict]
    concordancia_count: int
    total_antigo: int
    total_sombra: int


def _row_to_dict(r: GateDecision) -> dict:
    return {
        "id": r.id,
        "system_id": r.system_id,
        "run_id": r.run_id,
        "sql": r.sql,
        "connection_name": r.connection_name,
        "classification": r.classification,
        "decision": r.decision,
        "created_at": r.created_at,
    }


def compare(*, system_id: str | None = None, since_days: int = 30, window_seconds: float = 30.0) -> ComparisonReport:
    """Varre `GateDecision` (origem agente) dos últimos `since_days` dias e
    casa os dois caminhos por run_id + proximidade de horário, dentro de
    `window_seconds`."""
    since = datetime.now(timezone.utc) - timedelta(days=since_days)
    with session_scope() as s:
        query = select(GateDecision).where(GateDecision.origin == "agente", GateDecision.created_at >= since)
        if system_id:
            query = query.where(GateDecision.system_id == system_id)
        rows = s.execute(query.order_by(GateDecision.created_at)).scalars().all()
        antigo = [_row_to_dict(r) for r in rows if r.decision != "sombra"]
        sombra = [_row_to_dict(r) for r in rows if r.decision == "sombra"]

    antigo_por_run: dict[str | None, list[dict]] = defaultdict(list)
    sombra_por_run: dict[str | None, list[dict]] = defaultdict(list)
    for r in antigo:
        antigo_por_run[r["run_id"]].append(r)
    for r in sombra:
        sombra_por_run[r["run_id"]].append(r)

    escapes: list[dict] = []
    sem_correspondencia_antiga: list[dict] = []
    discordancia: list[dict] = []
    concordancia_count = 0

    for run_id in set(antigo_por_run) | set(sombra_por_run):
        a_list = sorted(antigo_por_run.get(run_id, []), key=lambda r: r["created_at"])
        s_list = sorted(sombra_por_run.get(run_id, []), key=lambda r: r["created_at"])

        # casamento guloso: todos os pares dentro da janela, do mais
        # próximo no tempo pro mais distante, sem reusar nenhum dos lados
        candidates = []
        for i, a in enumerate(a_list):
            for j, sm in enumerate(s_list):
                delta = abs((a["created_at"] - sm["created_at"]).total_seconds())
                if delta <= window_seconds:
                    candidates.append((delta, i, j))
        candidates.sort(key=lambda c: c[0])

        matched_a: set[int] = set()
        matched_s: set[int] = set()
        for delta, i, j in candidates:
            if i in matched_a or j in matched_s:
                continue
            matched_a.add(i)
            matched_s.add(j)
            a, sm = a_list[i], s_list[j]
            if a["classification"] == sm["classification"]:
                concordancia_count += 1
            else:
                discordancia.append({"antigo": a, "sombra": sm, "delta_segundos": delta})

        for i, a in enumerate(a_list):
            if i not in matched_a and a["classification"] in _FRICTION_CLASSES:
                sem_correspondencia_antiga.append(a)
        for j, sm in enumerate(s_list):
            if j not in matched_s and sm["classification"] in _FRICTION_CLASSES:
                escapes.append(sm)

    return ComparisonReport(
        escapes=escapes,
        sem_correspondencia_antiga=sem_correspondencia_antiga,
        discordancia=discordancia,
        concordancia_count=concordancia_count,
        total_antigo=len(antigo),
        total_sombra=len(sombra),
    )


def format_report(report: ComparisonReport) -> str:
    lines = [
        "=== Comparação S5: glob (control plane) vs sombra (data plane) ===",
        f"Total de decisões do caminho antigo (glob): {report.total_antigo}",
        f"Total de statements auditadas em sombra: {report.total_sombra}",
        f"Casadas e concordantes: {report.concordancia_count}",
        f"Discordâncias (classificação diferente): {len(report.discordancia)}",
        f"Escapes do glob (sombra pegou, glob nunca perguntou): {len(report.escapes)}",
        f"Sem correspondência em sombra (glob perguntou, sem tráfego casado): {len(report.sem_correspondencia_antiga)}",
    ]

    if report.escapes:
        lines.append("")
        lines.append("--- ESCAPES (falso-negativo do glob) ---")
        for e in report.escapes[:50]:
            lines.append(
                f"  [{e['created_at']}] run={e['run_id']} conexão={e['connection_name']} "
                f"classe={e['classification']}: {e['sql'][:120]}"
            )

    if report.discordancia:
        lines.append("")
        lines.append("--- DISCORDÂNCIAS (extract_sql != texto no wire) ---")
        for d in report.discordancia[:50]:
            a, sm = d["antigo"], d["sombra"]
            lines.append(
                f"  antigo={a['classification']} ({a['sql'][:80]!r}) vs "
                f"sombra={sm['classification']} ({sm['sql'][:80]!r}) Δ{d['delta_segundos']:.1f}s"
            )

    if report.sem_correspondencia_antiga:
        lines.append("")
        lines.append("--- SEM CORRESPONDÊNCIA EM SOMBRA (revisão manual) ---")
        for a in report.sem_correspondencia_antiga[:50]:
            lines.append(f"  [{a['created_at']}] run={a['run_id']} classe={a['classification']}: {a['sql'][:120]}")

    return "\n".join(lines)
