"""Seeder: crea una agenda completa para un consultorio medico.

Configuracion:
  - GrupoAgenda "Consultorio Medico"
  - 1 Recurso "Doctor General" (se puede pasar mas con --recursos)
  - Horario laboral:
      lunes a viernes 08:00 - 17:00
      sabado          09:00 - 14:00
  - Servicios de consulta tipicos (consulta general, control, etc.)

Uso:
    python scripts/seed_agenda_consultorio_medico.py
    python scripts/seed_agenda_consultorio_medico.py --sesion-id 19
    python scripts/seed_agenda_consultorio_medico.py --moneda PEN
    python scripts/seed_agenda_consultorio_medico.py --recursos "Dr. Garcia,Dr. Lopez,Box 1"
    python scripts/seed_agenda_consultorio_medico.py --limpiar
"""
import argparse
import os
import sys
from datetime import time
from decimal import Decimal

from django.core.wsgi import get_wsgi_application
from django.db import transaction

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')
application = get_wsgi_application()

from agenda.models import (
    GrupoAgenda,
    HorarioLaboral,
    Recurso,
    Servicio,
)
from whatsapp.models import SesionWhatsApp


GRUPO_NOMBRE = 'Consultorio Medico'
GRUPO_DESCRIPCION = (
    'Agenda del consultorio medico: turnos para consultas y controles. '
    'Atencion lunes a viernes 08:00-17:00, sabados 09:00-14:00.'
)

RECURSOS_DEFECTO = ['Doctor General']

HORARIOS = [
    {'dias': [0, 1, 2, 3, 4], 'inicio': time(8, 0),  'fin': time(17, 0), 'slot': 30},
    {'dias': [5],             'inicio': time(9, 0),  'fin': time(14, 0), 'slot': 30},
]

SERVICIOS = [
    {
        'nombre': 'Consulta General',
        'descripcion': 'Consulta medica general de primera vez.',
        'duracion_min': 30,
        'precio': Decimal('40.00'),
    },
    {
        'nombre': 'Control de Seguimiento',
        'descripcion': 'Control posterior a una consulta inicial.',
        'duracion_min': 20,
        'precio': Decimal('25.00'),
    },
    {
        'nombre': 'Consulta Pediatrica',
        'descripcion': 'Atencion pediatrica para ninos y adolescentes.',
        'duracion_min': 30,
        'precio': Decimal('45.00'),
    },
    {
        'nombre': 'Chequeo Preventivo',
        'descripcion': 'Examen general anual de prevencion.',
        'duracion_min': 45,
        'precio': Decimal('60.00'),
    },
    {
        'nombre': 'Certificado Medico',
        'descripcion': 'Emision de certificado medico simple.',
        'duracion_min': 15,
        'precio': Decimal('20.00'),
    },
]


def _crear_grupo(moneda, recordatorio_horas, zona_horaria):
    grupo, creado = GrupoAgenda.objects.get_or_create(
        nombre=GRUPO_NOMBRE,
        defaults={
            'descripcion': GRUPO_DESCRIPCION,
            'moneda': moneda,
            'recordatorio_horas_antes': recordatorio_horas,
            'zona_horaria': zona_horaria,
            'status': True,
        },
    )
    if not creado:
        grupo.descripcion = GRUPO_DESCRIPCION
        grupo.moneda = moneda
        grupo.recordatorio_horas_antes = recordatorio_horas
        grupo.zona_horaria = zona_horaria
        grupo.status = True
        grupo.save()
    print(f'  GrupoAgenda: {grupo.nombre} ({"creado" if creado else "actualizado"}) [moneda={grupo.moneda}]')
    return grupo


def _crear_recursos(grupo, nombres):
    recursos = []
    colores = ['#0d6efd', '#198754', '#fd7e14', '#dc3545', '#6f42c1', '#20c997', '#d63384']
    for orden, nombre in enumerate(nombres):
        color = colores[orden % len(colores)]
        rec, creado = Recurso.objects.get_or_create(
            grupo_agenda=grupo, nombre=nombre,
            defaults={'color': color, 'orden': orden, 'status': True},
        )
        if not creado:
            rec.color = color
            rec.orden = orden
            rec.status = True
            rec.save()
        print(f'  Recurso: {rec.nombre} ({"creado" if creado else "actualizado"})')
        recursos.append(rec)
    return recursos


def _crear_horarios(recurso):
    HorarioLaboral.objects.filter(recurso=recurso).update(status=False)
    creados = 0
    for bloque in HORARIOS:
        for dia in bloque['dias']:
            HorarioLaboral.objects.create(
                recurso=recurso,
                dia_semana=dia,
                hora_inicio=bloque['inicio'],
                hora_fin=bloque['fin'],
                duracion_slot_min=bloque['slot'],
                status=True,
            )
            creados += 1
    print(f'    Horarios cargados ({creados} bloques: lun-vie 08:00-17:00, sab 09:00-14:00)')


def _crear_servicios(grupo, recursos):
    servicios = []
    for orden, s in enumerate(SERVICIOS):
        serv, creado = Servicio.objects.get_or_create(
            grupo_agenda=grupo, nombre=s['nombre'],
            defaults={
                'descripcion': s['descripcion'],
                'duracion_min': s['duracion_min'],
                'precio': s['precio'],
                'orden': orden,
                'status': True,
            },
        )
        if not creado:
            serv.descripcion = s['descripcion']
            serv.duracion_min = s['duracion_min']
            serv.precio = s['precio']
            serv.orden = orden
            serv.status = True
            serv.save()
        serv.recursos.set(recursos)
        print(f'  Servicio: {serv.nombre} ({"creado" if creado else "actualizado"}) - '
              f'{serv.duracion_min} min, {serv.precio} {grupo.moneda}')
        servicios.append(serv)
    return servicios


def _vincular_sesion(grupo, sesion_id):
    if not sesion_id:
        return
    try:
        sesion = SesionWhatsApp.objects.get(pk=sesion_id)
    except SesionWhatsApp.DoesNotExist:
        print(f'  AVISO: SesionWhatsApp id={sesion_id} no existe. Salto vinculacion.')
        return
    sesion.grupo_agenda = grupo
    sesion.save()
    print(f'  Sesion {sesion.id} ({sesion.numero or "sin numero"}) vinculada al grupo.')


def sembrar(sesion_id=None, moneda='USD', recursos_nombres=None, recordatorio_horas=24,
            zona_horaria='America/Guayaquil'):
    nombres = recursos_nombres or RECURSOS_DEFECTO
    print('Sembrando agenda del consultorio medico...')
    with transaction.atomic():
        grupo = _crear_grupo(moneda, recordatorio_horas, zona_horaria)
        recursos = _crear_recursos(grupo, nombres)
        for rec in recursos:
            print(f'  Configurando horario de "{rec.nombre}"...')
            _crear_horarios(rec)
        _crear_servicios(grupo, recursos)
        _vincular_sesion(grupo, sesion_id)
    print('\nListo. Resumen:')
    print(f'  Grupo "{grupo.nombre}" ({grupo.moneda})')
    print(f'  Recursos: {len(recursos)} ({", ".join(r.nombre for r in recursos)})')
    print(f'  Servicios: {len(SERVICIOS)}')
    print(f'  Horario: lun-vie 08:00-17:00, sab 09:00-14:00 (slot 30 min)')
    print(f'  Recordatorio: {recordatorio_horas}h antes')
    if sesion_id:
        print(f'  Sesion vinculada: id={sesion_id}')
    else:
        print('  Sin sesion vinculada. Para vincular: editar SesionWhatsApp.grupo_agenda en admin '
              'o usar --sesion-id <id>.')


def limpiar():
    print('Eliminando datos sembrados (soft-delete)...')
    grupos = GrupoAgenda.objects.filter(nombre=GRUPO_NOMBRE)
    if not grupos.exists():
        print(f'  No existe ningun grupo con nombre "{GRUPO_NOMBRE}".')
        return
    with transaction.atomic():
        for grupo in grupos:
            HorarioLaboral.objects.filter(recurso__grupo_agenda=grupo).update(status=False)
            Recurso.objects.filter(grupo_agenda=grupo).update(status=False)
            Servicio.objects.filter(grupo_agenda=grupo).update(status=False)
            grupo.status = False
            grupo.save()
            print(f'  Grupo "{grupo.nombre}" y sus recursos/servicios marcados inactivos.')
    SesionWhatsApp.objects.filter(grupo_agenda__in=grupos).update(grupo_agenda=None)
    print('Hecho.')


def main():
    parser = argparse.ArgumentParser(description='Sembrar agenda de consultorio medico.')
    parser.add_argument('--sesion-id', type=int, default=None,
                        help='ID de SesionWhatsApp para vincular al grupo creado.')
    parser.add_argument('--moneda', type=str, default='USD',
                        help='Codigo de moneda (USD, ARS, PEN, COP, MXN, etc.). Default: USD.')
    parser.add_argument('--recursos', type=str, default=None,
                        help='Lista separada por comas de nombres de recursos. '
                             'Default: "Doctor General".')
    parser.add_argument('--recordatorio', type=int, default=24,
                        help='Horas antes para enviar recordatorio. Default: 24.')
    parser.add_argument('--zona-horaria', type=str, default='America/Guayaquil',
                        help='Zona horaria del grupo. Default: America/Guayaquil.')
    parser.add_argument('--limpiar', action='store_true',
                        help='Eliminar (soft-delete) los datos sembrados por este script.')
    args = parser.parse_args()

    if args.limpiar:
        limpiar()
        return

    nombres = None
    if args.recursos:
        nombres = [n.strip() for n in args.recursos.split(',') if n.strip()]

    sembrar(
        sesion_id=args.sesion_id,
        moneda=args.moneda,
        recursos_nombres=nombres,
        recordatorio_horas=args.recordatorio,
        zona_horaria=args.zona_horaria,
    )


if __name__ == '__main__':
    main()
