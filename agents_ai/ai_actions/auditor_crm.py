"""Wrapper IA del Auditor de agentes — alias de naming consistente.

La logica canonica vive en `agents_ai/auditor_agente.py` (modulo existente
que ya estaba bien organizado y NO se modifica). Aca solo re-exportamos
las funciones con nombres uniformes para que las views usen el mismo
patron de import que las demas acciones IA:

    from agents_ai.ai_actions import auditor_crm
    auditoria = auditor_crm.generar(agente, usuario=request.user, dias=30)
    auditor_crm.aplicar(auditoria, campo, usuario=request.user)
    auditor_crm.aplicar_faq(auditoria, usuario=request.user)
    auditor_crm.revertir(auditoria, usuario=request.user)
"""
from agents_ai.auditor_agente import (
    aplicar_faq_sugerido as aplicar_faq,
    aplicar_sugerencia as aplicar,
    ejecutar_auditoria as generar,
    revertir_auditoria as revertir,
)

__all__ = ['generar', 'aplicar', 'aplicar_faq', 'revertir']
