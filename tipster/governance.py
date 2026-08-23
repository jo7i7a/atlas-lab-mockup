# -*- coding: utf-8 -*-
"""Filtro de calidad/gobernanza de Picks ATLAS (2026-08-22, mandato del
Director tras AUDITORIA_PICK_GOVERNANCE_2026-08-22.md).

REEMPLAZA el criterio anterior (2026-08-16): "EV%>0 + la familia de motor
tiene gobernanza fuerte (CERTIFICADO/PROMOVIDO/BASELINE), o no tiene
gobernanza en absoluto (caso de BTTS)". Ese criterio quedo RECHAZADO
explicitamente por el Director tras el backtest historico de la auditoria:
permitia picks de 38-45% de probabilidad y no distinguia una senal con edge
economico real de una sin el -- 7 de 8 selecciones evaluadas con ese criterio
resultaron con ROI negativo a cualquier umbral (BTTS, 1X2 Local/Empate,
Over/Under 2.5, Corners 9.5 Over/Under).

Nuevo criterio, unico: una prediccion solo pasa el gate de Pick ATLAS si
coincide con una hipotesis de umbral CONGELADA (ver
tipster/pick_governance.py / pick_governance_thresholds.json) que ademas ya
alcanzo el estado CERTIFICADO (protocolo Gate/FVP-1 completo de Carril B,
nunca por atajo). Mientras ninguna hipotesis este CERTIFICADA -- el estado
real de todas hoy, incluida la unica piloto (1X2 Visita >=50%, EN_OBSERVACION
-- Picks ATLAS no genera NINGUN pick nuevo. Esto es exactamente el
comportamiento pedido por el Director: "ausencia de Picks ATLAS certificados
no es un fallo del sistema; seria un fallo ocultar esa ausencia."
"""
from __future__ import annotations

from atlas_lab_mockup.tipster.pick_governance import Hypothesis, matching_hypothesis, passes_pick_gate

# Se preserva por compatibilidad de lectura/documentacion -- ya NO se usa
# para decidir si algo es Pick (ver passes_pick_gate). Describe el criterio
# de gobernanza de FAMILIA DE MOTOR (atlas_pocket.engines.contract.
# GovernanceStatus), un eje distinto del de HypothesisStatus.
STRONG_GOVERNANCE = ("CERTIFICADO", "PROMOVIDO", "BASELINE")


def passes_governance_gate(mercado: str, seleccion: str, prob: float | None, motor: str | None) -> bool:
    """Unica autoridad que decide si una senal puede llegar a Pick ATLAS.
    Delega enteramente en pick_governance.py: busca la hipotesis congelada
    (si existe) para este mercado/seleccion/motor con prob>=umbral, y exige
    que su estado sea CERTIFICADO. Sin hipotesis congelada -> nunca pasa,
    sin importar que tan alto sea el EV%."""
    hyp: Hypothesis | None = matching_hypothesis(mercado, seleccion, prob, motor)
    return passes_pick_gate(hyp)
