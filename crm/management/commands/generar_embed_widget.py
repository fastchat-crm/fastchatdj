"""Genera el embed key y el snippet del widget de chat para un agente.

Onboarding de un cliente nuevo ("su propia pagina con su propia API"):
  python manage.py generar_embed_widget --agente-id 22
  python manage.py generar_embed_widget --agente-id 22 --origins https://cliente.com https://www.cliente.com
  python manage.py generar_embed_widget --agente-id 22 --base https://mi-dominio.com

Imprime: el embed key firmado, el <script> para incrustar, y la URL de la
pagina de chat autonoma. No toca la BD ni expone credenciales.
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Genera el embed key y el snippet del widget de chat para un agente.'

    def add_arguments(self, parser):
        parser.add_argument('--agente-id', type=int, required=True, help='ID del AgentesIA.')
        parser.add_argument('--origins', nargs='*', default=None,
                            help='Dominios permitidos (opcional). Restringe el widget a esos origenes.')
        parser.add_argument('--base', type=str, default='https://TU-DOMINIO',
                            help='Base URL publica del servidor (para armar el snippet y la pagina).')

    def handle(self, *args, **opts):
        from crm.models import AgentesIA
        from crm.chat_widget import generar_embed_key

        agente = AgentesIA.objects.filter(pk=opts['agente_id'], status=True).first()
        if not agente:
            raise CommandError(f"No existe un AgentesIA activo con id={opts['agente_id']}.")

        apikey = agente.apikey.filter(estado=True, status=True).first()
        if not apikey:
            self.stderr.write(self.style.WARNING(
                'AVISO: el agente no tiene ApiKeyIA activa; el widget respondera con error '
                'hasta que se le asocie una key.'
            ))

        key = generar_embed_key(agente.id, origins=opts.get('origins'))
        base = (opts['base'] or '').rstrip('/')

        self.stdout.write(self.style.SUCCESS(f'\nAgente: {agente.nombre} (id={agente.id})'))
        if apikey:
            self.stdout.write(f'Proveedor/Modelo: {apikey.get_proveedor_display()} · {apikey.modelo or "(default)"}')
        if opts.get('origins'):
            self.stdout.write(f'Origenes permitidos: {", ".join(opts["origins"])}')

        self.stdout.write('\n' + '=' * 68)
        self.stdout.write('EMBED KEY (publico, va en la pagina del cliente):')
        self.stdout.write('=' * 68)
        self.stdout.write(key)

        self.stdout.write('\n' + '=' * 68)
        self.stdout.write('SNIPPET para incrustar en cualquier pagina:')
        self.stdout.write('=' * 68)
        self.stdout.write(
            f'<script src="{base}/chat-widget/embed.js"\n'
            f'        data-embed-key="{key}"\n'
            f'        data-titulo="{agente.nombre}"\n'
            f'        data-color="#1b6ec2"\n'
            f'        data-bienvenida="¡Hola! ¿En qué puedo ayudarte?"></script>'
        )

        self.stdout.write('\n' + '=' * 68)
        self.stdout.write('PAGINA DE CHAT AUTONOMA (una por cliente):')
        self.stdout.write('=' * 68)
        self.stdout.write(f'{base}/chat/{key}/')
        self.stdout.write('')
