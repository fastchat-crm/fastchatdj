"""Registry de funciones internas para persistir Clientes desde flujos chatbot.

Funciones:
    cliente_upsert → get_or_create Cliente por cédula. En el create captura el
                     origen (contacto/conversación/sesión/departamento). En el
                     update refresca campos no vacíos y `fecha_ultima_interaccion`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.utils import timezone

from .funciones_chatbot import registrar_funcion


logger = logging.getLogger(__name__)


def _str(v) -> str:
    if v is None:
        return ''
    return str(v).strip()


def _to_int(v, default=None):
    try:
        if v in (None, ''):
            return default
        return int(v)
    except (ValueError, TypeError):
        return default


def _parse_fecha_nac(v):
    s = _str(v)
    if not s:
        return None
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _resolver_origen(conversacion):
    contacto = getattr(conversacion, 'contacto', None) if conversacion else None
    sesion = getattr(conversacion, 'sesion', None) if conversacion else None
    estado = getattr(conversacion, 'estado_flujo', None) if conversacion else None
    depto = getattr(estado, 'departamento', None) if estado else None
    return contacto, sesion, depto


@registrar_funcion(
    codigo='cliente_upsert',
    descripcion='Crea/actualiza Cliente local (cédula UK) y registra el contacto/conversación de origen.',
    parametros={
        'cedula':            'string requerido · cédula/identificación',
        'nombres':           'string',
        'apellidos':         'string',
        'email':             'string',
        'telefono':          'string · opcional, si vacío usa contacto.numero',
        'edad':              'int',
        'fecha_nacimiento':  'string YYYY-MM-DD | DD/MM/YYYY (opcional)',
        'sexo':              'M | F',
        'canal_origen':      'string · default "chatbot"',
        'notas':             'string opcional',
    },
)
def cliente_upsert(conversacion, variables, config, endpoint=None) -> dict:
    from .models import Cliente

    cedula = _str(variables.get('cedula'))
    if not cedula:
        return {'etiqueta': 'error', 'body': {}, 'status': 400,
                'error': 'cedula requerida para crear/actualizar cliente'}

    contacto, sesion, depto = _resolver_origen(conversacion)

    nombres = _str(variables.get('nombres'))
    apellidos = _str(variables.get('apellidos'))
    email = _str(variables.get('email'))
    telefono = _str(variables.get('telefono'))
    if not telefono and contacto is not None:
        telefono = (
            _str(getattr(contacto, 'numero_telefono', ''))
            or _str(getattr(contacto, 'contacto_numero', ''))
        )
    edad = _to_int(variables.get('edad') or variables.get('driver_age'))
    fecha_nac = _parse_fecha_nac(variables.get('fecha_nacimiento'))
    if not fecha_nac and edad is not None and edad >= 0:
        hoy = timezone.now().date()
        try:
            fecha_nac = hoy.replace(year=hoy.year - int(edad))
        except ValueError:
            fecha_nac = hoy - timedelta(days=int(edad) * 365)
    sexo = _str(variables.get('sexo')).upper()
    if sexo not in ('M', 'F'):
        sexo = ''
    canal = _str(variables.get('canal_origen') or config.get('canal_origen') or 'chatbot')
    notas = _str(variables.get('notas'))

    ahora = timezone.now()

    cliente, creado = Cliente.objects.get_or_create(
        cedula=cedula,
        defaults={
            'nombres': nombres,
            'apellidos': apellidos,
            'email': email,
            'telefono': telefono,
            'edad': edad,
            'fecha_nacimiento': fecha_nac,
            'sexo': sexo,
            'notas': notas,
            'canal_origen': canal,
            'contacto_origen': contacto,
            'conversacion_origen': conversacion,
            'sesion_origen': sesion,
            'departamento_origen': depto,
            'fecha_ultima_interaccion': ahora,
        },
    )

    if not creado:
        cambios = []
        for campo, nuevo in (
            ('nombres', nombres), ('apellidos', apellidos),
            ('email', email), ('telefono', telefono),
            ('sexo', sexo), ('notas', notas),
        ):
            if nuevo and nuevo != getattr(cliente, campo, ''):
                setattr(cliente, campo, nuevo)
                cambios.append(campo)
        if edad is not None and edad != cliente.edad:
            cliente.edad = edad
            cambios.append('edad')
        if fecha_nac and fecha_nac != cliente.fecha_nacimiento:
            cliente.fecha_nacimiento = fecha_nac
            cambios.append('fecha_nacimiento')
        cliente.fecha_ultima_interaccion = ahora
        cambios.append('fecha_ultima_interaccion')
        try:
            cliente.save(update_fields=cambios)
        except Exception as ex:
            logger.exception('Error actualizando Cliente %s: %s', cedula, ex)
            return {'etiqueta': 'error', 'body': {}, 'status': 500,
                    'error': f'no se pudo actualizar cliente: {ex}'}

    nombre_full = f'{cliente.nombres} {cliente.apellidos}'.strip()
    return {
        'etiqueta': 'ok',
        'body': {
            'cliente_id': cliente.id,
            'cliente_creado': creado,
            'cliente_nombre': nombre_full or cliente.cedula,
            'contacto_origen_id': contacto.id if contacto else None,
            'departamento_origen_id': depto.id if depto else None,
        },
        'status': 200, 'error': '',
    }
