"""Agentes del motor de IA (bots que hablan con un LLM).

  - resumidor.py    : AgenteResumidor — resume + analiza sentimiento al cierre.
  - auditor.py      : auditor IA de la configuración de un agente.
  - humanizacion.py : burbujas, delays, ánimo, saludos — hace que el bot escriba como persona.

`agente_consultor.py` (el bot conversacional principal) todavía vive en la raíz
del paquete; se moverá aquí como fachada del grafo en la fase LangGraph.

Compat: los módulos viejos en la raíz (`agente_resumidor.py`, `auditor_agente.py`,
`humanizacion.py`) quedaron como shims que re-exportan desde aquí.
"""
