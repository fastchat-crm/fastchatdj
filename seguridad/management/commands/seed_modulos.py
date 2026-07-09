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
                   en el mapa Y las ModuloGrupo cuyo nombre no este en
                   SECCIONES (reemplaza la segmentacion vieja del sidebar).
                   Solo tiene sentido con --authoritative.
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
        'nombre':    'Inteligencia Artificial',
        'icono':     'fa fa-robot',
        'prioridad': 40,
        'modulos': [
            ('/crm/entrenamiento/',          'Entrenamiento IA',      10),
            ('/crm/entrenamiento/wizard/',   'Crear agente (rápido)', 20),
            ('/crm/departamentos_chatbots/', 'Flujos chatbot',        30),
            ('/crm/endpoints_api/',          'Endpoints API',         40),
            ('/whatsapp/trazas/',            'Trazas IA',             50),
        ],
    },
    {
        'nombre':    'Analítica',
        'icono':     'fa fa-chart-line',
        'prioridad': 50,
        'modulos': [
            ('/whatsapp/analytics/',   'Analytics',   10),
            ('/whatsapp/supervision/', 'Supervisión', 20),
        ],
    },
    {
        'nombre':    'Agenda',
        'icono':     'fa fa-calendar-days',
        'prioridad': 60,
        'modulos': [
            ('/agenda/citas/',         'Citas',                   10),
            ('/agenda/configuracion/', 'Configuración de agenda', 20),
        ],
    },
    {
        'nombre':    'Meta',
        'icono':     'fab fa-meta',
        'prioridad': 70,
        'modulos': [
            ('/seguridad/credencial-meta/', 'Credenciales Meta App', 10),
            ('/whatsapp/tarifas/',          'Tarifas Meta',          20),
        ],
    },
    {
        'nombre':    'Administración de usuarios',
        'icono':     'fa fa-users-gear',
        'prioridad': 80,
        'modulos': [
            ('/autenticacion/usuario/',  'Administrativos',  10),
            ('/autenticacion/personas/', 'Clientes',         20),
            ('/crm/cliente/',            'Clientes CRM',     30),
            ('/seguridad/empresas/',     'Empresas',         40),
            ('/seguridad/grupo/',        'Roles de usuario', 50),
        ],
    },
    {
        'nombre':    'Áreas geográficas',
        'icono':     'fa fa-globe',
        'prioridad': 90,
        'modulos': [
            ('/area-geografica/pais/',      'País',      10),
            ('/area-geografica/provincia/', 'Provincia', 20),
            ('/area-geografica/ciudad/',    'Ciudad',    30),
        ],
    },
    {
        'nombre':    'Configuración del sistema',
        'icono':     'fa fa-sliders',
        'prioridad': 100,
        'modulos': [
            ('/seguridad/configuracion/',         'Configuración del sitio',   10),
            ('/crm/perfil_empresa/',              'Perfil de empresa',         20),
            ('/crm/industria/',                   'Industria',                 30),
            ('/crm/actividad_economica/',         'Actividad económica',       40),
            ('/seguridad/terminosycondiciones/',  'Términos y condiciones',    50),
            ('/seguridad/administracion-mails/',  'Administración de correos', 60),
            ('/seguridad/webpush-broadcast/',     'Push broadcast',            70),
            ('/seguridad/documentacion/',         'Documentación',             80),
        ],
    },
    {
        'nombre':    'Mantenimientos',
        'icono':     'fa fa-gears',
        'prioridad': 110,
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
                self._desactivar_secciones_huerfanas()

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

    def _desactivar_secciones_huerfanas(self):
        """Marca status=False las ModuloGrupo cuyo nombre no aparece en SECCIONES.

        Es lo que permite reemplazar la segmentacion vieja del sidebar
        (Inbox/Canales/CRM/...) por la nueva sin dejar secciones fantasma.
        """
        nombres_validos = {s['nombre'] for s in SECCIONES}
        huerfanas = ModuloGrupo.objects.filter(status=True).exclude(nombre__in=nombres_validos)
        n = huerfanas.count()
        if n:
            self.stdout.write(self.style.WARNING(
                f'  {n} seccion(es) huerfana(s) desactivada(s):'
            ))
            for mg in huerfanas:
                self.stdout.write(f'      - {mg.nombre}')
            huerfanas.update(status=False)
        else:
            self.stdout.write('  Sin secciones huerfanas.')

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
