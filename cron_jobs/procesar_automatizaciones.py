"""Procesa las automatizaciones vencidas. Cadencia sugerida: cada 1 minuto.

Es el que hace avanzar los pasos `esperar`: una ejecución que quedó dormida
hasta dentro de dos días la retoma este cron cuando llega la fecha. Sin él, las
automatizaciones con espera nunca terminan.
"""
import os, sys

from django.core.wsgi import get_wsgi_application

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')

application = get_wsgi_application()

from automatizacion.motor import procesar_pendientes
from core.funciones import logCron

try:
    resultado = procesar_pendientes()
    total = sum(resultado.values())
    if total:
        logCron(
            'procesar_automatizaciones',
            f"{resultado['completadas']} completadas · {resultado['esperando']} esperando · "
            f"{resultado['fallidas']} fallidas",
            exito=True,
        )
except Exception as ex:
    logCron('procesar_automatizaciones', f'Error: {ex}', exito=False)
    raise
