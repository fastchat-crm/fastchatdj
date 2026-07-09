"""Seed del sidebar: BORRA (delete real) todo el catalogo y lo recrea.

Comportamiento (RESET destructivo):
  1. Elimina con `.delete()` TODOS los `GroupModulo`, `ModuloGrupo` y `Modulo`.
  2. Crea desde cero los `Modulo` y `ModuloGrupo` definidos en `SECCIONES`.
  3. Crea (o reutiliza) el grupo `Administrador` y le asigna TODOS los modulos
     via `GroupModulo`.

ADVERTENCIA: los demas roles pierden sus URLs asignadas; hay que
re-asignarlas desde /seguridad/arbol-de-grupos-url/.

Flags:
  --dry-run   No escribe, solo reporta el plan.

Uso:
    python manage.py seed_modulos
    python manage.py seed_modulos --dry-run
"""
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from seguridad.models import Modulo, ModuloGrupo, GroupModulo


ADMIN_GROUP_NAME = 'Administrador'


SECCIONES = [
    {
        'nombre':    'WhatsApp',
        'icono':     'fab fa-whatsapp',
        'prioridad': 10,
        'modulos': [
            ('/whatsapp/sesiones/',                  'Sesiones',                 10),
            ('/whatsapp/conversaciones/',            'Conversaciones',           20),
            ('/whatsapp/conversaciones-finalizadas/','Conversaciones cerradas',  30),
            ('/whatsapp/conversaciones-pendiente-reconexion/', 'Pendientes de reconexión', 40),
            ('/whatsapp/contacto/',                  'Contactos',                50),
            ('/whatsapp/etiquetas/',                 'Etiquetas',                60),
            ('/whatsapp/pipeline/',                  'Pipeline de ventas',       70),
            ('/whatsapp/plantillas/',                'Plantillas Meta',          80),
            ('/whatsapp/campanas/',                  'Campañas masivas',         90),
            ('/whatsapp/horarios/',                  'Horarios de atención',    100),
        ],
    },
    {
        'nombre':    'Instagram',
        'icono':     'fab fa-instagram',
        'prioridad': 20,
        'modulos': [
            ('/instagram/sesiones/',       'Sesiones',       10),
            ('/instagram/conversaciones/', 'Conversaciones', 20),
            ('/instagram/comentarios/',    'Comentarios',    30),
            ('/instagram/publicaciones/',  'Publicaciones',  40),
        ],
    },
    {
        'nombre':    'TikTok',
        'icono':     'fab fa-tiktok',
        'prioridad': 30,
        'modulos': [
            ('/tiktok/sesiones/',       'Sesiones',       10),
            ('/tiktok/conversaciones/', 'Conversaciones', 20),
            ('/tiktok/comentarios/',    'Comentarios',    30),
        ],
    },
    {
        'nombre':    'CRM',
        'icono':     'fa fa-address-book',
        'prioridad': 40,
        'modulos': [
            ('/crm/cliente/',             'Clientes',            10),
            ('/crm/perfil_empresa/',      'Perfil de empresa',   20),
            ('/crm/industria/',           'Industria',           30),
            ('/crm/actividad_economica/', 'Actividad económica', 40),
        ],
    },
    {
        'nombre':    'Inteligencia Artificial',
        'icono':     'fa fa-robot',
        'prioridad': 50,
        'modulos': [
            ('/crm/entrenamiento/',        'Entrenamiento IA',      10),
            ('/crm/entrenamiento/wizard/', 'Crear agente (rápido)', 20),
            ('/crm/endpoints_api/',        'Endpoints API',         30),
            ('/whatsapp/trazas/',          'Trazas IA',             40),
        ],
    },
    {
        'nombre':    'Departamentos',
        'icono':     'fa fa-sitemap',
        'prioridad': 60,
        'modulos': [
            ('/crm/departamentos_chatbots/', 'Flujos chatbot', 10),
        ],
    },
    {
        'nombre':    'Analítica',
        'icono':     'fa fa-chart-line',
        'prioridad': 70,
        'modulos': [
            ('/whatsapp/analytics/',   'Analytics',   10),
            ('/whatsapp/supervision/', 'Supervisión', 20),
        ],
    },
    {
        'nombre':    'Agenda',
        'icono':     'fa fa-calendar-days',
        'prioridad': 80,
        'modulos': [
            ('/agenda/citas/',         'Citas',                   10),
            ('/agenda/configuracion/', 'Configuración de agenda', 20),
        ],
    },
    {
        'nombre':    'Meta',
        'icono':     'fab fa-meta',
        'prioridad': 90,
        'modulos': [
            ('/seguridad/credencial-meta/', 'Credenciales Meta App', 10),
            ('/whatsapp/tarifas/',          'Tarifas Meta',          20),
        ],
    },
    {
        'nombre':    'Administración de usuarios',
        'icono':     'fa fa-users-gear',
        'prioridad': 100,
        'modulos': [
            ('/autenticacion/usuario/',  'Administrativos',  10),
            ('/autenticacion/personas/', 'Clientes',         20),
            ('/seguridad/empresas/',     'Empresas',         30),
            ('/seguridad/grupo/',        'Roles de usuario', 40),
        ],
    },
    {
        'nombre':    'Áreas geográficas',
        'icono':     'fa fa-globe',
        'prioridad': 110,
        'modulos': [
            ('/area-geografica/pais/',      'País',      10),
            ('/area-geografica/provincia/', 'Provincia', 20),
            ('/area-geografica/ciudad/',    'Ciudad',    30),
        ],
    },
    {
        'nombre':    'Configuración del sistema',
        'icono':     'fa fa-sliders',
        'prioridad': 120,
        'modulos': [
            ('/seguridad/configuracion/',        'Configuración del sitio',   10),
            ('/seguridad/terminosycondiciones/', 'Términos y condiciones',    20),
            ('/seguridad/administracion-mails/', 'Administración de correos', 30),
            ('/seguridad/webpush-broadcast/',    'Push broadcast',            40),
            ('/seguridad/documentacion/',        'Documentación',             50),
        ],
    },
    {
        'nombre':    'Mantenimientos',
        'icono':     'fa fa-gears',
        'prioridad': 130,
        'modulos': [
            ('/seguridad/modulogrupo/',         'Secciones del sidebar', 10),
            ('/seguridad/modulo/urls/',         'Mantenimiento URLs',    20),
            ('/seguridad/arbol-de-url/',        'Árbol de URLs',         30),
            ('/seguridad/arbol-de-grupos-url/', 'Árbol de grupos',       40),
            ('/seguridad/auditoria/',           'Auditoría',             50),
            ('/seguridad/databasebackup/',      'Backup BD',             60),
        ],
    },
]


class Command(BaseCommand):
    help = ('Borra (delete real) todos los Modulos, ModuloGrupos y GroupModulos, '
            'los recrea desde SECCIONES y asigna todo al grupo Administrador.')

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='No escribe cambios, solo reporta.')

    def handle(self, *args, **opts):
        dry = opts['dry_run']

        total_urls = sum(len(s['modulos']) for s in SECCIONES)
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'Sembrando {len(SECCIONES)} secciones / {total_urls} URLs [DELETE total]...'
        ))
        if dry:
            self.stdout.write(self.style.WARNING('DRY RUN - no se escribe nada.'))
            self._plan()
            return

        with transaction.atomic():
            self._borrar_todo()
            modulos_por_url = self._crear_modulos()
            self._crear_secciones(modulos_por_url)
            self._asignar_administrador(modulos_por_url)

        self.stdout.write(self.style.SUCCESS('Listo.'))

    def _plan(self):
        for s in SECCIONES:
            self.stdout.write(f"  [{s['prioridad']:>3}] {s['nombre']} ({s['icono']})")
            for url, nombre, orden in s['modulos']:
                self.stdout.write(f"      {orden:>3}. {nombre:<28} {url}")

    def _borrar_todo(self):
        """Delete real de todo el catalogo del sidebar y sus asignaciones."""
        n_gm, _ = GroupModulo.objects.all().delete()
        n_sec, _ = ModuloGrupo.objects.all().delete()
        n_mod, _ = Modulo.objects.all().delete()
        self.stdout.write(
            f'  Eliminados: {n_gm} asignacion(es) de rol, {n_sec} seccion(es), '
            f'{n_mod} modulo(s).'
        )

    def _crear_modulos(self):
        """Crea cada Modulo del mapa desde cero. Devuelve {url: modulo}."""
        out = {}
        for sec in SECCIONES:
            for url, nombre, orden in sec['modulos']:
                out[url] = Modulo.objects.create(url=url, nombre=nombre, orden=orden)
        self.stdout.write(f'  Modulos creados: {len(out)}.')
        return out

    def _crear_secciones(self, modulos_por_url):
        """Crea cada ModuloGrupo del mapa con su M2M exacto."""
        for sec in SECCIONES:
            mg = ModuloGrupo.objects.create(
                nombre=sec['nombre'], icono=sec['icono'], prioridad=sec['prioridad'],
            )
            mg.modulos.set([modulos_por_url[url] for (url, _, _) in sec['modulos']])
        self.stdout.write(f'  Secciones creadas: {len(SECCIONES)}.')

    def _asignar_administrador(self, modulos_por_url):
        """Grupo Administrador recibe TODOS los modulos del mapa."""
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
        gm.modulos.set(modulos)
        self.stdout.write(
            f'  Grupo "{ADMIN_GROUP_NAME}" asignado a {len(modulos)} modulo(s).'
        )
