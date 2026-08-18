"""Normaliza conversaciones de canales sociales (Messenger / TikTok).

Dos estados anómalos que las dejaban invisibles en el inbox (el badge de
"Abiertas" las contaba pero el listado, que usa `sin_expirar`, las ocultaba):

1. Abiertas con `fecha_hora_expira` en el pasado: Messenger/TikTok se
   finalizan a mano (no hay cierre por inactividad), pero conversaciones
   creadas antes del fix de `obtener_o_crear_activa` heredaron la ventana
   `min_sesion` de la sesión. → se limpia `fecha_hora_expira=None`.
2. Inconsistentes: `conversacion_finalizada=True` con `estado_conversacion=0`
   — no aparecen ni en abiertas ni en finalizadas. → se marca
   `estado_conversacion=1` para que al menos salgan en finalizadas.

Uso:
    python manage.py normalizar_conversaciones_social            # aplica
    python manage.py normalizar_conversaciones_social --dry-run  # solo muestra
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from whatsapp.models import ConversacionWhatsApp

PROVEEDORES_SOCIALES = ('messenger', 'tiktok')


class Command(BaseCommand):
    help = 'Repara conversaciones Messenger/TikTok invisibles (expiradas sin cerrar o en estado inconsistente).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Mostrar lo que se corregiría sin escribir nada.')

    def handle(self, *args, **opts):
        ahora = timezone.now()

        atascadas = ConversacionWhatsApp.objects.filter(
            status=True,
            estado_conversacion=0,
            conversacion_finalizada=False,
            fecha_hora_expira__lt=ahora,
            contacto__sesion__proveedor__in=PROVEEDORES_SOCIALES,
        )
        inconsistentes = ConversacionWhatsApp.objects.filter(
            status=True,
            estado_conversacion=0,
            conversacion_finalizada=True,
            contacto__sesion__proveedor__in=PROVEEDORES_SOCIALES,
        )

        for conv in atascadas.select_related('contacto', 'contacto__sesion'):
            self.stdout.write(
                f'  abierta-expirada #{conv.id} ({conv.contacto.sesion.proveedor}, '
                f'contacto {conv.contacto_id}, expiraba {conv.fecha_hora_expira:%Y-%m-%d %H:%M})'
            )
        for conv in inconsistentes.select_related('contacto', 'contacto__sesion'):
            self.stdout.write(
                f'  inconsistente #{conv.id} ({conv.contacto.sesion.proveedor}, '
                f'finalizada=True con estado abierto)'
            )

        if opts['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'Dry-run: {atascadas.count()} abiertas-expiradas y '
                f'{inconsistentes.count()} inconsistentes. Nada se modificó.'
            ))
            return

        n_expira = atascadas.update(fecha_hora_expira=None)
        n_incons = inconsistentes.update(estado_conversacion=1)
        self.stdout.write(self.style.SUCCESS(
            f'Listo: {n_expira} conversaciones reactivadas en el inbox '
            f'(fecha_hora_expira=None) y {n_incons} inconsistentes movidas a finalizadas.'
        ))
