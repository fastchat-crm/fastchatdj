"""Enrutador round-robin de conversaciones a agentes humanos.

El pool de candidatos y el orden los provee la fuente única
`crm.helpers_asignacion.candidatos_ordenados` (asesores de la SESIÓN/número vía
`PerfilSesionWhatsApp`, filtrados por `DisponibilidadAgente.disponible` y
`max_conversaciones`, ordenados por menor carga y luego por antigüedad de
asignación). Este módulo solo agrega lo propio del round-robin:

  1. Lock transaccional (`select_for_update`) para evitar doble asignación
     concurrente de la misma conversación.
  2. Traza de la decisión en `AsignacionAutomatica`.
"""
from __future__ import annotations

import logging
from typing import Optional

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    AsignacionAutomatica,
    ConversacionWhatsApp,
    DisponibilidadAgente,
    HistorialAsignacion,
)

logger = logging.getLogger(__name__)


def asignar_automaticamente(conv: ConversacionWhatsApp,
                            estrategia: str = 'round_robin') -> Optional[int]:
    """Asigna la conversación a un agente y devuelve el Usuario.id asignado,
    o None si no hay candidatos disponibles.

    Usa la fuente única `crm.helpers_asignacion.candidatos_ordenados` (pool por
    departamento + filtro de disponibilidad + orden por carga). Esta función
    aporta sólo la parte específica del round-robin: el lock transaccional para
    evitar doble asignación concurrente y la traza `AsignacionAutomatica`.

    Si la conversación ya tiene asignado_a, no hace nada.
    """
    if conv.asignado_a_id:
        return conv.asignado_a_id
    sesion = conv.sesion
    if not sesion:
        return None

    from crm.helpers_asignacion import candidatos_ordenados, _marcar_ultima_asignacion

    with transaction.atomic():
        conv_locked = (
            ConversacionWhatsApp.objects
            .select_for_update()
            .filter(pk=conv.pk)
            .first()
        )
        if not conv_locked or conv_locked.asignado_a_id:
            return conv_locked.asignado_a_id if conv_locked else None

        candidatos = candidatos_ordenados(conv_locked)
        if not candidatos:
            logger.info("Round-robin: sin candidatos disponibles para sesion=%s", sesion.id)
            return None
        usuario, carga = candidatos[0]

        conv_locked.asignado_a_id = usuario.id
        conv_locked.fecha_asignacion = timezone.now()
        if not conv_locked.primer_agente_id:
            conv_locked.primer_agente_id = usuario.id
        conv_locked.save(update_fields=[
            'asignado_a', 'fecha_asignacion', 'primer_agente',
        ])

        _marcar_ultima_asignacion(usuario)

        AsignacionAutomatica.objects.create(
            conversacion=conv_locked,
            agente_id=usuario.id,
            estrategia=estrategia,
            motivo=f'carga_previa={carga}',
        )
        HistorialAsignacion.objects.create(
            conversacion=conv_locked,
            asignado_a_id=usuario.id,
            asignado_por=None,
            nota=f'Asignación automática ({estrategia}). Carga previa: {carga}.',
        )
        logger.info(
            "Round-robin: conv=%s → agente=%s (carga=%s, estrategia=%s)",
            conv_locked.id, usuario.id, carga, estrategia,
        )
        return usuario.id
