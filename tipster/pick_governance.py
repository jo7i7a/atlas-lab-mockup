# -*- coding: utf-8 -*-
"""PICK GOVERNANCE (2026-08-22, mandato del Director tras
AUDITORIA_PICK_GOVERNANCE_2026-08-22.md, secciones 15-17). Reemplaza el
criterio anterior de tipster/governance.py ("EV%>0 + familia de motor con
gobernanza fuerte") -- una prediccion solo puede convertirse en Pick ATLAS si
existe una hipotesis de umbral CONGELADA (mercado+seleccion+umbral+motor
esperado, ver pick_governance_thresholds.json) que ademas alcanzo el estado
CERTIFICADO (protocolo Gate/FVP-1 completo de Carril B, nunca por atajo).

Principio de inmutabilidad de hipotesis: una hipotesis nunca se edita una vez
congelada -- cambiar cualquier condicion relevante (umbral, mercado,
seleccion, motor) crea una hipotesis NUEVA con un hypothesis_id distinto
(sufijo de version). La evidencia de versiones distintas nunca se mezcla.

HypothesisStatus es un eje DISTINTO de atlas_pocket.engines.contract.
GovernanceStatus (esa es sobre el MOTOR/familia; esta es sobre la HIPOTESIS
de pick) -- deliberadamente separados, nunca se fusionan.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from atlas_lab_mockup.tipster.common import ROOT, load_json

THRESHOLDS_PATH = ROOT + r"\tipster\pick_governance_thresholds.json"


class HypothesisStatus(str, Enum):
    EN_OBSERVACION = "EN_OBSERVACION"
    CANDIDATO = "CANDIDATO"
    CERTIFICADO = "CERTIFICADO"
    SUSPENDIDO = "SUSPENDIDO"
    NO_BACKTESTEABLE = "NO_BACKTESTEABLE"


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    mercado: str
    seleccion: str
    motor_esperado: str
    umbral_prob: float
    estado: HypothesisStatus
    retirada: bool


def load_hypotheses(path: str | None = None) -> list[Hypothesis]:
    """Lee pick_governance_thresholds.json. Nunca lanza si el archivo esta
    ausente o vacio -- devuelve lista vacia (ninguna hipotesis definida =
    ninguna senal puede convertirse en Pick, comportamiento seguro por
    defecto)."""
    data = load_json(path or THRESHOLDS_PATH, {}) or {}
    out = []
    for h in data.get("hypotheses", []):
        out.append(Hypothesis(
            hypothesis_id=h["hypothesis_id"],
            mercado=h["mercado"],
            seleccion=h["seleccion"],
            motor_esperado=h["motor_esperado"],
            umbral_prob=float(h["umbral_prob"]),
            estado=HypothesisStatus(h["estado"]),
            retirada=bool(h.get("retirada", False)),
        ))
    return out


def matching_hypothesis(
    mercado: str, seleccion: str, prob: float | None, motor: str | None,
    hypotheses: list[Hypothesis] | None = None,
) -> Hypothesis | None:
    """Dado un candidato real (mercado/seleccion/probabilidad/motor), busca
    si cae dentro de alguna hipotesis activa (no retirada) congelada para
    exactamente ese mercado+seleccion+motor, con prob >= su umbral. Ninguna
    coincidencia -> None (la senal no esta bajo ninguna hipotesis de
    gobernanza todavia, no puede ser mas que una prediccion cruda de motor).
    Si dos hipotesis activas coincidieran (no deberia ocurrir con la
    disciplina de version unica activa por mercado+seleccion, pero se cubre
    por seguridad), se devuelve la de umbral mas alto -- la mas exigente."""
    if prob is None or motor is None:
        return None
    pool = hypotheses if hypotheses is not None else load_hypotheses()
    candidates = [
        h for h in pool
        if not h.retirada and h.mercado == mercado and h.seleccion == seleccion
        and h.motor_esperado == motor and prob >= h.umbral_prob
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda h: h.umbral_prob)


def passes_pick_gate(hypothesis: Hypothesis | None) -> bool:
    """Unica autoridad para decidir si una senal puede convertirse en Pick
    ATLAS (mandato del Director, 2026-08-22): SOLO si existe una hipotesis
    congelada que coincide Y esta en estado CERTIFICADO. Ninguna senal sin
    hipotesis, o con hipotesis EN_OBSERVACION/CANDIDATO/SUSPENDIDA/NO_
    BACKTESTEABLE, puede pasar -- reemplaza por completo el criterio anterior
    de "EV%>0 + familia con gobernanza fuerte" (tipster/governance.py)."""
    return hypothesis is not None and hypothesis.estado == HypothesisStatus.CERTIFICADO
