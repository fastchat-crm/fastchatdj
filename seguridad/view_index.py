from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Max
from django.shortcuts import render
from django.utils import timezone

from autenticacion.models import PerfilPersona
from core.funciones import addData, secure_module
from public.models import VisitaEntorno
from seguridad.models import *
from seguridad.templatetags.templatefunctions import encrypt
from whatsapp.funcionesWhatsappConversacion import conversaciones_por_caducar_por_sesion
from whatsapp.models import (
    SesionWhatsApp, Contacto, ConversacionWhatsApp, MensajeWhatsApp,
    PlantillaWhatsApp,
)


@login_required
@secure_module
def index(request):
    data = {
        'titulo': 'Inicio',
        'modulo': 'Menu',
        'ruta': '/',
        'fecha': datetime.now(),
    }
    addData(request, data)
    persona = request.user

    if request.method == 'POST':
        return render(request, 'seguridad/index.html', data)

    # Resumen de sesiones por canal — visible para todos los perfiles: cada
    # tarjeta lleva a las conversaciones/sesiones de su app e indica cuántas
    # sesiones hay y cuántas están conectadas (para saber si el canal funciona).
    q_mis_sesiones = Q(usuario=persona) | Q(
        perfilsesionwhatsapp__usuario=persona,
        perfilsesionwhatsapp__status=True,
    )
    sesiones_qs = (
        SesionWhatsApp.objects
        .filter(q_mis_sesiones, status=True)
        .select_related('config_meta', 'config_baileys', 'agente_ia')
        .distinct()
    )
    canales_def = [
        ('whatsapp', 'WhatsApp', ('baileys', 'meta'), '/whatsapp/conversaciones/', '/whatsapp/sesiones/'),
        ('facebook', 'Facebook', ('messenger',), '/facebook/conversaciones/', '/facebook/sesiones/'),
        ('instagram', 'Instagram', ('instagram',), '/instagram/conversaciones/', '/instagram/sesiones/'),
        ('tiktok', 'TikTok', ('tiktok',), '/tiktok/conversaciones/', '/tiktok/sesiones/'),
    ]
    canales_resumen = []
    for key, label, provs, url_conv, url_ses in canales_def:
        qs_c = sesiones_qs.filter(proveedor__in=provs)
        agg_c = qs_c.aggregate(
            total=Count('id'),
            conectadas=Count('id', filter=Q(estado='conectado')),
            desconectadas=Count('id', filter=Q(estado='desconectado')),
            errores=Count('id', filter=Q(estado='error')),
            pausadas=Count('id', filter=Q(activo=False)),
        )
        canales_resumen.append({
            'key': key,
            'label': label,
            'total': agg_c['total'],
            'conectadas': agg_c['conectadas'],
            'desconectadas': agg_c['desconectadas'],
            'errores': agg_c['errores'],
            'pausadas': agg_c['pausadas'],
            'url_conversaciones': url_conv,
            'url_sesiones': url_ses,
        })
    data['canales_resumen'] = canales_resumen

    # Alerta por sesión: conversaciones a punto de salirse de la ventana de 24h
    # de Meta. Se calcula antes del corte por perfil porque el asesor —que no
    # ve el resto del panel— es justamente quien tiene que responderlas. Cada
    # tarjeta enlaza al inbox ya filtrado (`?por_caducar=1`) y, si solo queda
    # una, abre su ventana de conversación directo.
    alertas_por_caducar = conversaciones_por_caducar_por_sesion(persona, sesiones_qs)
    data['alertas_por_caducar'] = alertas_por_caducar
    data['total_por_caducar'] = sum(a['total'] for a in alertas_por_caducar)

    if not persona.es_administrativo():
        data['PERFIL_EXISTE'] = False
        return render(request, 'seguridad/index.html', data)

    data['PERFIL_EXISTE'] = True
    # Bienvenida de primer ingreso: se muestra UNA sola vez y se marca vista.
    # Reemplaza al viejo modal "Conoce tu asistente" que salía en cada login
    # hasta configurar un agente IA.
    mostrar_bienvenida = not getattr(persona, 'bienvenida_vista', True)
    if mostrar_bienvenida:
        persona.bienvenida_vista = True
        persona.save(update_fields=['bienvenida_vista'])
    data['mostrar_bienvenida'] = mostrar_bienvenida

    ahora = timezone.now()
    hace_24h = ahora - timedelta(hours=24)
    hace_7d = ahora - timedelta(days=7)
    mes_ini = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    stats_sesiones = sesiones_qs.aggregate(
        total=Count('id'),
        conectadas=Count('id', filter=Q(estado='conectado')),
        pendientes=Count('id', filter=Q(estado='pendiente')),
        desconectadas=Count('id', filter=Q(estado='desconectado')),
        errores=Count('id', filter=Q(estado='error')),
        pausadas=Count('id', filter=Q(activo=False)),
    )

    sesiones_activas = list(
        sesiones_qs.filter(estado='conectado')
        .annotate(
            contactos_n=Count(
                'contacto',
                filter=Q(contacto__status=True),
                distinct=True,
            ),
            convs_abiertas=Count(
                'contacto__conversaciones',
                filter=Q(
                    contacto__conversaciones__status=True,
                    contacto__conversaciones__conversacion_finalizada=False,
                    contacto__conversaciones__estado_conversacion=0,
                    contacto__conversaciones__fecha_hora_expira__gte=ahora,
                ),
                distinct=True,
            ),
            ultima_conv=Max(
                'contacto__conversaciones__fecha_registro',
                filter=Q(contacto__conversaciones__status=True),
            ),
        )
        .order_by('-ultima_conexion', '-fecha_registro')[:8]
    )

    if sesiones_activas:
        ids_activas = [s.id for s in sesiones_activas]
        msgs_24h_por_sesion = dict(
            MensajeWhatsApp.objects
            .filter(
                conversacion__contacto__sesion_id__in=ids_activas,
                fecha__gte=hace_24h,
            )
            .values_list('conversacion__contacto__sesion_id')
            .annotate(c=Count('id'))
            .values_list('conversacion__contacto__sesion_id', 'c')
        )
        for s in sesiones_activas:
            s.msgs_24h = msgs_24h_por_sesion.get(s.id, 0)

    sesiones_atencion = list(
        sesiones_qs.filter(estado__in=['desconectado', 'error', 'pendiente'])
        .order_by('estado', '-fecha_modificacion')[:6]
    )

    contactos_total = Contacto.objects.filter(
        status=True, sesion__in=sesiones_qs,
    ).count()

    convs_abiertas_total = ConversacionWhatsApp.objects.sin_expirar.filter(
        status=True,
        contacto__status=True,
        contacto__sesion__in=sesiones_qs,
    ).count()

    convs_no_asignadas = ConversacionWhatsApp.objects.sin_expirar.filter(
        status=True,
        contacto__status=True,
        asignado_a__isnull=True,
        contacto__sesion__in=sesiones_qs,
    ).count()

    convs_mes_actual = ConversacionWhatsApp.objects.filter(
        status=True,
        contacto__sesion__in=sesiones_qs,
        fecha_registro__gte=mes_ini,
    ).count()

    mensajes_24h = MensajeWhatsApp.objects.filter(
        conversacion__contacto__sesion__in=sesiones_qs,
        fecha__gte=hace_24h,
    ).count()

    mensajes_7d = MensajeWhatsApp.objects.filter(
        conversacion__contacto__sesion__in=sesiones_qs,
        fecha__gte=hace_7d,
    ).count()

    # Citas de agenda en las próximas 24h. Superuser o permiso
    # crm.puede_ver_citas_all ven TODAS; el resto solo las de los recursos
    # que tienen asignados.
    citas_proximas = []
    try:
        from agenda.models import Turno
        if persona.is_superuser or persona.has_perm('crm.puede_ver_citas_all'):
            turnos_qs = Turno.objects.filter(status=True)
        else:
            turnos_qs = Turno.objects.filter(status=True, recurso__usuario=persona)
        citas_proximas = list(
            turnos_qs.filter(inicio__gte=ahora, inicio__lte=ahora + timedelta(hours=24))
            .exclude(estado__in=['cancelled', 'no_show'])
            .select_related('recurso', 'servicio', 'contacto')
            .order_by('inicio')[:8]
        )
    except Exception:
        citas_proximas = []
    data['citas_proximas'] = citas_proximas

    serie_7d = []
    for i in range(0, 7):
        dia_ini = (ahora - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        dia_fin = dia_ini + timedelta(days=1)
        n = MensajeWhatsApp.objects.filter(
            conversacion__contacto__sesion__in=sesiones_qs,
            fecha__gte=dia_ini, fecha__lt=dia_fin,
        ).count()
        serie_7d.append({'label': dia_ini.strftime('%a'), 'valor': n})
    pico_serie = max((d['valor'] for d in serie_7d), default=0) or 1
    for d in serie_7d:
        d['pct'] = int(100 * d['valor'] / pico_serie)

    meta_sesiones = []
    meta_config_ids = []
    for s in sesiones_qs:
        if not s.es_meta:
            continue
        cfg = getattr(s, 'config_meta', None)
        if not cfg:
            continue
        meta_sesiones.append(s)
        meta_config_ids.append(cfg.id)

    plantillas_stats = {}
    calidad_alertas = []
    if meta_config_ids:
        plantillas_stats = PlantillaWhatsApp.objects.filter(
            config_meta_id__in=meta_config_ids, status=True,
        ).aggregate(
            total=Count('id'),
            aprobadas=Count('id', filter=Q(estado_meta='APPROVED')),
            pendientes=Count('id', filter=Q(estado_meta='PENDING')),
            rechazadas=Count('id', filter=Q(estado_meta='REJECTED')),
        )
        for s in meta_sesiones:
            cfg = s.config_meta
            if cfg.quality_rating == 'RED':
                calidad_alertas.append({'sesion': s, 'nivel': 'RED'})
            elif cfg.quality_rating == 'YELLOW':
                calidad_alertas.append({'sesion': s, 'nivel': 'YELLOW'})

    data.update({
        'stats_sesiones':       stats_sesiones,
        'sesiones_activas':     sesiones_activas,
        'sesiones_atencion':    sesiones_atencion,
        'sesiones_desconectados': sesiones_qs.filter(estado='desconectado'),
        'contactos_total':      contactos_total,
        'convs_abiertas_total': convs_abiertas_total,
        'convs_no_asignadas':   convs_no_asignadas,
        'convs_mes_actual':     convs_mes_actual,
        'mensajes_24h':         mensajes_24h,
        'mensajes_7d':          mensajes_7d,
        'serie_7d':             serie_7d,
        'plantillas_stats':     plantillas_stats,
        'calidad_alertas':      calidad_alertas,
        'tiene_sesiones':       stats_sesiones.get('total', 0) > 0,
    })

    return render(request, 'seguridad/index.html', data)
