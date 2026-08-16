# -*- coding: utf-8 -*-
"""Filtro de calidad/gobernanza reutilizado (2026-08-16, Tipster ATLAS,
Objetivo 4) -- NO se inventa un umbral nuevo de EV/probabilidad/confianza.

Mismo criterio ya vigente en atlas_pocket/context/analyst_conclusion.py:29
(`_STRONG_GOVERNANCE = (CERTIFICADO, PROMOVIDO, BASELINE)`), usado ahi como
gate real (no solo display) para decidir que familias de mercado cuentan
como "bien soportadas". No se importa el enum GovernanceStatus en runtime
(evita acoplar Picks ATLAS a atlas_pocket.context) -- son los mismos 3
valores string ya congelados como parte del contrato publico de cada
Estimation (ver atlas_pocket/engines/contract.py:22-28, `est.governance_status.value`).
"""
STRONG_GOVERNANCE = ("CERTIFICADO", "PROMOVIDO", "BASELINE")


def passes_governance_gate(governance_status):
    """True si el mercado tiene gobernanza fuerte (CERTIFICADO/PROMOVIDO/
    BASELINE), o si el mercado no tiene gobernanza en absoluto -- BTTS no
    viene de un motor de atlas_pocket (es hist.btts_general_pct, dato
    historico), asi que este filtro no le aplica estructuralmente. Decision
    explicita del Director (2026-08-16): BTTS puede llegar a ser PICK ATLAS
    igual que los mercados con motor real, sin exclusion especial."""
    if governance_status is None:
        return True
    return governance_status in STRONG_GOVERNANCE
