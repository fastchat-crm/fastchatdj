"""Enrutador round-robin de conversaciones a agentes humanos.

Criterios:
  1. Solo considera agentes con `DisponibilidadAgente.disponible=True`.
  2. Respeta `max_conversaciones` (no asigna más carga).
  3. Filtra por `sesiones` (si el agente tiene lista explícita; vacío = todas).
  4. Elige el agente con menos conversaciones abiertas — empate: el que lleva
     más tiempo sin recibir asignación.
  5. Registra la decisión en `AsignacionAutomatica` para auditoría.

Thread-safety: usa `select_for_update()` dentro de una transaction para evitar
que dos requests concurrentes asignen la misma conversación dos veces.
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


def _candidatos_para_sesion(sesion) -> list[DisponibilidadAgente]:
    """Lista de agentes elegibles para atender una sesión dada, ya filtrados y
    con la carga actual calculada."""
    qs = DisponibilidadAgente.objects.filter(
        disponible=True, status=True,
    ).select_related('usuario').prefetch_related('sesiones')

    candidatos = []
    for disp in qs:
        sesiones_ids = list(disp.sesiones.values_list('id', flat=True))
        if sesiones_ids and sesion.id not in sesiones_ids:
            continue
        carga = ConversacionWhatsApp.objects.filter(
            asignado_a=disp.usuario,
            conversacion_finalizada=False,
            status=True,
        ).count()
        if carga >= disp.max_conversaciones:
            continue
        candidatos.append((disp, carga))
    return candidatos


def asignar_automaticamente(conv: ConversacionWhatsApp,
                            estrategia: str = 'round_robin') -> Optional[int]:
    """Asigna la conversación a un agente y devuelve el Usuario.id asignado,
    o None si no hay candidatos disponibles.

    Si la conversación ya tiene asignado_a, no hace nada.
    """
    if conv.asignado_a_id:
        return conv.asignado_a_id
    sesion = conv.sesion
    if not sesion:
        return None

    with transaction.atomic():
        conv_locked = (
            ConversacionWhatsApp.objects
            .select_for_update()
            .filter(pk=conv.pk)
            .first()
        )
        if not conv_locked or conv_locked.asignado_a_id:
            return conv_locked.asignado_a_id if conv_locked else None

        candidatos = _candidatos_para_sesion(sesion)
        if not candidatos:
            logger.info("Round-robin: sin candidatos disponibles para sesion=%s", sesion.id)
            return None

        # Ordenar por carga ascendente y luego por último asignación (FIFO).
        def sort_key(item):
            disp, carga = item
            ultima = disp.ultimo_asignado_en or timezone.datetime.min.replace(
                tzinfo=timezone.get_current_timezone()
            )
            return (carga, ultima)

        candidatos.sort(key=sort_key)
        elegido, carga = candidatos[0]

        conv_locked.asignado_a_id = elegido.usuario_id
        conv_locked.fecha_asignacion = timezone.now()
        if not conv_locked.primer_agente_id:
            conv_locked.primer_agente_id = elegido.usuario_id
        conv_locked.save(update_fields=[
            'asignado_a', 'fecha_asignacion', 'primer_agente',
        ])

        elegido.ultimo_asignado_en = timezone.now()
        elegido.save(update_fields=['ultimo_asignado_en'])

        AsignacionAutomatica.objects.create(
            conversacion=conv_locked,
            agente_id=elegido.usuario_id,
            estrategia=estrategia,
            motivo=f'carga_previa={carga}',
        )
        HistorialAsignacion.objects.create(
            conversacion=conv_locked,
            asignado_a_id=elegido.usuario_id,
            asignado_por=None,
            nota=f'Asignación automática ({estrategia}). Carga previa: {carga}.',
        )
        logger.info(
            "Round-robin: conv=%s → agente=%s (carga=%s, estrategia=%s)",
            conv_locked.id, elegido.usuario_id, carga, estrategia,
        )
        return elegido.usuario_id
