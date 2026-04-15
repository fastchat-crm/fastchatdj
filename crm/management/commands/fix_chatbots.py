"""
Script todo-en-uno para reparar chatbots tradicionales que quedaron corruptos.

Hace (en orden):
  1. Borra EstadoFlujoChatbot huérfanos (departamento=None).
  2. Limpia estados con en_handoff=True que llevan > N minutos colgados.
  3. Para cada departamento:
     - Si ningún nodo raíz tiene es_inicio=True, marca el primer nodo `menu`
       raíz (o, si no hay menu, el primer raíz por orden) como es_inicio=True.
     - Reporta anomalías: nodos sin config, menús sin opciones, etc.
  4. Si se pasa --reseed-estudiantil, borra y recrea el depto del seed.
  5. Si se pasa --sesion, asocia el depto reseedeado a esa sesión en modo
     'tradicional' con departamento_default apuntando a él.

Uso típico (después de que el wizard corrompió algo):
    python manage.py fix_chatbots
    python manage.py fix_chatbots --reseed-estudiantil --sesion 3

Modo diagnóstico sin cambios:
    python manage.py fix_chatbots --dry-run
"""

from datetime import timedelta
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from crm.models import (
    DepartamentoChatBot,
    OpcionDepartamentoChatBot,
    EstadoFlujoChatbot,
)


SEED_NOMBRE = 'Centro de Atención Estudiantil'


class Command(BaseCommand):
    help = 'Repara inconsistencias en chatbots tradicionales (estados huérfanos, nodos sin inicio, etc.).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='No hace cambios, sólo reporta lo que haría.'
        )
        parser.add_argument(
            '--reseed-estudiantil', action='store_true',
            help='Borra y recrea el depto "Centro de Atención Estudiantil" con el seed.'
        )
        parser.add_argument(
            '--sesion', type=int, default=None,
            help='ID de SesionWhatsApp para asociar el depto reseedeado.'
        )
        parser.add_argument(
            '--handoff-minutos', type=int, default=120,
            help='Estados en_handoff más viejos que estos minutos se resetean (default 120).'
        )

    def _step(self, texto):
        self.stdout.write(self.style.SUCCESS(f'\n▶ {texto}'))

    def _info(self, texto):
        self.stdout.write(f'  {texto}')

    def _warn(self, texto):
        self.stdout.write(self.style.WARNING(f'  ⚠ {texto}'))

    def _ok(self, texto):
        self.stdout.write(self.style.SUCCESS(f'  ✓ {texto}'))

    # ─────────────────────────────────────────────────────────────

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        self.stdout.write(self.style.MIGRATE_HEADING(
            '\n═══════════ FIX CHATBOTS TRADICIONALES ═══════════'
        ))
        if dry:
            self.stdout.write(self.style.WARNING('Modo DRY-RUN: no se harán cambios.\n'))

        with transaction.atomic():
            self._limpiar_estados_huerfanos(dry)
            self._resetear_handoffs_colgados(dry, opts['handoff_minutos'])
            self._arreglar_nodos_inicio(dry)
            if opts['reseed_estudiantil']:
                self._reseed_estudiantil(dry, opts.get('sesion'))
            self._reporte_final()

            if dry:
                # Al salir del bloque atómico, los cambios hechos (si alguno) se
                # descartarán porque lanzamos un rollback explícito.
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING(
                    '\n(DRY-RUN terminado — ningún cambio fue persistido)'
                ))

    # ─────────────────────────────────────────────────────────────
    # 1. Estados huérfanos
    # ─────────────────────────────────────────────────────────────

    def _limpiar_estados_huerfanos(self, dry):
        self._step('1. Limpieza de estados huérfanos (sin departamento)')
        huerfanos = EstadoFlujoChatbot.objects.filter(departamento__isnull=True)
        n = huerfanos.count()
        if n == 0:
            self._info('Sin estados huérfanos.')
            return
        self._warn(f'{n} estado(s) huérfano(s) encontrados.')
        if not dry:
            huerfanos.delete()
            self._ok(f'{n} estado(s) eliminados.')

    # ─────────────────────────────────────────────────────────────
    # 2. Handoffs colgados
    # ─────────────────────────────────────────────────────────────

    def _resetear_handoffs_colgados(self, dry, minutos):
        self._step(f'2. Reset de en_handoff colgados (>{minutos} min sin actividad)')
        limite = timezone.now() - timedelta(minutes=minutos)
        qs = EstadoFlujoChatbot.objects.filter(en_handoff=True, actualizado__lt=limite)
        n = qs.count()
        if n == 0:
            self._info('Sin handoffs colgados (o todos son recientes).')
            return
        self._warn(f'{n} estado(s) con en_handoff=True más viejos que el límite.')
        if not dry:
            for estado in qs:
                self._info(f'  conv#{estado.conversacion_id} '
                           f'depto="{estado.departamento.nombre if estado.departamento else "—"}"')
                estado.en_handoff = False
                estado.finalizado = True
                estado.save(update_fields=['en_handoff', 'finalizado', 'actualizado'])
            self._ok(f'{n} handoffs liberados.')

    # ─────────────────────────────────────────────────────────────
    # 3. Nodos sin es_inicio y anomalías
    # ─────────────────────────────────────────────────────────────

    def _arreglar_nodos_inicio(self, dry):
        self._step('3. Arreglo de nodos de inicio por departamento')
        deptos = DepartamentoChatBot.objects.filter(status=True).order_by('id')
        if not deptos.exists():
            self._info('No hay departamentos.')
            return

        for d in deptos:
            raices = list(d.opciondepartamentochatbot_set.filter(
                status=True, opcion_padre__isnull=True
            ).order_by('orden', 'id'))

            if not raices:
                self._warn(f'Depto #{d.id} "{d.nombre}": sin nodos raíz activos.')
                continue

            hay_inicio = any(n.es_inicio for n in raices)
            if hay_inicio:
                # Verificar que el nodo inicio sea razonable
                inicio = next(n for n in raices if n.es_inicio)
                self._info(f'Depto #{d.id} "{d.nombre}": nodo inicial #{inicio.id} '
                           f'tipo={inicio.tipo_nodo} ✓')
                self._detectar_anomalias(d, raices)
                continue

            # Elegir un candidato: preferir 'menu', si no el primero por orden
            candidato = next((n for n in raices if n.tipo_nodo == 'menu'), None)
            if candidato is None:
                candidato = raices[0]

            self._warn(f'Depto #{d.id} "{d.nombre}": ningún nodo tiene es_inicio=True.')
            self._info(f'  → Candidato: #{candidato.id} "{candidato.nombre}" tipo={candidato.tipo_nodo}')
            if not dry:
                candidato.es_inicio = True
                candidato.save(update_fields=['es_inicio'])
                self._ok(f'Marcado #{candidato.id} como es_inicio=True.')

            self._detectar_anomalias(d, raices)

    def _detectar_anomalias(self, depto, raices):
        # Menús sin opciones configuradas
        for n in raices:
            if n.tipo_nodo == 'menu':
                ops = (n.config or {}).get('opciones') or []
                if not ops and not n.subopciones.filter(status=True).exists():
                    self._warn(f'  Nodo #{n.id} "{n.nombre}" es tipo=menu pero '
                               f'no tiene opciones ni hijos — el bot no podrá enrutar.')
            if n.tipo_nodo == 'http':
                if not n.endpoint_id:
                    self._warn(f'  Nodo #{n.id} "{n.nombre}" es tipo=http pero '
                               f'no tiene endpoint asignado.')
            if n.tipo_nodo == 'pregunta' and not n.variable_destino:
                self._warn(f'  Nodo #{n.id} "{n.nombre}" es tipo=pregunta pero '
                           f'no define variable_destino — no podrás usar la respuesta.')

    # ─────────────────────────────────────────────────────────────
    # 4. Reseed opcional
    # ─────────────────────────────────────────────────────────────

    def _reseed_estudiantil(self, dry, sesion_id):
        self._step(f'4. Reseed del depto "{SEED_NOMBRE}"')
        if dry:
            self._info('(dry-run: se omite reseed)')
            return
        # Llama al comando seed con --reset (que ya limpia estados asociados)
        args = ['--reset']
        if sesion_id:
            args += ['--sesion', str(sesion_id)]
        try:
            call_command('seed_centro_estudiantil', *args, stdout=self.stdout)
            self._ok('Reseed completado.')
        except Exception as e:
            self._warn(f'Reseed falló: {e}')

    # ─────────────────────────────────────────────────────────────
    # 5. Reporte final
    # ─────────────────────────────────────────────────────────────

    def _reporte_final(self):
        self._step('5. Resumen final')
        deptos = DepartamentoChatBot.objects.filter(status=True).order_by('id')
        self.stdout.write(f'  Deptos activos: {deptos.count()}')
        for d in deptos:
            inicio = d.nodo_inicio()
            ok_inicio = bool(inicio and inicio.tipo_nodo in ('menu', 'inicio', 'respuesta'))
            marca = '✓' if ok_inicio else '⚠'
            tipo_ini = inicio.tipo_nodo if inicio else '—'
            self.stdout.write(
                f'  {marca} #{d.id} "{d.nombre}"  inicio={tipo_ini}  '
                f'{"[DEFAULT]" if d.es_default else ""} '
                f'{"[ACTIVO]" if d.activo_tradicional else "[INACTIVO]"}'
            )

        n_estados = EstadoFlujoChatbot.objects.count()
        n_handoff = EstadoFlujoChatbot.objects.filter(en_handoff=True).count()
        n_fin = EstadoFlujoChatbot.objects.filter(finalizado=True).count()
        self.stdout.write(
            f'\n  Estados runtime: {n_estados} '
            f'(en_handoff: {n_handoff}, finalizados: {n_fin})'
        )

        self.stdout.write(self.style.SUCCESS('\n═══════════ LISTO ═══════════\n'))
