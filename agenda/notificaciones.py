import logging

from django.conf import settings

from core.email_config import send_html_mail
from core.funciones import encrypt_sesion_id
from core.notificacion_config import enviar_not_push


logger = logging.getLogger(__name__)


def _build_urls(turno):
    base = getattr(settings, 'URL_GENERAL', '').rstrip('/')
    token = encrypt_sesion_id(turno.id)
    path_modulo = '/agenda/citas/'
    path_detalle = f'{path_modulo}?cita={token}'
    return {
        'path_modulo': path_modulo,
        'path_detalle': path_detalle,
        'url_modulo': f'{base}{path_modulo}',
        'url_detalle': f'{base}{path_detalle}',
    }


def notificar_turno_creado(turno, request=None):
    grupo = getattr(turno.recurso, 'grupo_agenda', None)
    responsable = getattr(grupo, 'responsable', None) if grupo else None
    if not responsable:
        return False

    urls = _build_urls(turno)
    contacto = turno.contacto
    contacto_nombre = (contacto.contacto_nombre or '').strip() or contacto.contacto_numero
    titulo = f'🩺 Nueva cita #{turno.id} — {turno.servicio.nombre}'
    cuerpo = (
        f'Grupo "{grupo.nombre}". Recurso: {turno.recurso.nombre}. '
        f'Servicio: {turno.servicio.nombre}. '
        f'Cuándo: {turno.inicio:%d/%m/%Y %H:%M}. '
        f'Contacto: {contacto_nombre}.'
    )

    try:
        from seguridad.models import Notificacion
        Notificacion.objects.create(
            titulo=titulo[:300],
            cuerpo=cuerpo,
            destinatario=responsable,
            url=urls['path_detalle'],
            tipo=3,
            prioridad=2,
        )
    except Exception:
        logger.exception('No se pudo crear Notificacion para turno %s', turno.id)

    try:
        enviar_not_push(responsable, titulo, cuerpo, urls['path_detalle'], request=request)
    except Exception:
        logger.exception('Push falló para turno %s', turno.id)

    email = (responsable.email or '').strip()
    if email:
        datos = {
            'turno': turno,
            'grupo': grupo,
            'responsable': responsable,
            'contacto_nombre': contacto_nombre,
            'contacto_numero': contacto.contacto_numero,
            'fecha_fmt': turno.inicio.strftime('%d/%m/%Y %H:%M'),
            'url_modulo': urls['url_modulo'],
            'url_detalle': urls['url_detalle'],
            'notas': turno.notas or '',
        }
        try:
            send_html_mail(
                f'Nueva cita reservada #{turno.id} — {grupo.nombre}',
                'email/agenda_turno_responsable.html',
                datos, [email], [],
            )
        except Exception:
            logger.exception('Email turno %s falló', turno.id)
    return True


def notificar_turno_cliente(turno, email, cliente_nombre='', motivo='', moneda='', recordatorio_h=24):
    email = (email or '').strip()
    if not email:
        return False
    try:
        from decimal import Decimal
        from seguridad.models import Configuracion
        servicio = turno.servicio
        recurso = turno.recurso
        try:
            precio = Decimal(servicio.precio)
        except Exception:
            precio = Decimal('0')
        grupo = getattr(recurso, 'grupo_agenda', None)
        moneda_eff = moneda or getattr(grupo, 'moneda', '') or ''
        precio_str = f'{precio} {moneda_eff}' if precio > 0 else ''
        confi = Configuracion.get_instancia()
        nombreempresa = getattr(confi, 'nombre_empresa', '') or 'Care team'
        fecha_fmt = turno.inicio.strftime('%d/%m/%Y · %H:%M')
        datos = {
            'turno_id': turno.id,
            'cliente_nombre': (cliente_nombre or '').strip() or 'there',
            'servicio_nombre': servicio.nombre,
            'medico_nombre': recurso.nombre,
            'fecha_fmt': fecha_fmt,
            'duracion_min': servicio.duracion_min,
            'precio_str': precio_str,
            'motivo': (motivo or '').strip(),
            'recordatorio_h': recordatorio_h or 24,
            'nombreempresa': nombreempresa,
        }
        send_html_mail(
            f'Appointment confirmed · {fecha_fmt}',
            'agenda/email_confirmacion_turno.html',
            datos, [email], [],
        )
        return True
    except Exception:
        logger.exception('Email confirmación cliente falló (turno %s)', getattr(turno, 'id', '?'))
        return False
