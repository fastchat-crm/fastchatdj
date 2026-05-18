"""Registry de funciones internas del flujo de agenda médica/consultorio.

Reusa la infra de `crm.funciones_chatbot` (mismo registry global) para que
los nodos `tipo_nodo='funcion'` puedan invocarlas con
`funcion_codigo='agenda_*'`. Toda la lógica vive dentro de Django (sin
HTTP outbound): los nodos hacen `llamada_funcion` en lugar de `llamada_http`
cuando los datos están en BD.

Funciones registradas:
    agenda_init             → lee depto.grupo_agenda → variables (config)
    agenda_listar_servicios → Servicio del grupo → variables.servicios
    agenda_listar_recursos  → Recursos que ofrecen el servicio → variables.recursos
    agenda_disponibilidad   → slots libres en fecha → variables.turnos_disponibles
    agenda_armar_resumen    → texto pre-confirmación → variables.resumen_texto
    agenda_registrar_turno  → crea Contacto+Turno (origen=chatbot, confirmed)

Contrato (igual que funciones_chatbot): cada fn retorna
    {etiqueta: 'ok'|'error', body: dict, status: int, error: str}
y el motor enruta con `extraer` por JSONPath sobre `body`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from django.utils import timezone

from .funciones_chatbot import registrar_funcion


logger = logging.getLogger(__name__)


_PALABRAS_SALTAR = {'-', 'saltar', 'skip', 'ninguno', 'ninguna', 'no'}


def _hoy_local():
    ahora = timezone.now()
    if timezone.is_naive(ahora):
        return ahora.date()
    return timezone.localtime(ahora).date()


def _to_int(v, default=0):
    try:
        if v in (None, ''):
            return default
        return int(v)
    except (ValueError, TypeError):
        return default


def _obtener_grupo(conversacion):
    """Resuelve el GrupoAgenda asociado al depto activo del flujo.

    El motor pasa la instancia de ConversacionWhatsApp; el depto vive en
    `conversacion.estado_flujo.departamento`. Devuelve None si no hay.
    """
    estado = getattr(conversacion, 'estado_flujo', None)
    depto = getattr(estado, 'departamento', None) if estado else None
    return getattr(depto, 'grupo_agenda', None) if depto else None


@registrar_funcion(
    codigo='agenda_init',
    descripcion='Lee depto.grupo_agenda y carga moneda/recordatorio/zona a variables.',
    parametros={},
)
def agenda_init(conversacion, variables, config, endpoint=None) -> dict:
    grupo = _obtener_grupo(conversacion)
    if not grupo or not getattr(grupo, 'status', True):
        return {
            'etiqueta': 'error', 'body': {}, 'status': 400,
            'error': 'El departamento no tiene grupo de agenda asignado.',
        }
    return {
        'etiqueta': 'ok',
        'body': {
            'grupo_agenda_id': grupo.id,
            'grupo_nombre':    grupo.nombre,
            'moneda':          grupo.moneda,
            'recordatorio_h':  grupo.recordatorio_horas_antes,
            'zona_horaria':    grupo.zona_horaria,
        },
        'status': 200, 'error': '',
    }


@registrar_funcion(
    codigo='agenda_listar_servicios',
    descripcion='Lista servicios activos del grupo en variables.servicios.',
    parametros={'grupo_agenda_id': 'int — id GrupoAgenda (de variables)'},
)
def agenda_listar_servicios(conversacion, variables, config, endpoint=None) -> dict:
    from agenda.models import Servicio
    grupo_id = _to_int(variables.get('grupo_agenda_id'))
    if not grupo_id:
        grupo = _obtener_grupo(conversacion)
        grupo_id = grupo.id if grupo else 0
    if not grupo_id:
        return {'etiqueta': 'error', 'body': {}, 'status': 400,
                'error': 'grupo_agenda_id no definido'}
    qs = (
        Servicio.objects.filter(grupo_agenda_id=grupo_id, status=True)
        .order_by('orden', 'nombre')
    )
    servicios = [
        {
            'id': s.id,
            'nombre': s.nombre,
            'duracion_min': s.duracion_min,
            'precio': str(s.precio),
            'etiqueta': s.nombre,
        }
        for s in qs
    ]
    if not servicios:
        return {'etiqueta': 'error', 'body': {'servicios': []}, 'status': 404,
                'error': 'No hay servicios activos en este grupo de agenda.'}
    return {'etiqueta': 'ok', 'body': {'servicios': servicios},
            'status': 200, 'error': ''}


_DIAS_ABREV = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']


@registrar_funcion(
    codigo='agenda_listar_dias',
    descripcion='Próximos 7 días para que el usuario elija (id=YYYY-MM-DD).',
    parametros={'dias_total': 'int — cantidad de días a mostrar (default 7)'},
)
def agenda_listar_dias(conversacion, variables, config, endpoint=None) -> dict:
    total = _to_int(variables.get('dias_total') or config.get('dias_total') or 7) or 7
    if total < 1:
        total = 7
    if total > 14:
        total = 14
    hoy = _hoy_local()
    dias = []
    for i in range(total):
        f = hoy + timedelta(days=i)
        nombre = _DIAS_ABREV[f.weekday()]
        if i == 0:
            etiqueta = f'Hoy · {nombre} {f.strftime("%d/%m")}'
        elif i == 1:
            etiqueta = f'Mañana · {nombre} {f.strftime("%d/%m")}'
        else:
            etiqueta = f'{nombre} {f.strftime("%d/%m")}'
        dias.append({'id': f.isoformat(), 'etiqueta': etiqueta})
    return {'etiqueta': 'ok', 'body': {'dias': dias},
            'status': 200, 'error': ''}


@registrar_funcion(
    codigo='agenda_listar_recursos',
    descripcion='Recursos que ofrecen el servicio. Incluye opción "cualquiera" con id=0.',
    parametros={
        'servicio_id': 'int — id Servicio elegido',
        'grupo_agenda_id': 'int — id GrupoAgenda',
    },
)
def agenda_listar_recursos(conversacion, variables, config, endpoint=None) -> dict:
    from agenda.models import Recurso, Servicio
    servicio_id = _to_int(variables.get('servicio_id'))
    if not servicio_id:
        return {'etiqueta': 'error', 'body': {}, 'status': 400,
                'error': 'servicio_id no definido'}
    try:
        servicio = Servicio.objects.get(id=servicio_id, status=True)
    except Servicio.DoesNotExist:
        return {'etiqueta': 'error', 'body': {}, 'status': 404,
                'error': 'servicio no existe'}
    candidatos = servicio.recursos.filter(status=True).order_by('orden', 'nombre')
    if not candidatos.exists():
        candidatos = Recurso.objects.filter(
            grupo_agenda_id=servicio.grupo_agenda_id, status=True,
        ).order_by('orden', 'nombre')
    recursos = [
        {'id': r.id, 'nombre': r.nombre, 'etiqueta': r.nombre}
        for r in candidatos
    ]
    if not recursos:
        return {'etiqueta': 'error', 'body': {'recursos': []}, 'status': 404,
                'error': 'No hay recursos activos para este servicio.'}
    return {'etiqueta': 'ok', 'body': {'recursos': recursos},
            'status': 200, 'error': ''}


def _generar_slots_recurso(recurso, fecha_obj, duracion_min, tz):
    """Devuelve lista de (inicio_aware, fin_aware) candidatos del día."""
    from agenda.models import HorarioLaboral, ExcepcionAgenda
    dia = fecha_obj.weekday()
    horarios = list(
        HorarioLaboral.objects.filter(
            recurso=recurso, status=True, dia_semana=dia,
        ).order_by('hora_inicio')
    )
    if not horarios:
        return []
    excepciones = list(ExcepcionAgenda.objects.filter(
        recurso=recurso, fecha=fecha_obj, status=True,
    ))
    if any(e.tipo == 'block_day' for e in excepciones):
        return []
    block_ranges = [
        (e.hora_inicio, e.hora_fin)
        for e in excepciones
        if e.tipo == 'block_range' and e.hora_inicio and e.hora_fin
    ]
    add_ranges = [
        (e.hora_inicio, e.hora_fin)
        for e in excepciones
        if e.tipo == 'add_range' and e.hora_inicio and e.hora_fin
    ]

    def en_block(hi, hf):
        for bi, bf in block_ranges:
            if not (hf <= bi or hi >= bf):
                return True
        return False

    slots = []
    bloques = [(h.hora_inicio, h.hora_fin, h.duracion_slot_min) for h in horarios]
    bloques += [(bi, bf, duracion_min) for bi, bf in add_ranges]
    for hi, hf, slot_dur in bloques:
        paso = slot_dur or duracion_min
        cursor = datetime.combine(fecha_obj, hi)
        end_dt = datetime.combine(fecha_obj, hf)
        while cursor + timedelta(minutes=duracion_min) <= end_dt:
            fin = cursor + timedelta(minutes=duracion_min)
            if not en_block(cursor.time(), fin.time()):
                slots.append((tz.localize(cursor), tz.localize(fin)))
            cursor += timedelta(minutes=paso)
    return slots


@registrar_funcion(
    codigo='agenda_disponibilidad',
    descripcion='Slots libres para fecha + recurso (0=cualquiera) + servicio.',
    parametros={
        'fecha': 'string YYYY-MM-DD',
        'recurso_id': 'int — 0 = cualquier recurso',
        'servicio_id': 'int',
        'grupo_agenda_id': 'int',
        'zona_horaria': 'string TZ name',
    },
)
def agenda_disponibilidad(conversacion, variables, config, endpoint=None) -> dict:
    from agenda.models import Recurso, Servicio, Turno
    grupo_id = _to_int(variables.get('grupo_agenda_id'))
    servicio_id = _to_int(variables.get('servicio_id'))
    recurso_id = _to_int(variables.get('recurso_id'))
    fecha_str = (variables.get('fecha') or '').strip()
    zona = variables.get('zona_horaria') or 'America/Guayaquil'
    if not (grupo_id and servicio_id and fecha_str):
        return {'etiqueta': 'error', 'body': {}, 'status': 400,
                'error': 'faltan datos (grupo/servicio/fecha)'}
    try:
        fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        return {'etiqueta': 'error', 'body': {}, 'status': 400,
                'error': 'formato fecha inválido (YYYY-MM-DD)'}
    hoy = _hoy_local()
    if fecha_obj < hoy:
        return {'etiqueta': 'ok', 'body': {'turnos_disponibles': []},
                'status': 200, 'error': ''}
    try:
        tz = pytz.timezone(zona)
    except Exception:
        tz = timezone.get_current_timezone()
    try:
        servicio = Servicio.objects.get(id=servicio_id, status=True)
    except Servicio.DoesNotExist:
        return {'etiqueta': 'error', 'body': {}, 'status': 404,
                'error': 'servicio no existe'}

    if recurso_id:
        recursos = list(
            Recurso.objects.filter(
                id=recurso_id, grupo_agenda_id=grupo_id, status=True,
            )
        )
    else:
        candidatos = servicio.recursos.filter(status=True)
        if not candidatos.exists():
            candidatos = Recurso.objects.filter(
                grupo_agenda_id=grupo_id, status=True,
            )
        recursos = list(candidatos.order_by('orden', 'nombre'))

    duracion = servicio.duracion_min
    ahora = timezone.now()
    todos = []
    for r in recursos:
        slots = _generar_slots_recurso(r, fecha_obj, duracion, tz)
        if not slots:
            continue
        rango_ini = slots[0][0]
        rango_fin = slots[-1][1]
        ocupados = list(Turno.objects.filter(
            recurso=r,
            estado__in=('pending', 'confirmed'),
            status=True,
            inicio__lt=rango_fin,
            fin__gt=rango_ini,
        ).values_list('inicio', 'fin'))
        for ini, fin in slots:
            if ini <= ahora:
                continue
            choque = any(not (fin <= oi or ini >= of) for oi, of in ocupados)
            if choque:
                continue
            etiqueta = (
                f'{ini.strftime("%H:%M")} · {r.nombre}'
                if not recurso_id else ini.strftime('%H:%M')
            )
            todos.append({
                'id': f'{r.id}|{ini.isoformat()}',
                'recurso_id': r.id,
                'recurso_nombre': r.nombre,
                'inicio_iso': ini.isoformat(),
                'fin_iso': fin.isoformat(),
                'etiqueta': etiqueta,
            })
    todos.sort(key=lambda s: s['inicio_iso'])
    return {'etiqueta': 'ok', 'body': {'turnos_disponibles': todos[:30]},
            'status': 200, 'error': ''}


@registrar_funcion(
    codigo='agenda_armar_resumen',
    descripcion='Formatea resumen pre-confirmación. Precio solo si servicio.precio > 0.',
    parametros={
        'servicio_id': 'int',
        'slot_seleccionado': 'string "recurso_id|iso"',
        'motivo': 'string opcional',
    },
)
def agenda_armar_resumen(conversacion, variables, config, endpoint=None) -> dict:
    from agenda.models import Servicio, Recurso
    servicio_id = _to_int(variables.get('servicio_id'))
    slot_id = (variables.get('slot_seleccionado') or '').strip()
    motivo = (variables.get('motivo') or '').strip()
    if motivo.lower() in _PALABRAS_SALTAR:
        motivo = ''
    if not (servicio_id and slot_id and '|' in slot_id):
        return {'etiqueta': 'error', 'body': {}, 'status': 400,
                'error': 'datos incompletos para armar resumen'}
    recurso_str, iso = slot_id.split('|', 1)
    recurso_id = _to_int(recurso_str)
    try:
        servicio = Servicio.objects.get(id=servicio_id, status=True)
        recurso = Recurso.objects.get(id=recurso_id, status=True)
    except (Servicio.DoesNotExist, Recurso.DoesNotExist):
        return {'etiqueta': 'error', 'body': {}, 'status': 404,
                'error': 'servicio/recurso no encontrado'}
    try:
        inicio = datetime.fromisoformat(iso)
    except ValueError:
        return {'etiqueta': 'error', 'body': {}, 'status': 400,
                'error': 'fecha slot inválida'}
    moneda = variables.get('moneda') or servicio.grupo_agenda.moneda
    fecha_fmt = inicio.strftime('%d/%m/%Y · %H:%M')
    lineas = [
        '📋 *Resumen del turno:*',
        f'• Servicio: *{servicio.nombre}*',
        f'• Médico: *{recurso.nombre}*',
        f'• Fecha y hora: *{fecha_fmt}*',
        f'• Duración: {servicio.duracion_min} min',
    ]
    try:
        precio = Decimal(servicio.precio)
    except Exception:
        precio = Decimal('0')
    if precio > 0:
        lineas.append(f'• Precio: *{precio} {moneda}*')
    if motivo:
        lineas.append(f'• Motivo: {motivo}')
    return {
        'etiqueta': 'ok',
        'body': {
            'resumen_texto': '\n'.join(lineas),
            'turno_inicio_iso': iso,
            'turno_recurso_id': recurso_id,
            'motivo_limpio': motivo,
        },
        'status': 200, 'error': '',
    }


@registrar_funcion(
    codigo='agenda_registrar_turno',
    descripcion='Crea/actualiza Contacto + crea Turno (origen=chatbot, estado=confirmed).',
    parametros={
        'servicio_id': 'int',
        'turno_recurso_id': 'int',
        'turno_inicio_iso': 'string ISO',
        'motivo_limpio': 'string opcional',
        'cedula': 'string',
        'nombres': 'string',
        'apellidos': 'string',
        'email': 'string',
        'driver_age': 'string|int — edad',
    },
)
def agenda_registrar_turno(conversacion, variables, config, endpoint=None) -> dict:
    from agenda.models import Servicio, Recurso, Turno
    servicio_id = _to_int(variables.get('servicio_id'))
    recurso_id = _to_int(variables.get('turno_recurso_id'))
    iso = (variables.get('turno_inicio_iso') or '').strip()
    if not (servicio_id and recurso_id and iso):
        return {'etiqueta': 'error', 'body': {}, 'status': 400,
                'error': 'datos del turno incompletos'}
    try:
        servicio = Servicio.objects.get(id=servicio_id, status=True)
        recurso = Recurso.objects.get(id=recurso_id, status=True)
        inicio = datetime.fromisoformat(iso)
    except (Servicio.DoesNotExist, Recurso.DoesNotExist, ValueError):
        return {'etiqueta': 'error', 'body': {}, 'status': 404,
                'error': 'servicio/recurso/fecha inválidos'}

    contacto = getattr(conversacion, 'contacto', None)
    if not contacto:
        return {'etiqueta': 'error', 'body': {}, 'status': 400,
                'error': 'conversación sin contacto asociado'}

    nombres = (variables.get('nombres') or '').strip()
    apellidos = (variables.get('apellidos') or '').strip()
    nombre_full = (f'{nombres} {apellidos}').strip()
    if nombre_full and not (contacto.contacto_nombre or '').strip():
        contacto.contacto_nombre = nombre_full[:255]
        contacto.save()

    fin = inicio + timedelta(minutes=servicio.duracion_min)
    notas_lineas = []
    motivo = (variables.get('motivo_limpio') or '').strip()
    if motivo:
        notas_lineas.append(f'Motivo: {motivo}')
    if variables.get('cedula'):
        notas_lineas.append(f'Cédula: {variables["cedula"]}')
    if variables.get('email'):
        notas_lineas.append(f'Email: {variables["email"]}')
    if variables.get('driver_age'):
        notas_lineas.append(f'Edad: {variables["driver_age"]}')

    nuevo = Turno(
        recurso=recurso,
        servicio=servicio,
        contacto=contacto,
        inicio=inicio,
        fin=fin,
        precio_cobrado=servicio.precio,
        estado='confirmed',
        origen='chatbot',
        conversacion=conversacion,
        notas='\n'.join(notas_lineas)[:4000],
    )
    if nuevo.overlaps_existing():
        return {'etiqueta': 'error', 'body': {}, 'status': 409,
                'error': 'El slot fue tomado mientras confirmabas. Probá otra hora.'}
    try:
        nuevo.save()
    except Exception as e:
        logger.exception('Error guardando Turno: %s', e)
        return {'etiqueta': 'error', 'body': {}, 'status': 500,
                'error': f'No se pudo guardar el turno: {e}'}

    fecha_fmt = inicio.strftime('%d/%m/%Y · %H:%M')
    return {
        'etiqueta': 'ok',
        'body': {
            'turno_id': nuevo.id,
            'turno_fecha_fmt': fecha_fmt,
            'medico_nombre': recurso.nombre,
            'servicio_nombre': servicio.nombre,
        },
        'status': 200, 'error': '',
    }
