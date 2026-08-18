"""Reporte de carga y actividad de asesores por sesión.

Alimenta el modal "Carga de asesores" de `/whatsapp/sesiones/`. Además de las
conversaciones abiertas de cada asesor responde la pregunta operativa: ¿está
respondiendo? Para eso mira los mensajes salientes escritos por el asesor
(`MensajeWhatsApp.agente`) en las últimas 24 horas.
"""

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Max, Subquery, OuterRef
from django.utils import timezone

from .models import (
    ConversacionWhatsApp, MensajeWhatsApp, HistorialAsignacion,
    DisponibilidadAgente,
)


HORAS_VENTANA_ACTIVIDAD = 24
HORAS_VENTANA_META_CUSTOMER_SERVICE = 24


def _fmt_duracion(delta):
    """Formatea una duración a un texto corto en español ("2d 3h", "5h 12m")."""
    total = max(int(delta.total_seconds()), 0)
    dias = total // 86400
    horas = (total % 86400) // 3600
    mins = (total % 3600) // 60
    if dias:
        return f'{dias}d {horas}h'
    if horas:
        return f'{horas}h {mins}m'
    return f'{mins}m'


def _aware(fecha):
    """Alinea la conciencia de zona de `fecha` con la de `timezone.now()`.

    Con USE_TZ=True `timezone.now()` es aware; con USE_TZ=False es naive. Los
    subqueries pueden devolver el otro tipo, así que se normaliza a lo que dicta
    settings para poder compararlas sin TypeError.
    """
    if not fecha:
        return fecha
    tz = timezone.get_current_timezone()
    if settings.USE_TZ:
        return timezone.make_aware(fecha, tz) if timezone.is_naive(fecha) else fecha
    return timezone.make_naive(fecha, tz) if timezone.is_aware(fecha) else fecha


def _fmt_fecha(fecha):
    fecha = _aware(fecha)
    if not fecha:
        return '—'
    if settings.USE_TZ:
        fecha = timezone.localtime(fecha)
    return fecha.strftime('%d/%m/%Y %H:%M')


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

    # Buckets por estado (disjuntos, consistentes con las tabs del inbox).
    limite_meta = timezone.now() - timedelta(hours=HORAS_VENTANA_META_CUSTOMER_SERVICE)
    ult_entrante_sq = (
        MensajeWhatsApp.objects
        .filter(conversacion=OuterRef('pk'))
        .exclude(remitente=(sesion.numero or ''))
        .order_by('-fecha').values('fecha')[:1]
    )
    caducadas = dict(
        ConversacionWhatsApp.objects.filter(
            contacto__sesion=sesion, estado_conversacion=0, conversacion_finalizada=False,
            status=True, contacto__status=True, contacto__sesion__proveedor='meta',
        ).annotate(_ult=Subquery(ult_entrante_sq)).filter(_ult__lte=limite_meta)
        .values('asignado_a').annotate(c=Count('id')).values_list('asignado_a', 'c')
    )
    pendientes_recon = dict(
        ConversacionWhatsApp.objects.filter(
            contacto__sesion=sesion, estado_conversacion=1, pendiente_reconexion=True,
            reconectada=False, status=True, contacto__status=True,
        ).values('asignado_a').annotate(c=Count('id')).values_list('asignado_a', 'c')
    )
    finalizadas = dict(
        ConversacionWhatsApp.objects.filter(
            contacto__sesion=sesion, conversacion_finalizada=True,
            status=True, contacto__status=True,
        ).values('asignado_a').annotate(c=Count('id')).values_list('asignado_a', 'c')
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
        caducadas_asesor = caducadas.get(uid, 0)
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
            'c_abiertas': max(abiertas_asesor - caducadas_asesor, 0),
            'c_caducadas': caducadas_asesor,
            'c_pendientes': pendientes_recon.get(uid, 0),
            'c_finalizadas': finalizadas.get(uid, 0),
        })
    filas.sort(key=lambda f: (-f['pendientes'], -f['abiertas']))

    estado_caducadas = sum(caducadas.values())
    resumen = {
        'sin_asignar': abiertas.get(None, 0),
        'total_abiertas': sum(abiertas.values()),
        'asesores': len(filas),
        'sin_responder_24h': sum(1 for f in filas if f['abiertas'] and not f['respondio_24h']),
        'horas': HORAS_VENTANA_ACTIVIDAD,
        'estado_abiertas': max(sum(abiertas.values()) - estado_caducadas, 0),
        'estado_caducadas': estado_caducadas,
        'estado_pendientes': sum(pendientes_recon.values()),
        'estado_finalizadas': sum(finalizadas.values()),
    }
    return filas, resumen


def detalle_carga_asesor(sesion, usuario_id, estado):
    """Filas de detalle de las conversaciones de un asesor en un estado dado.

    `estado` ∈ {abiertas, caducadas, pendientes, finalizadas}. Cada fila trae
    contacto, teléfono, fecha del último mensaje saliente y un texto de tiempo
    cuyo significado depende del estado (ver `_tiempo_por_estado`).
    """
    ahora = timezone.now()
    limite_meta = ahora - timedelta(hours=HORAS_VENTANA_META_CUSTOMER_SERVICE)
    numero_sesion = sesion.numero or ''
    es_meta = (sesion.proveedor == 'meta')

    ult_entrante_sq = (
        MensajeWhatsApp.objects
        .filter(conversacion=OuterRef('pk'))
        .exclude(remitente=numero_sesion)
        .order_by('-fecha').values('fecha')[:1]
    )
    ult_saliente_sq = (
        MensajeWhatsApp.objects
        .filter(conversacion=OuterRef('pk'), remitente=numero_sesion)
        .order_by('-fecha').values('fecha')[:1]
    )

    base = (
        ConversacionWhatsApp.objects
        .filter(contacto__sesion=sesion, asignado_a_id=usuario_id,
                status=True, contacto__status=True)
        .select_related('contacto')
        .annotate(_ult_entrante=Subquery(ult_entrante_sq),
                  _ult_saliente=Subquery(ult_saliente_sq))
    )

    if estado == 'abiertas':
        qs = base.filter(estado_conversacion=0, conversacion_finalizada=False).exclude(
            contacto__sesion__proveedor='meta', _ult_entrante__lte=limite_meta,
        )
    elif estado == 'caducadas':
        qs = base.filter(
            estado_conversacion=0, conversacion_finalizada=False,
            contacto__sesion__proveedor='meta', _ult_entrante__lte=limite_meta,
        )
    elif estado == 'pendientes':
        qs = base.filter(estado_conversacion=1, pendiente_reconexion=True, reconectada=False)
    elif estado == 'finalizadas':
        qs = base.filter(conversacion_finalizada=True)
    else:
        return []

    filas = []
    for c in qs.order_by('-id'):
        cont = c.contacto
        filas.append({
            'contacto': cont.contacto_nombre or cont.numero_telefono or cont.contacto_numero or 'Sin nombre',
            'telefono': cont.numero_telefono or cont.contacto_numero or cont.from_number or '—',
            'ultimo_msj': _fmt_fecha(c._ult_saliente),
            'tiempo': _tiempo_por_estado(estado, c, es_meta, ahora),
        })
    return filas


def _tiempo_por_estado(estado, c, es_meta, ahora):
    ult_ent = _aware(getattr(c, '_ult_entrante', None))
    if estado == 'abiertas':
        if es_meta and ult_ent:
            vence = ult_ent + timedelta(hours=HORAS_VENTANA_META_CUSTOMER_SERVICE)
            if vence > ahora:
                return f'Vence en {_fmt_duracion(vence - ahora)}'
            return f'Caducó hace {_fmt_duracion(ahora - vence)}'
        expira = _aware(c.fecha_hora_expira)
        if expira:
            if expira > ahora:
                return f'Vence en {_fmt_duracion(expira - ahora)}'
            return f'Expiró hace {_fmt_duracion(ahora - expira)}'
        return 'Sin límite'
    if estado == 'caducadas':
        if ult_ent:
            vence = ult_ent + timedelta(hours=HORAS_VENTANA_META_CUSTOMER_SERVICE)
            return f'Caducó hace {_fmt_duracion(ahora - vence)}'
        return '—'
    if estado == 'pendientes':
        ref = _aware(c.fecha_fin_conversacion or c.contacto.fecha_ultimo_mensaje)
        if ref:
            return f'Pendiente hace {_fmt_duracion(ahora - ref)}'
        return '—'
    if estado == 'finalizadas':
        fin = _aware(c.fecha_fin_conversacion)
        if fin:
            return f'Finalizó hace {_fmt_duracion(ahora - fin)} ({_fmt_fecha(fin)})'
        return '—'
    return '—'
