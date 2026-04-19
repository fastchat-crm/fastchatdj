"""Cron que ejecuta campañas: arma la audiencia, respeta throttle y envía.

Se diseña para correr cada minuto. En cada tick:
  1. Toma campañas en estado 'programada' cuya fecha_inicio <= ahora, las
     marca 'enviando' y arma sus EnvioCampana a partir de la audiencia.
  2. Para cada campaña en estado 'enviando', envía hasta
     `throttle_por_minuto` mensajes pendientes en esta ronda.
  3. Cuando ya no hay pendientes, marca la campaña 'completada'.

Los envíos se registran individualmente en EnvioCampana para trazabilidad.
"""
import os, sys
from datetime import datetime

from django.core.wsgi import get_wsgi_application

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')
application = get_wsgi_application()

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.funciones import logCron
from whatsapp.models import Campana, EnvioCampana, Contacto, MensajeWhatsAppProgramado
from whatsapp.services import get_whatsapp_service


def _construir_audiencia(campana: Campana):
    """Calcula el queryset de contactos objetivo según filtros de la campaña."""
    qs = Contacto.objects.filter(sesion=campana.sesion, status=True)
    canales = campana.canales or []
    if canales:
        qs = qs.filter(canal__in=canales)
    tags_in = list(campana.etiquetas_incluir.values_list('id', flat=True))
    tags_out = list(campana.etiquetas_excluir.values_list('id', flat=True))
    if tags_in:
        qs = qs.filter(etiquetas__in=tags_in)
    if tags_out:
        qs = qs.exclude(etiquetas__in=tags_out)
    return qs.distinct()


def _materializar_envios(campana: Campana) -> int:
    audiencia = _construir_audiencia(campana)
    creados = 0
    for contacto in audiencia:
        _, created = EnvioCampana.objects.get_or_create(
            campana=campana, contacto=contacto,
            defaults={'estado': 'pendiente'},
        )
        if created:
            creados += 1
    campana.total_objetivo = campana.envios.count()
    campana.save(update_fields=['total_objetivo'])
    return creados


def _render_mensaje(campana: Campana, contacto: Contacto) -> str:
    """Sustituye {nombre} / {numero} en mensaje_texto."""
    texto = campana.mensaje_texto or ''
    return (
        texto
        .replace('{nombre}', contacto.contacto_nombre or '')
        .replace('{numero}', contacto.numero_telefono or contacto.contacto_numero or '')
    )


def _despachar_campana(campana: Campana):
    ahora = timezone.now()
    # Respetar ventana horaria si está configurada
    if campana.ventana_inicio and campana.ventana_fin:
        hora = ahora.time()
        if not (campana.ventana_inicio <= hora <= campana.ventana_fin):
            return 0

    pendientes = (
        EnvioCampana.objects
        .filter(campana=campana, estado='pendiente', status=True)
        .select_related('contacto', 'contacto__sesion')
        [:campana.throttle_por_minuto]
    )

    service = get_whatsapp_service(campana.sesion)
    enviados_now = 0
    for envio in pendientes:
        envio.estado = 'enviando'
        envio.intentos += 1
        envio.save(update_fields=['estado', 'intentos'])
        try:
            texto_final = _render_mensaje(campana, envio.contacto)
            destino = envio.contacto.from_number or envio.contacto.contacto_numero
            if campana.tipo == 'plantilla' and campana.plantilla:
                # Meta: usa plantilla aprobada
                params_cuerpo = []
                for clave, campo in (campana.plantilla_variables or {}).items():
                    params_cuerpo.append(getattr(envio.contacto, campo, '') or clave)
                res = service.send_template(
                    campana.sesion.session_id, destino,
                    campana.plantilla.nombre, campana.plantilla.idioma,
                    parametros_cuerpo=params_cuerpo,
                )
            else:
                res = service.send_text_message(
                    campana.sesion.session_id, destino, texto_final,
                    simularEscritura=False,
                )
            if res.get('success'):
                envio.estado = 'enviado'
                envio.mensaje_enviado = texto_final
                envio.mensaje_id_externo = res.get('message_id') or ''
                envio.fecha_envio = timezone.now()
                envio.save(update_fields=[
                    'estado', 'mensaje_enviado', 'mensaje_id_externo', 'fecha_envio',
                ])
                enviados_now += 1
                campana.total_enviados = (campana.total_enviados or 0) + 1
            else:
                envio.estado = 'fallido'
                envio.error = str(res.get('error') or 'desconocido')[:2000]
                envio.save(update_fields=['estado', 'error'])
                campana.total_fallidos = (campana.total_fallidos or 0) + 1
        except Exception as e:
            envio.estado = 'fallido'
            envio.error = str(e)[:2000]
            envio.save(update_fields=['estado', 'error'])
            campana.total_fallidos = (campana.total_fallidos or 0) + 1

    campana.save(update_fields=['total_enviados', 'total_fallidos'])

    # Marcar completada si ya no quedan pendientes
    restantes = EnvioCampana.objects.filter(
        campana=campana, estado__in=('pendiente', 'enviando'), status=True
    ).count()
    if restantes == 0:
        campana.estado = 'completada'
        campana.fecha_fin_real = timezone.now()
        campana.save(update_fields=['estado', 'fecha_fin_real'])

    return enviados_now


def main():
    ahora = timezone.now()

    # 1. Arrancar campañas que ya tocaba correr
    por_arrancar = Campana.objects.filter(
        status=True,
        estado='programada',
    ).filter(
        Q(programada_para__isnull=True) | Q(programada_para__lte=ahora),
    )
    for campana in por_arrancar:
        with transaction.atomic():
            campana.estado = 'enviando'
            campana.fecha_inicio_real = ahora
            campana.save(update_fields=['estado', 'fecha_inicio_real'])
            creados = _materializar_envios(campana)
            logCron('Campañas', f'Arrancada {campana.id} "{campana.nombre}" con {creados} envíos.', True)

    # 2. Despachar campañas en progreso
    en_progreso = Campana.objects.filter(status=True, estado='enviando')
    total = 0
    for campana in en_progreso:
        try:
            total += _despachar_campana(campana)
        except Exception as e:
            campana.estado = 'error'
            campana.error_detalle = str(e)[:4000]
            campana.save(update_fields=['estado', 'error_detalle'])
            logCron('Campañas', f'Error despachando campaña {campana.id}: {e}', False)

    if total:
        logCron('Campañas', f'Enviados {total} mensajes de campañas en esta ronda.', True)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logCron('Campañas', f'Error fatal cron campañas: {e}', False)
        print(f'Error: {e}')
