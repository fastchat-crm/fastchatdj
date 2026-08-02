"""Shim de compatibilidad.

Las utilidades de humanización (burbujas, delays, ánimo, saludos) se movieron a
`agents_ai/agentes/humanizacion.py`. Este módulo re-exporta todo para no romper
imports existentes (`from agents_ai.humanizacion import dividir_en_burbujas`, etc.).
"""
from agents_ai.agentes.humanizacion import *  # noqa: F401,F403
