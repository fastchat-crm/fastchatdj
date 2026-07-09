"""Seed del sidebar: resetea y recrea Modulos y ModuloGrupos.

Comportamiento por defecto (RESET total, sin duplicados):
  1. Toma snapshot de que URLs tenia asignadas cada rol (`GroupModulo`).
  2. Desactiva (status=False) TODOS los `Modulo` y `ModuloGrupo` activos.
  3. Recrea/reactiva desde `SECCIONES`:
     - `Modulo` por `url`: si existe se reutiliza el mas antiguo y se
       actualiza nombre/orden; duplicados por url quedan desactivados.
     - `ModuloGrupo` por `nombre`: icono/prioridad del mapa y M2M exacto
       (`set`) a los modulos de la seccion.
  4. Re-vincula los roles: cada `GroupModulo` conserva los modulos cuya
     url sigue existiendo en el mapa. El grupo `Staff` recibe TODOS.

Nunca se hace `.delete()`: todo borrado es soft-delete via status=False.

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
    help = ('Resetea el sidebar: desactiva todos los Modulos/ModuloGrupos y los '
            'recrea desde SECCIONES sin duplicados, re-vinculando los roles por URL.')

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='No escribe cambios, solo reporta.')

    def handle(self, *args, **opts):
        dry = opts['dry_run']

        total_urls = sum(len(s['modulos']) for s in SECCIONES)
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'Sembrando {len(SECCIONES)} secciones / {total_urls} URLs [RESET total]...'
        ))
        if dry:
            self.stdout.write(self.style.WARNING('DRY RUN - no se escribe nada.'))
            self._plan()
            return

        with transaction.atomic():
            snapshot_roles = self._snapshot_roles()
            self._desactivar_todo()
            modulos_por_url = self._recrear_modulos()
            self._recrear_secciones(modulos_por_url)
            self._revincular_roles(snapshot_roles, modulos_por_url)
            self._asignar_staff(modulos_por_url)

        self.stdout.write(self.style.SUCCESS('Listo.'))

    # -------- planeacion (dry-run) --------
    def _plan(self):
        for s in SECCIONES:
            self.stdout.write(f"  [{s['prioridad']:>3}] {s['nombre']} ({s['icono']})")
            for url, nombre, orden in s['modulos']:
                self.stdout.write(f"      {orden:>3}. {nombre:<28} {url}")

    # -------- helpers --------
    def _snapshot_roles(self):
        """Guarda {group_name: set(urls activas)} antes del reset."""
        snapshot = {}
        for gm in GroupModulo.objects.select_related('group').prefetch_related('modulos'):
            urls = set(gm.modulos.values_list('url', flat=True))
            snapshot[gm.group.name] = urls
        self.stdout.write(f'  Snapshot de {len(snapshot)} rol(es) tomado.')
        return snapshot

    def _desactivar_todo(self):
        """Soft-delete de todo el catalogo actual (nunca .delete())."""
        n_mod = Modulo.objects.filter(status=True).update(status=False)
        n_sec = ModuloGrupo.objects.filter(status=True).update(status=False)
        self.stdout.write(f'  Desactivados: {n_mod} modulo(s), {n_sec} seccion(es).')

    def _recrear_modulos(self):
        """Reactiva o crea cada Modulo del mapa. Duplicados por url quedan
        desactivados (se reutiliza siempre el registro mas antiguo).
        Devuelve {url: modulo}."""
        out = {}
        creados, reactivados, duplicados = 0, 0, 0
        for sec in SECCIONES:
            for url, nombre, orden in sec['modulos']:
                existentes = list(Modulo.objects.filter(url=url).order_by('id'))
                if existentes:
                    mod = existentes[0]
                    mod.nombre = nombre
                    mod.orden = orden
                    mod.status = True
                    mod.save()
                    reactivados += 1
                    duplicados += len(existentes) - 1
                else:
                    mod = Modulo.objects.create(url=url, nombre=nombre, orden=orden)
                    creados += 1
                out[url] = mod
        self.stdout.write(f'  Modulos: {creados} creados, {reactivados} reactivados, '
                          f'{duplicados} duplicado(s) dejados inactivos, {len(out)} total.')
        return out

    def _recrear_secciones(self, modulos_por_url):
        """Reactiva o crea cada ModuloGrupo del mapa con M2M exacto (set)."""
        creadas, reactivadas, duplicadas = 0, 0, 0
        for sec in SECCIONES:
            existentes = list(ModuloGrupo.objects.filter(nombre=sec['nombre']).order_by('id'))
            if existentes:
                mg = existentes[0]
                mg.icono = sec['icono']
                mg.prioridad = sec['prioridad']
                mg.status = True
                mg.save()
                reactivadas += 1
                duplicadas += len(existentes) - 1
            else:
                mg = ModuloGrupo.objects.create(
                    nombre=sec['nombre'], icono=sec['icono'], prioridad=sec['prioridad'],
                )
                creadas += 1
            mg.modulos.set([modulos_por_url[url] for (url, _, _) in sec['modulos']])
        self.stdout.write(f'  Secciones: {creadas} creadas, {reactivadas} reactivadas, '
                          f'{duplicadas} duplicada(s) dejadas inactivas, {len(SECCIONES)} total.')

    def _revincular_roles(self, snapshot_roles, modulos_por_url):
        """Cada rol conserva los modulos cuya url sigue en el mapa."""
        for gm in GroupModulo.objects.select_related('group'):
            if gm.group.name == ADMIN_GROUP_NAME:
                continue
            urls_previas = snapshot_roles.get(gm.group.name, set())
            vigentes = [modulos_por_url[u] for u in urls_previas if u in modulos_por_url]
            perdidos = len(urls_previas) - len(vigentes)
            gm.modulos.set(vigentes)
            detalle = f', {perdidos} url(s) obsoleta(s) descartada(s)' if perdidos else ''
            self.stdout.write(
                f'  Rol "{gm.group.name}": {len(vigentes)} modulo(s) re-vinculado(s){detalle}.'
            )

    def _asignar_staff(self, modulos_por_url):
        """Staff = admin unico. Recibe TODOS los modulos del mapa."""
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
            f'  Grupo "{ADMIN_GROUP_NAME}" asignado (set) a {len(modulos)} modulos.'
        )
