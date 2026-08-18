"""Reprocesa eventos webhook Meta que quedaron sin procesar.

Caso de uso principal: eventos rechazados por `firma_hmac_invalida` cuando el
App Secret estaba mal configurado o la validación tenía un bug (como la copia
local de `_validar_firma_hmac` que no aceptaba la lista de
`get_meta_app_secrets`). El payload completo quedó guardado en
`EventoMetaRecibido`, así que los mensajes se pueden recuperar enrutándolos
por el mismo pipeline del webhook (`_enrutar_payload`).

Uso:
    python manage.py reprocesar_eventos_meta                # firma_hmac_invalida últimos 7 días
    python manage.py reprocesar_eventos_meta --dias 30      # ampliar rango
    python manage.py reprocesar_eventos_meta --evento-id 8478
    python manage.py reprocesar_eventos_meta --todos-los-errores
    python manage.py reprocesar_eventos_meta --dry-run      # solo listar, sin procesar

Notas:
- Solo toma eventos con `procesado=False`, así que correrlo dos veces no
  duplica: cada evento recuperado queda marcado `procesado=True`.
- `firma_valida` se deja como está (False): la firma nunca llegó a
  verificarse realmente y el body crudo ya no existe para recomputar el HMAC.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from whatsapp.models import ConfigMeta, EventoMetaRecibido


class Command(BaseCommand):
    help = 'Reprocesa eventos Meta no procesados (por defecto los rechazados por firma_hmac_invalida).'

    def add_arguments(self, parser):
        parser.add_argument('--dias', type=int, default=7,
                            help='Rango hacia atrás en días (default 7).')
        parser.add_argument('--evento-id', type=int, default=None,
                            help='Reprocesar un solo evento por id (ignora --dias y filtros de error).')
        parser.add_argument('--todos-los-errores', action='store_true',
                            help='Incluir todo evento no procesado, no solo firma_hmac_invalida.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Listar lo que se reprocesaría sin ejecutar nada.')

    def handle(self, *args, **opts):
        from whatsapp.meta_webhook_view import _enrutar_payload, _extraer_phone_number_id

        if opts['evento_id']:
            qs = EventoMetaRecibido.objects.filter(id=opts['evento_id'])
        else:
            desde = timezone.now() - timedelta(days=opts['dias'])
            qs = EventoMetaRecibido.objects.filter(procesado=False, recibido_en__gte=desde)
            if not opts['todos_los_errores']:
                qs = qs.filter(error_procesamiento='firma_hmac_invalida')
        qs = qs.order_by('recibido_en', 'id')

        total = qs.count()
        if not total:
            self.stdout.write(self.style.WARNING('No hay eventos que reprocesar con esos filtros.'))
            return

        self.stdout.write(f'Eventos a reprocesar: {total}')
        ok = fallidos = sin_config = 0

        for evento in qs.iterator():
            payload = evento.payload_json or {}
            config = evento.config_meta
            if not config:
                phone_number_id = _extraer_phone_number_id(payload)
                config = ConfigMeta.objects.filter(phone_number_id=phone_number_id).first() if phone_number_id else None
                if config and not opts['dry_run']:
                    evento.config_meta = config
                    evento.save(update_fields=['config_meta'])
            if not config:
                sin_config += 1
                self.stdout.write(self.style.WARNING(
                    f'  #{evento.id} {evento.tipo_evento} — sin ConfigMeta resoluble, se omite.'
                ))
                continue

            if opts['dry_run']:
                ok += 1
                self.stdout.write(
                    f'  #{evento.id} {evento.tipo_evento} recibido {evento.recibido_en:%Y-%m-%d %H:%M:%S} '
                    f'(config {config.phone_number_id}) — se reprocesaría'
                )
                continue

            try:
                _enrutar_payload(payload, config, evento)
                evento.procesado = True
                evento.error_procesamiento = ''
                evento.save(update_fields=['procesado', 'error_procesamiento'])
                ok += 1
                self.stdout.write(self.style.SUCCESS(
                    f'  #{evento.id} {evento.tipo_evento} — reprocesado OK'
                ))
            except Exception as e:
                fallidos += 1
                evento.error_procesamiento = f'reproceso_fallido: {e}'[:1000]
                evento.save(update_fields=['error_procesamiento'])
                self.stdout.write(self.style.ERROR(
                    f'  #{evento.id} {evento.tipo_evento} — error: {e}'
                ))

        verbo = 'se reprocesarían' if opts['dry_run'] else 'reprocesados'
        self.stdout.write(self.style.SUCCESS(
            f'Listo: {ok} {verbo}, {fallidos} con error, {sin_config} sin config.'
        ))
