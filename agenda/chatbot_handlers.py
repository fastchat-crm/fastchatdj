from datetime import datetime, timedelta

from django.utils import timezone

from .helpers import calcular_slots_disponibles, listar_turnos_futuros_contacto
from .models import Recurso, Servicio, Turno


CANCEL_KEYWORDS = ('cancel', 'cancelar', 'salir', 'cancelar reserva', 'exit')


def procesar_nodo_turno(motor, nodo, consumir_mensaje):
    cfg = nodo.config or {}
    sub_action = (cfg.get('sub_action') or 'reservar').strip().lower()
    sesion = motor.session
    contacto = motor.contacto
    estado = motor.estado
    vars_ctx = dict(estado.variables or {})
    texto = (motor.texto or '').strip()

    if not getattr(sesion, 'grupo_agenda', None):
        motor.enviar('Disculpá, esta sesión no tiene una agenda configurada.')
        return ''

    grupo = sesion.grupo_agenda

    if consumir_mensaje and texto.lower() in CANCEL_KEYWORDS:
        _limpiar_vars(estado)
        motor.enviar('Reserva cancelada. ¿Necesitás algo más?')
        return 'cancelado'

    if sub_action == 'reservar':
        return _flow_reservar(motor, grupo, contacto, texto, consumir_mensaje, vars_ctx)
    if sub_action == 'cancelar':
        return _flow_cancelar(motor, grupo, contacto, texto, consumir_mensaje, vars_ctx)
    if sub_action == 'reagendar':
        return _flow_reagendar(motor, grupo, contacto, texto, consumir_mensaje, vars_ctx)

    motor.enviar('Acción de agenda no reconocida.')
    return ''


def _limpiar_vars(estado):
    keys = [k for k in (estado.variables or {}).keys() if k.startswith('agenda_')]
    for k in keys:
        estado.variables.pop(k, None)
    estado.save()


def _set_var(estado, nombre, valor):
    estado.set_variable(nombre, valor)
    estado.save()


def _parse_indice(texto, max_n):
    try:
        n = int(texto.strip())
        if 1 <= n <= max_n:
            return n - 1
    except (ValueError, AttributeError):
        pass
    return None


def _parse_fecha(texto):
    t = (texto or '').strip().lower()
    today = timezone.localdate()
    if t in ('hoy', 'today'):
        return today
    if t in ('mañana', 'manana', 'tomorrow'):
        return today + timedelta(days=1)
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def _flow_reservar(motor, grupo, contacto, texto, consumir, vars_ctx):
    estado = motor.estado
    step = int(vars_ctx.get('agenda_step') or 0)

    if step == 0:
        servicios = list(grupo.servicios.filter(status=True).order_by('orden', 'nombre'))
        if not servicios:
            motor.enviar('No hay servicios disponibles en este momento.')
            return ''
        lines = ['*Elegí un servicio* (respondé con el número):']
        for i, s in enumerate(servicios, 1):
            lines.append(f'{i}. {s.nombre} — {s.precio} {grupo.moneda} · {s.duracion_min} min')
        lines.append('\nEscribí *cancelar* en cualquier momento para abortar.')
        motor.enviar('\n'.join(lines))
        _set_var(estado, 'agenda_step', 1)
        _set_var(estado, 'agenda_servicios', [s.id for s in servicios])
        return None

    if step == 1:
        if not consumir:
            return None
        ids = vars_ctx.get('agenda_servicios') or []
        idx = _parse_indice(texto, len(ids))
        if idx is None:
            motor.enviar(f'Respondé con un número entre 1 y {len(ids)}.')
            return None
        servicio = Servicio.objects.filter(pk=ids[idx], status=True).first()
        if not servicio:
            motor.enviar('Ese servicio ya no está disponible.')
            return None
        recursos = list(servicio.recursos.filter(status=True).order_by('orden', 'nombre'))
        if not recursos:
            motor.enviar('Ningún recurso puede ofrecer ese servicio. Probá con otro.')
            return None
        _set_var(estado, 'agenda_servicio_id', servicio.id)
        _set_var(estado, 'agenda_recursos', [r.id for r in recursos])
        lines = [f'*{servicio.nombre}* seleccionado.\n*Elegí un recurso*:']
        for i, r in enumerate(recursos, 1):
            lines.append(f'{i}. {r.nombre}')
        motor.enviar('\n'.join(lines))
        _set_var(estado, 'agenda_step', 2)
        return None

    if step == 2:
        if not consumir:
            return None
        ids = vars_ctx.get('agenda_recursos') or []
        idx = _parse_indice(texto, len(ids))
        if idx is None:
            motor.enviar(f'Respondé con un número entre 1 y {len(ids)}.')
            return None
        recurso = Recurso.objects.filter(pk=ids[idx], status=True).first()
        if not recurso:
            motor.enviar('Ese recurso ya no está disponible.')
            return None
        _set_var(estado, 'agenda_recurso_id', recurso.id)
        motor.enviar(
            f'*{recurso.nombre}* seleccionado.\n¿Para qué día? '
            f'Respondé *hoy*, *mañana* o una fecha tipo *YYYY-MM-DD*.'
        )
        _set_var(estado, 'agenda_step', 3)
        return None

    if step == 3:
        if not consumir:
            return None
        fecha = _parse_fecha(texto)
        if not fecha:
            motor.enviar('No reconocí la fecha. Probá con *hoy*, *mañana* o *YYYY-MM-DD*.')
            return None
        if fecha < timezone.localdate():
            motor.enviar('Esa fecha ya pasó. Elegí una fecha futura.')
            return None
        recurso = Recurso.objects.filter(pk=vars_ctx.get('agenda_recurso_id'), status=True).first()
        servicio = Servicio.objects.filter(pk=vars_ctx.get('agenda_servicio_id'), status=True).first()
        if not recurso or not servicio:
            motor.enviar('La sesión de reserva expiró. Empezá de nuevo, por favor.')
            _limpiar_vars(estado)
            return ''
        slots = calcular_slots_disponibles(recurso, fecha, servicio)
        if not slots:
            motor.enviar(
                f'No hay horarios disponibles el {fecha.strftime("%Y-%m-%d")}. '
                f'Probá con otra fecha.'
            )
            return None
        slots = slots[:10]
        lines = [f'*Horarios disponibles el {fecha.strftime("%Y-%m-%d")}* (respondé con el número):']
        for i, (ini, _fin) in enumerate(slots, 1):
            lines.append(f'{i}. {ini.strftime("%H:%M")}')
        motor.enviar('\n'.join(lines))
        _set_var(estado, 'agenda_fecha', fecha.isoformat())
        _set_var(estado, 'agenda_slots', [
            (ini.isoformat(), fin.isoformat()) for ini, fin in slots
        ])
        _set_var(estado, 'agenda_step', 4)
        return None

    if step == 4:
        if not consumir:
            return None
        slots = vars_ctx.get('agenda_slots') or []
        idx = _parse_indice(texto, len(slots))
        if idx is None:
            motor.enviar(f'Respondé con un número entre 1 y {len(slots)}.')
            return None
        ini_iso, fin_iso = slots[idx]
        servicio = Servicio.objects.filter(pk=vars_ctx.get('agenda_servicio_id'), status=True).first()
        recurso = Recurso.objects.filter(pk=vars_ctx.get('agenda_recurso_id'), status=True).first()
        if not servicio or not recurso:
            motor.enviar('La sesión de reserva expiró. Empezá de nuevo, por favor.')
            _limpiar_vars(estado)
            return ''
        ini_dt = datetime.fromisoformat(ini_iso)
        motor.enviar(
            f'*Por favor confirmá:*\n'
            f'• Servicio: {servicio.nombre}\n'
            f'• Recurso: {recurso.nombre}\n'
            f'• Cuándo: {ini_dt.strftime("%Y-%m-%d %H:%M")}\n'
            f'• Precio: {servicio.precio} {servicio.grupo_agenda.moneda}\n\n'
            f'Respondé *si* para confirmar o *no* para cancelar.'
        )
        _set_var(estado, 'agenda_slot_inicio', ini_iso)
        _set_var(estado, 'agenda_slot_fin', fin_iso)
        _set_var(estado, 'agenda_step', 5)
        return None

    if step == 5:
        if not consumir:
            return None
        respuesta = texto.lower()
        if respuesta in ('no', 'n', 'cancel', 'cancelar'):
            _limpiar_vars(estado)
            motor.enviar('Reserva cancelada.')
            return 'cancelado'
        if respuesta not in ('si', 'sí', 's', 'yes', 'y'):
            motor.enviar('Respondé *si* para confirmar o *no* para cancelar.')
            return None
        servicio = Servicio.objects.filter(pk=vars_ctx.get('agenda_servicio_id'), status=True).first()
        recurso = Recurso.objects.filter(pk=vars_ctx.get('agenda_recurso_id'), status=True).first()
        ini_dt = datetime.fromisoformat(vars_ctx.get('agenda_slot_inicio'))
        fin_dt = datetime.fromisoformat(vars_ctx.get('agenda_slot_fin'))
        if not servicio or not recurso:
            motor.enviar('La sesión de reserva expiró. Empezá de nuevo, por favor.')
            _limpiar_vars(estado)
            return ''
        turno = Turno(
            recurso=recurso, servicio=servicio, contacto=contacto,
            inicio=ini_dt, fin=fin_dt,
            precio_cobrado=servicio.precio,
            estado='confirmed', origen='chatbot',
            conversacion=motor.conversation,
        )
        if turno.overlaps_existing():
            motor.enviar('Justo se ocupó ese horario. Elegí otro, por favor.')
            _set_var(estado, 'agenda_step', 3)
            return None
        turno.save(request=None)
        _limpiar_vars(estado)
        motor.enviar(
            f'✅ Turno confirmado.\n'
            f'{servicio.nombre} con {recurso.nombre}\n'
            f'{ini_dt.strftime("%Y-%m-%d %H:%M")}.\n'
            f'¡Te esperamos!'
        )
        return ''

    _limpiar_vars(estado)
    return ''


def _flow_cancelar(motor, grupo, contacto, texto, consumir, vars_ctx):
    estado = motor.estado
    step = int(vars_ctx.get('agenda_step') or 0)

    if step == 0:
        turnos = list(listar_turnos_futuros_contacto(contacto, limite=10))
        turnos = [t for t in turnos if t.recurso.grupo_agenda_id == grupo.id]
        if not turnos:
            motor.enviar('No tenés turnos próximos para cancelar.')
            return ''
        lines = ['*Tus turnos próximos* (respondé con el número que querés cancelar):']
        for i, t in enumerate(turnos, 1):
            lines.append(
                f'{i}. {t.inicio.strftime("%Y-%m-%d %H:%M")} — '
                f'{t.servicio.nombre} con {t.recurso.nombre}'
            )
        motor.enviar('\n'.join(lines))
        _set_var(estado, 'agenda_step', 1)
        _set_var(estado, 'agenda_turnos', [t.id for t in turnos])
        return None

    if step == 1:
        if not consumir:
            return None
        ids = vars_ctx.get('agenda_turnos') or []
        idx = _parse_indice(texto, len(ids))
        if idx is None:
            motor.enviar(f'Respondé con un número entre 1 y {len(ids)}.')
            return None
        turno = Turno.objects.filter(pk=ids[idx], status=True).first()
        if not turno:
            motor.enviar('Ese turno no está disponible.')
            return None
        _set_var(estado, 'agenda_turno_id', turno.id)
        motor.enviar(
            f'¿Cancelar el turno del {turno.inicio.strftime("%Y-%m-%d %H:%M")} '
            f'({turno.servicio.nombre})? Respondé *si* o *no*.'
        )
        _set_var(estado, 'agenda_step', 2)
        return None

    if step == 2:
        if not consumir:
            return None
        if texto.lower() in ('no', 'n'):
            _limpiar_vars(estado)
            motor.enviar('Listo, lo dejamos como está.')
            return ''
        if texto.lower() not in ('si', 'sí', 's', 'yes', 'y'):
            motor.enviar('Respondé *si* o *no*.')
            return None
        turno = Turno.objects.filter(pk=vars_ctx.get('agenda_turno_id'), status=True).first()
        if not turno:
            _limpiar_vars(estado)
            motor.enviar('El turno ya no existe.')
            return ''
        turno.estado = 'cancelled'
        turno.save(request=None)
        _limpiar_vars(estado)
        motor.enviar('✅ Turno cancelado.')
        return ''

    _limpiar_vars(estado)
    return ''


def _flow_reagendar(motor, grupo, contacto, texto, consumir, vars_ctx):
    estado = motor.estado
    step = int(vars_ctx.get('agenda_step') or 0)

    if step == 0:
        turnos = list(listar_turnos_futuros_contacto(contacto, limite=10))
        turnos = [t for t in turnos if t.recurso.grupo_agenda_id == grupo.id]
        if not turnos:
            motor.enviar('No tenés turnos próximos para reagendar.')
            return ''
        lines = ['*Tus turnos próximos* (respondé con el número que querés reagendar):']
        for i, t in enumerate(turnos, 1):
            lines.append(
                f'{i}. {t.inicio.strftime("%Y-%m-%d %H:%M")} — '
                f'{t.servicio.nombre} con {t.recurso.nombre}'
            )
        motor.enviar('\n'.join(lines))
        _set_var(estado, 'agenda_step', 1)
        _set_var(estado, 'agenda_turnos', [t.id for t in turnos])
        return None

    if step == 1:
        if not consumir:
            return None
        ids = vars_ctx.get('agenda_turnos') or []
        idx = _parse_indice(texto, len(ids))
        if idx is None:
            motor.enviar(f'Respondé con un número entre 1 y {len(ids)}.')
            return None
        turno = Turno.objects.filter(pk=ids[idx], status=True).first()
        if not turno:
            motor.enviar('Ese turno no está disponible.')
            return None
        _set_var(estado, 'agenda_turno_id', turno.id)
        motor.enviar(
            f'¿Nueva fecha para *{turno.servicio.nombre}* con *{turno.recurso.nombre}*?\n'
            f'Respondé *hoy*, *mañana* o *YYYY-MM-DD*.'
        )
        _set_var(estado, 'agenda_step', 2)
        return None

    if step == 2:
        if not consumir:
            return None
        fecha = _parse_fecha(texto)
        if not fecha:
            motor.enviar('No reconocí la fecha. Probá con *hoy*, *mañana* o *YYYY-MM-DD*.')
            return None
        if fecha < timezone.localdate():
            motor.enviar('Esa fecha ya pasó.')
            return None
        turno = Turno.objects.filter(pk=vars_ctx.get('agenda_turno_id'), status=True).first()
        if not turno:
            _limpiar_vars(estado)
            return ''
        slots = calcular_slots_disponibles(turno.recurso, fecha, turno.servicio)
        if not slots:
            motor.enviar(f'No hay horarios disponibles el {fecha.strftime("%Y-%m-%d")}. Probá con otra fecha.')
            return None
        slots = slots[:10]
        lines = [f'*Horarios disponibles el {fecha.strftime("%Y-%m-%d")}*:']
        for i, (ini, _fin) in enumerate(slots, 1):
            lines.append(f'{i}. {ini.strftime("%H:%M")}')
        motor.enviar('\n'.join(lines))
        _set_var(estado, 'agenda_slots', [
            (ini.isoformat(), fin.isoformat()) for ini, fin in slots
        ])
        _set_var(estado, 'agenda_step', 3)
        return None

    if step == 3:
        if not consumir:
            return None
        slots = vars_ctx.get('agenda_slots') or []
        idx = _parse_indice(texto, len(slots))
        if idx is None:
            motor.enviar(f'Respondé con un número entre 1 y {len(slots)}.')
            return None
        ini_iso, fin_iso = slots[idx]
        turno_orig = Turno.objects.filter(pk=vars_ctx.get('agenda_turno_id'), status=True).first()
        if not turno_orig:
            _limpiar_vars(estado)
            return ''
        ini_dt = datetime.fromisoformat(ini_iso)
        fin_dt = datetime.fromisoformat(fin_iso)
        nuevo = Turno(
            recurso=turno_orig.recurso, servicio=turno_orig.servicio,
            contacto=turno_orig.contacto,
            inicio=ini_dt, fin=fin_dt,
            precio_cobrado=turno_orig.precio_cobrado,
            estado='confirmed', origen='chatbot',
            conversacion=motor.conversation, turno_anterior=turno_orig,
        )
        if nuevo.overlaps_existing():
            motor.enviar('Justo se ocupó ese horario. Elegí otro.')
            return None
        nuevo.save(request=None)
        turno_orig.estado = 'rescheduled'
        turno_orig.save(request=None)
        _limpiar_vars(estado)
        motor.enviar(
            f'✅ Turno reagendado para el {ini_dt.strftime("%Y-%m-%d %H:%M")}.'
        )
        return ''

    _limpiar_vars(estado)
    return ''
