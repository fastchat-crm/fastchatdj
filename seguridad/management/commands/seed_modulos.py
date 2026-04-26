"""Seed/reorganize sidebar modules and groups.

Idempotente. Por defecto UNIFICA (merge) sin borrar:
  - `Modulo`: get_or_create por `url`. Actualiza nombre/orden si cambian.
    Nunca se elimina.
  - `ModuloGrupo`: get_or_create por `nombre`. El M2M hace UNION con los
    modulos ya asignados (no pierde vinculos manuales agregados por UI).
  - `GroupModulo` del grupo `Staff`: UNION con los modulos del mapa.

Flags opcionales:
  --authoritative  El archivo es la unica fuente de verdad. Resetea el M2M
                   de cada seccion y del Staff a exactamente lo del mapa.
  --reset          Soft-delete (status=False) los Modulos cuya url no este
                   en el mapa. Solo tiene sentido con --authoritative.
  --dry-run        No escribe, solo reporta el plan.

Uso:
    python manage.py seed_modulos                   # merge seguro (default)
    python manage.py seed_modulos --authoritative   # reescribe M2Ms exactos
    python manage.py seed_modulos --authoritative --reset
    python manage.py seed_modulos --dry-run
"""
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from seguridad.models import Modulo, ModuloGrupo, GroupModulo


ADMIN_GROUP_NAME = 'Staff'


SECCIONES = [
    {
        'nombre':    'Inbox',
        'icono':     'fa fa-comments',
        'prioridad': 10,
        'modulos': [
            ('/whatsapp/conversaciones/',            'Conversaciones',          10),
            ('/whatsapp/conversaciones-finalizadas/','Conversaciones cerradas', 20),
            ('/whatsapp/contacto/',                  'Contactos',               30),
            ('/whatsapp/pipeline/',                  'Pipeline de ventas',      40),
            ('/whatsapp/etiquetas/',                 'Etiquetas',               50),
        ],
    },
    {
        'nombre':    'Canales',
        'icono':     'fa fa-plug',
        'prioridad': 20,
        'modulos': [
            ('/whatsapp/sesiones/', 'Sesiones WhatsApp', 10),
        ],
    },
    {
        'nombre':    'Mensajeria saliente',
        'icono':     'fa fa-paper-plane',
        'prioridad': 30,
        'modulos': [
            ('/whatsapp/plantillas/', 'Plantillas Meta',     10),
            ('/whatsapp/campanas/',   'Campanas masivas',    20),
            ('/whatsapp/horarios/',   'Horarios de atencion',30),
        ],
    },
    {
        'nombre':    'Inteligencia Artificial',
        'icono':     'fa fa-robot',
        'prioridad': 40,
        'modulos': [
            ('/crm/entrenamiento/',          'Entrenamiento IA',          10),
            ('/crm/entrenamiento/wizard/',   'Crear agente (rapido)',     15),
            ('/crm/departamentos_chatbots/', 'Flujos chatbot',            20),
            ('/whatsapp/trazas/',            'Trazas IA',                 30),
        ],
    },
    {
        'nombre':    'CRM',
        'icono':     'fa fa-briefcase',
        'prioridad': 50,
        'modulos': [
            ('/crm/perfil_empresa/',      'Perfil de empresa',   10),
            ('/crm/industria/',           'Industria',           20),
            ('/crm/actividad_economica/', 'Actividad economica', 30),
        ],
    },
    {
        'nombre':    'Analitica',
        'icono':     'fa fa-chart-line',
        'prioridad': 60,
        'modulos': [
            ('/whatsapp/analytics/', 'Analytics', 10),
        ],
    },
    {
        'nombre':    'Areas geograficas',
        'icono':     'fa fa-globe',
        'prioridad': 70,
        'modulos': [
            ('/area-geografica/pais/',      'Pais',      10),
            ('/area-geografica/provincia/', 'Provincia', 20),
            ('/area-geografica/ciudad/',    'Ciudad',    30),
        ],
    },
    {
        'nombre':    'Administracion de usuarios',
        'icono':     'fa fa-users-gear',
        'prioridad': 80,
        'modulos': [
            ('/autenticacion/usuario/',  'Administrativos', 10),
            ('/autenticacion/personas/', 'Clientes',        20),
            ('/seguridad/empresas/',     'Empresas',        30),
        ],
    },
    {
        'nombre':    'Configuracion',
        'icono':     'fa fa-sliders',
        'prioridad': 90,
        'modulos': [
            ('/seguridad/configuracion/',        'Configuracion del sitio', 10),
            ('/seguridad/credencial-meta/',      'Credenciales Meta',       20),
            ('/seguridad/terminosycondiciones/', 'Terminos y condiciones',  30),
        ],
    },
    {
        'nombre':    'Documentacion',
        'icono':     'fa fa-book',
        'prioridad': 95,
        'modulos': [
            ('/seguridad/documentacion/', 'Documentacion general', 10),
        ],
    },
    {
        'nombre':    'Sistemas',
        'icono':     'fa fa-gears',
        'prioridad': 100,
        'modulos': [
            ('/seguridad/grupo/',               'Roles de usuario',      10),
            ('/seguridad/modulogrupo/',         'Secciones del sidebar', 20),
            ('/seguridad/modulo/urls/',         'Mantenimiento URLs',    30),
            ('/seguridad/arbol-de-url/',        'Arbol de URLs',         40),
            ('/seguridad/arbol-de-grupos-url/', 'Arbol de grupos',       50),
            ('/seguridad/auditoria/',           'Auditoria',             60),
            ('/seguridad/databasebackup/',      'Backup BD',             70),
        ],
    },
]


class Command(BaseCommand):
    help = 'Crea/actualiza Modulos, ModuloGrupos y asigna todos al grupo Staff.'

    def add_arguments(self, parser):
        parser.add_argument('--authoritative', action='store_true',
                            help='El archivo es la unica fuente de verdad: '
                                 'resetea el M2M de cada seccion y del grupo Staff.')
        parser.add_argument('--reset', action='store_true',
                            help='Soft-delete (status=False) de Modulos cuya url no este '
                                 'en el mapa. Implica --authoritative.')
        parser.add_argument('--dry-run', action='store_true',
                            help='No escribe cambios, solo reporta.')

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        reset = opts['reset']
        authoritative = opts['authoritative'] or reset

        total_urls = sum(len(s['modulos']) for s in SECCIONES)
        modo = 'AUTHORITATIVE (reemplaza M2Ms)' if authoritative else 'MERGE (unifica, no borra)'
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'Sembrando {len(SECCIONES)} secciones / {total_urls} URLs '
            f'[{modo}]...'
        ))
        if dry:
            self.stdout.write(self.style.WARNING('DRY RUN - no se escribe nada.'))
            self._plan()
            return

        with transaction.atomic():
            modulos_por_url = self._upsert_modulos()
            self._upsert_secciones(modulos_por_url, authoritative)
            self._asignar_staff(modulos_por_url, authoritative)
            if reset:
                self._desactivar_huerfanos(modulos_por_url)

        self.stdout.write(self.style.SUCCESS('Listo.'))

    # -------- planeacion (dry-run) --------
    def _plan(self):
        for s in SECCIONES:
            self.stdout.write(f"  [{s['prioridad']:>3}] {s['nombre']} ({s['icono']})")
            for url, nombre, orden in s['modulos']:
                self.stdout.write(f"      {orden:>3}. {nombre:<28} {url}")

    # -------- helpers --------
    def _upsert_modulos(self):
        """Crea o actualiza cada Modulo. Devuelve {url: modulo}."""
        out = {}
        creados, actualizados, reactivados = 0, 0, 0
        for sec in SECCIONES:
            for url, nombre, orden in sec['modulos']:
                mod, was_created = Modulo.objects.get_or_create(
                    url=url, defaults={'nombre': nombre, 'orden': orden},
                )
                cambios = []
                if not was_created:
                    if mod.nombre != nombre:
                        mod.nombre = nombre; cambios.append('nombre')
                    if mod.orden != orden:
                        mod.orden = orden; cambios.append('orden')
                    if not mod.status:
                        mod.status = True; cambios.append('reactivado')
                        reactivados += 1
                    if cambios:
                        mod.save()
                        actualizados += 1
                else:
                    creados += 1
                out[url] = mod
        self.stdout.write(f'  Modulos: {creados} creados, {actualizados} actualizados, '
                          f'{reactivados} reactivados, {len(out)} total.')
        return out

    def _upsert_secciones(self, modulos_por_url, authoritative):
        """Crea/actualiza ModuloGrupo. En modo merge hace UNION al M2M; en
        authoritative lo resetea a exactamente los modulos del mapa."""
        creados, actualizados = 0, 0
        total_nuevos_links = 0
        for sec in SECCIONES:
            mg, was_created = ModuloGrupo.objects.get_or_create(
                nombre=sec['nombre'],
                defaults={'icono': sec['icono'], 'prioridad': sec['prioridad']},
            )
            cambios = []
            if not was_created:
                if mg.icono != sec['icono']:
                    mg.icono = sec['icono']; cambios.append('icono')
                if mg.prioridad != sec['prioridad']:
                    mg.prioridad = sec['prioridad']; cambios.append('prioridad')
                if not mg.status:
                    mg.status = True; cambios.append('reactivada')
                if cambios:
                    mg.save()
                    actualizados += 1
            else:
                creados += 1

            modulos_del_mapa = [modulos_por_url[url] for (url, _, _) in sec['modulos']]
            if authoritative:
                mg.modulos.set(modulos_del_mapa)
            else:
                existentes_ids = set(mg.modulos.values_list('id', flat=True))
                nuevos = [m for m in modulos_del_mapa if m.id not in existentes_ids]
                if nuevos:
                    mg.modulos.add(*nuevos)
                    total_nuevos_links += len(nuevos)
        modo = 'reasignado (set)' if authoritative else f'union: +{total_nuevos_links} link(s)'
        self.stdout.write(f'  Secciones: {creados} creadas, {actualizados} actualizadas, '
                          f'{len(SECCIONES)} total. M2M {modo}.')

    def _asignar_staff(self, modulos_por_url, authoritative):
        """Staff = admin unico. Le garantiza acceso a TODOS los modulos del mapa."""
        group, was_created = Group.objects.get_or_create(name=ADMIN_GROUP_NAME)
        if was_created:
            self.stdout.write(self.style.WARNING(
                f'  Grupo "{ADMIN_GROUP_NAME}" no existia, se creo.'
            ))
        gm, _ = GroupModulo.objects.get_or_create(group=group)
        if not gm.status:
            gm.status = True
            gm.save()

        modulos = list(modulos_por_url.values())
        if authoritative:
            gm.modulos.set(modulos)
            self.stdout.write(
                f'  Grupo "{ADMIN_GROUP_NAME}" re-asignado (set) a {len(modulos)} modulos.'
            )
        else:
            existentes_ids = set(gm.modulos.values_list('id', flat=True))
            nuevos = [m for m in modulos if m.id not in existentes_ids]
            if nuevos:
                gm.modulos.add(*nuevos)
            self.stdout.write(
                f'  Grupo "{ADMIN_GROUP_NAME}": +{len(nuevos)} modulo(s) agregado(s). '
                f'Total vinculados preservados.'
            )

    def _desactivar_huerfanos(self, modulos_por_url):
        """Marca status=False los Modulos cuya url no aparece en SECCIONES."""
        urls_validas = set(modulos_por_url.keys())
        huerfanos = Modulo.objects.filter(status=True).exclude(url__in=urls_validas)
        n = huerfanos.count()
        if n:
            self.stdout.write(self.style.WARNING(
                f'  {n} modulo(s) huerfano(s) desactivado(s):'
            ))
            for m in huerfanos:
                self.stdout.write(f'      - {m.url} ({m.nombre})')
            huerfanos.update(status=False)
        else:
            self.stdout.write('  Sin huerfanos.')
