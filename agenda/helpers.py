from datetime import date, datetime, time, timedelta

from django.utils import timezone

from .models import ACTIVE_STATUSES, ExcepcionAgenda, HorarioLaboral, Turno


def _combine_aware(fecha: date, hora: time, tz=None):
    naive = datetime.combine(fecha, hora)
    tz = tz or timezone.get_current_timezone()
    return timezone.make_aware(naive, tz)


def _expand_horarios(recurso, fecha: date, slot_min: int):
    rangos = []
    horarios = HorarioLaboral.objects.filter(
        recurso=recurso, status=True, dia_semana=fecha.weekday()
    )
    for h in horarios:
        rangos.append({
            'inicio': h.hora_inicio,
            'fin': h.hora_fin,
            'slot_min': slot_min or h.duracion_slot_min,
        })
    return rangos


def _aplicar_excepciones(rangos, recurso, fecha: date):
    excepciones = ExcepcionAgenda.objects.filter(recurso=recurso, fecha=fecha, status=True)
    for ex in excepciones:
        if ex.tipo == 'block_day':
            return []
        if ex.tipo == 'add_range' and ex.hora_inicio and ex.hora_fin:
            rangos.append({
                'inicio': ex.hora_inicio,
                'fin': ex.hora_fin,
                'slot_min': rangos[0]['slot_min'] if rangos else 30,
            })
        if ex.tipo == 'block_range' and ex.hora_inicio and ex.hora_fin:
            nuevos = []
            for r in rangos:
                if ex.hora_fin <= r['inicio'] or ex.hora_inicio >= r['fin']:
                    nuevos.append(r)
                    continue
                if ex.hora_inicio > r['inicio']:
                    nuevos.append({'inicio': r['inicio'], 'fin': ex.hora_inicio, 'slot_min': r['slot_min']})
                if ex.hora_fin < r['fin']:
                    nuevos.append({'inicio': ex.hora_fin, 'fin': r['fin'], 'slot_min': r['slot_min']})
            rangos = nuevos
    return rangos


def _generar_slots(rangos, fecha: date, duracion_min: int, tz):
    slots = []
    paso = timedelta(minutes=duracion_min)
    for r in rangos:
        cursor = _combine_aware(fecha, r['inicio'], tz)
        limite = _combine_aware(fecha, r['fin'], tz)
        while cursor + paso <= limite:
            slots.append((cursor, cursor + paso))
            cursor += paso
    return slots


def _restar_turnos(slots, recurso):
    if not slots:
        return slots
    rango_min = min(s[0] for s in slots)
    rango_max = max(s[1] for s in slots)
    ocupados = list(Turno.objects.filter(
        recurso=recurso,
        status=True,
        estado__in=ACTIVE_STATUSES,
        inicio__lt=rango_max,
        fin__gt=rango_min,
    ).values_list('inicio', 'fin'))
    if not ocupados:
        return slots
    libres = []
    for ini, fin in slots:
        choca = any(o_ini < fin and o_fin > ini for o_ini, o_fin in ocupados)
        if not choca:
            libres.append((ini, fin))
    return libres


def calcular_slots_disponibles(recurso, fecha: date, servicio=None):
    duracion_min = servicio.duracion_min if servicio else None
    tz_name = recurso.grupo_agenda.zona_horaria
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = timezone.get_current_timezone()

    rangos = _expand_horarios(recurso, fecha, duracion_min or 0)
    if not duracion_min:
        duracion_min = rangos[0]['slot_min'] if rangos else 30
    rangos = _aplicar_excepciones(rangos, recurso, fecha)
    slots = _generar_slots(rangos, fecha, duracion_min, tz)
    slots = _restar_turnos(slots, recurso)
    return slots


def listar_turnos_futuros_contacto(contacto, limite=10):
    return Turno.objects.filter(
        contacto=contacto,
        status=True,
        estado__in=ACTIVE_STATUSES,
        inicio__gte=timezone.now(),
    ).order_by('inicio')[:limite]
