"""Reporte de carga y actividad de asesores por sesión.

Alimenta el modal "Carga de asesores" de `/whatsapp/sesiones/`. Además de las
conversaciones abiertas de cada asesor responde la pregunta operativa: ¿está
respondiendo? Para eso mira los mensajes salientes escritos por el asesor
(`MensajeWhatsApp.agente`) en las últimas 24 horas.
"""

from datetime import timedelta

from django.db.models import Count, Max
from django.utils import timezone

from .models import (
    ConversacionWhatsApp, MensajeWhatsApp, HistorialAsignacion,
    DisponibilidadAgente,
)


HORAS_VENTANA_ACTIVIDAD = 24


def reporte_carga_asesores(sesion):
    """[filas, resumen] de la actividad de los asesores de una sesión.

    Cada fila trae: conversaciones abiertas, cuántas de esas respondió en las
    últimas 24 h, mensajes que escribió, su última respuesta y disponibilidad.
    `pendientes` son las abiertas que NO tocó en la ventana: la fila roja que el
    supervisor tiene que mirar.
    """
    desde = timezone.now() - timedelta(hours=HORAS_VENTANA_ACTIVIDAD)

    abiertas_qs = ConversacionWhatsApp.objects.filter(
        contacto__sesion=sesion, estado_conversacion=0,
        conversacion_finalizada=False, status=True, contacto__status=True,
    )
    abiertas = dict(
        abiertas_qs.values('asignado_a').annotate(c=Count('id')).values_list('asignado_a', 'c')
    )

    asignaciones_24h = dict(
        HistorialAsignacion.objects.filter(
            conversacion__contacto__sesion=sesion, fecha__gte=desde,
        ).values('asignado_a').annotate(c=Count('id')).values_list('asignado_a', 'c')
    )

    # Actividad real: mensajes que escribió el asesor (no la IA ni automáticos).
    mensajes_qs = MensajeWhatsApp.objects.filter(
        conversacion__contacto__sesion=sesion,
        agente__isnull=False, fecha__gte=desde, status=True,
    )
    actividad = {
        f['agente']: f
        for f in mensajes_qs.values('agente').annotate(
            mensajes=Count('id'),
            conversaciones=Count('conversacion', distinct=True),
            ultima=Max('fecha'),
        )
    }
    # Última respuesta histórica (fuera de la ventana) para los que no aparecen.
    ultima_historica = dict(
        MensajeWhatsApp.objects.filter(
            conversacion__contacto__sesion=sesion, agente__isnull=False, status=True,
        ).values('agente').annotate(ultima=Max('fecha')).values_list('agente', 'ultima')
    )

    perfiles = sesion.perfilsesionwhatsapp_set.filter(status=True).select_related('usuario')
    offline = set(
        DisponibilidadAgente.objects.filter(
            usuario_id__in=[p.usuario_id for p in perfiles], status=True, disponible=False,
        ).values_list('usuario_id', flat=True)
    )

    filas = []
    for perfil in perfiles:
        uid = perfil.usuario_id
        act = actividad.get(uid) or {}
        abiertas_asesor = abiertas.get(uid, 0)
        respondidas = act.get('conversaciones', 0)
        filas.append({
            'usuario_id': uid,
            'nombre': perfil.usuario.get_full_name() or perfil.usuario.username,
            'rol': perfil.get_rol_display() if hasattr(perfil, 'get_rol_display') else perfil.rol,
            'abiertas': abiertas_asesor,
            'asig_24h': asignaciones_24h.get(uid, 0),
            'respondidas_24h': respondidas,
            'mensajes_24h': act.get('mensajes', 0),
            'pendientes': max(abiertas_asesor - respondidas, 0),
            'ultima_respuesta': act.get('ultima') or ultima_historica.get(uid),
            'respondio_24h': bool(act.get('mensajes')),
            'disponible': uid not in offline,
        })
    filas.sort(key=lambda f: (-f['pendientes'], -f['abiertas']))

    resumen = {
        'sin_asignar': abiertas.get(None, 0),
        'total_abiertas': sum(abiertas.values()),
        'asesores': len(filas),
        'sin_responder_24h': sum(1 for f in filas if f['abiertas'] and not f['respondio_24h']),
        'horas': HORAS_VENTANA_ACTIVIDAD,
    }
    return filas, resumen
