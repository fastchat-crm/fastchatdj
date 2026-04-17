"""Seeder: crea un set de plantillas WhatsApp tipicas de un restaurante para
la sesion con ID 19 (o el que se pase por linea de comandos).

Todas las plantillas se crean en estado BORRADOR (no se envian a Meta aun).
Despues, desde la UI o via MetaWhatsAppService().crear_plantilla_en_meta(),
se pueden someter una por una para aprobacion.

Uso:
    python scripts/seed_plantillas_restaurante.py
    python scripts/seed_plantillas_restaurante.py --sesion-id 25

    # Para eliminar las plantillas creadas por este seed (cleanup):
    python scripts/seed_plantillas_restaurante.py --limpiar

Las plantillas siguen las mejores practicas de Meta:
- UTILITY para transaccionales (confirmaciones, recordatorios, estados de pedido).
- MARKETING para promociones y engagement (menu del dia, ofertas, agradecimientos).
- Los nombres son slugs en minuscula con guiones bajos (requisito de Meta).
- Los placeholders usan {{1}}, {{2}}, {{3}}, ... en orden estricto (Meta lo exige).
"""
import argparse
import os
import sys

from django.core.wsgi import get_wsgi_application

# Bootstrap Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')
application = get_wsgi_application()

from whatsapp.models import PlantillaWhatsApp, SesionWhatsApp


# ---------------------------------------------------------------------------
# Catalogo de plantillas para restaurante
# ---------------------------------------------------------------------------
# Cada entrada tiene exactamente los campos del modelo PlantillaWhatsApp.
# Los {{N}} se cuentan en orden de aparicion en el cuerpo y se reportan en
# variables_json para que la UI pueda renderizar hints.
# ---------------------------------------------------------------------------

PLANTILLAS_RESTAURANTE = [
    {
        'nombre': 'confirmacion_reserva',
        'idioma': 'es',
        'categoria': 'UTILITY',
        'header_tipo': 'TEXT',
        'header_contenido': '✅ Reserva confirmada',
        'cuerpo': (
            'Hola {{1}}, tu reserva en *Mi Restaurante* esta confirmada.\n\n'
            '📅 Fecha: {{2}}\n'
            '🕐 Hora: {{3}}\n'
            '👥 Personas: {{4}}\n'
            '📍 Direccion: {{5}}\n\n'
            'Si necesitas cambiar o cancelar, responde a este mensaje con anticipacion. '
            '¡Te esperamos!'
        ),
        'footer': 'Mi Restaurante · Gracias por elegirnos',
        'botones_json': [
            {'type': 'QUICK_REPLY', 'text': 'Modificar reserva'},
            {'type': 'QUICK_REPLY', 'text': 'Cancelar reserva'},
        ],
        'variables_json': [
            {'nombre': 'cliente',   'ejemplo': 'Hector'},
            {'nombre': 'fecha',     'ejemplo': '20/04/2026'},
            {'nombre': 'hora',      'ejemplo': '20:00'},
            {'nombre': 'personas',  'ejemplo': '4'},
            {'nombre': 'direccion', 'ejemplo': 'Av. 6 de Diciembre N24-310'},
        ],
    },

    {
        'nombre': 'recordatorio_reserva',
        'idioma': 'es',
        'categoria': 'UTILITY',
        'header_tipo': 'NONE',
        'header_contenido': None,
        'cuerpo': (
            'Hola {{1}} 👋, te recordamos tu reserva de hoy a las {{2}} '
            'para {{3}} personas en *Mi Restaurante*.\n\n'
            'Estaremos esperandote. Si tu plan cambio, avisanos para liberar la mesa.'
        ),
        'footer': 'Mi Restaurante',
        'botones_json': [
            {'type': 'QUICK_REPLY', 'text': 'Confirmar asistencia'},
            {'type': 'QUICK_REPLY', 'text': 'No podre ir'},
        ],
        'variables_json': [
            {'nombre': 'cliente',  'ejemplo': 'Hector'},
            {'nombre': 'hora',     'ejemplo': '20:00'},
            {'nombre': 'personas', 'ejemplo': '4'},
        ],
    },

    {
        'nombre': 'confirmacion_pedido_delivery',
        'idioma': 'es',
        'categoria': 'UTILITY',
        'header_tipo': 'TEXT',
        'header_contenido': '🛵 Pedido #{{1}} recibido',
        'cuerpo': (
            'Gracias {{2}}! Confirmamos tu pedido:\n\n'
            '{{3}}\n\n'
            '💰 Total: ${{4}}\n'
            '🕐 Tiempo estimado: {{5}} minutos\n'
            '📍 Entrega en: {{6}}\n\n'
            'Te avisamos cuando salga de cocina.'
        ),
        'footer': 'Mi Restaurante · Delivery',
        'botones_json': [
            {'type': 'QUICK_REPLY', 'text': 'Ver estado del pedido'},
        ],
        'variables_json': [
            {'nombre': 'numero_pedido', 'ejemplo': '1024'},
            {'nombre': 'cliente',       'ejemplo': 'Hector'},
            {'nombre': 'resumen_items', 'ejemplo': '2x Pizza Margherita, 1x Ensalada Cesar'},
            {'nombre': 'total',         'ejemplo': '28.50'},
            {'nombre': 'minutos',       'ejemplo': '35'},
            {'nombre': 'direccion',     'ejemplo': 'Calle Bolivar 123'},
        ],
    },

    {
        'nombre': 'pedido_en_camino',
        'idioma': 'es',
        'categoria': 'UTILITY',
        'header_tipo': 'NONE',
        'header_contenido': None,
        'cuerpo': (
            '🛵 ¡Tu pedido #{{1}} ya salio! Llega en aproximadamente {{2}} minutos.\n\n'
            'El repartidor es {{3}} y lleva uniforme de Mi Restaurante.'
        ),
        'footer': None,
        'botones_json': [
            {'type': 'URL',          'text': 'Rastrear en vivo', 'url': 'https://mi-restaurante.com/seguimiento/{{1}}'},
            {'type': 'PHONE_NUMBER', 'text': 'Llamar al local',  'phone_number': '+593987654321'},
        ],
        'variables_json': [
            {'nombre': 'numero_pedido', 'ejemplo': '1024'},
            {'nombre': 'minutos',       'ejemplo': '12'},
            {'nombre': 'repartidor',    'ejemplo': 'Luis'},
        ],
    },

    {
        'nombre': 'menu_del_dia',
        'idioma': 'es',
        'categoria': 'MARKETING',
        'header_tipo': 'TEXT',
        'header_contenido': '🍽️ Menu del dia — {{1}}',
        'cuerpo': (
            '¡Buen provecho {{2}}! Hoy en *Mi Restaurante*:\n\n'
            '{{3}}\n\n'
            '💵 Precio especial: ${{4}}\n\n'
            'Valido solo hoy hasta las {{5}}. Reserva tu mesa o pide delivery antes que se acaben.'
        ),
        'footer': 'Mi Restaurante · Cocina tradicional',
        'botones_json': [
            {'type': 'QUICK_REPLY', 'text': 'Reservar mesa'},
            {'type': 'QUICK_REPLY', 'text': 'Pedir delivery'},
            {'type': 'URL',         'text': 'Ver menu completo', 'url': 'https://mi-restaurante.com/menu'},
        ],
        'variables_json': [
            {'nombre': 'fecha',        'ejemplo': '20 de abril'},
            {'nombre': 'cliente',      'ejemplo': 'Hector'},
            {'nombre': 'platos',       'ejemplo': 'Entrada: Sopa de quinua · Fuerte: Lomo saltado con arroz · Postre: Flan'},
            {'nombre': 'precio',       'ejemplo': '6.50'},
            {'nombre': 'hora_limite',  'ejemplo': '22:00'},
        ],
    },

    {
        'nombre': 'promocion_fin_de_semana',
        'idioma': 'es',
        'categoria': 'MARKETING',
        'header_tipo': 'IMAGE',
        'header_contenido': 'https://mi-restaurante.com/static/promo-finde.jpg',
        'cuerpo': (
            '🎉 ¡Promo fin de semana, {{1}}!\n\n'
            '{{2}} con *{{3}}% de descuento*.\n\n'
            'Valido del {{4}} al {{5}}. Solo presentando este mensaje al ordenar.'
        ),
        'footer': 'Sujeto a disponibilidad. No acumulable.',
        'botones_json': [
            {'type': 'QUICK_REPLY', 'text': 'Quiero reservar'},
            {'type': 'URL',         'text': 'Ver condiciones', 'url': 'https://mi-restaurante.com/promo'},
        ],
        'variables_json': [
            {'nombre': 'cliente',       'ejemplo': 'Hector'},
            {'nombre': 'item_promo',    'ejemplo': 'Parrillada para 2'},
            {'nombre': 'porcentaje',    'ejemplo': '25'},
            {'nombre': 'fecha_inicio',  'ejemplo': '19/04'},
            {'nombre': 'fecha_fin',     'ejemplo': '21/04'},
        ],
    },

    {
        'nombre': 'encuesta_post_visita',
        'idioma': 'es',
        'categoria': 'MARKETING',
        'header_tipo': 'NONE',
        'header_contenido': None,
        'cuerpo': (
            '¡Gracias por visitarnos {{1}}! 🙏\n\n'
            'Nos encantaria saber como estuvo tu experiencia. '
            'Si tienes un minuto, califica tu visita respondiendo este mensaje. '
            'Tu opinion nos ayuda a seguir mejorando.'
        ),
        'footer': 'Mi Restaurante',
        'botones_json': [
            {'type': 'QUICK_REPLY', 'text': '⭐⭐⭐⭐⭐ Excelente'},
            {'type': 'QUICK_REPLY', 'text': '⭐⭐⭐ Regular'},
            {'type': 'QUICK_REPLY', 'text': '⭐ Tuve problemas'},
        ],
        'variables_json': [
            {'nombre': 'cliente', 'ejemplo': 'Hector'},
        ],
    },

    {
        'nombre': 'cumpleanos_cliente',
        'idioma': 'es',
        'categoria': 'MARKETING',
        'header_tipo': 'TEXT',
        'header_contenido': '🎂 ¡Feliz cumpleanos {{1}}!',
        'cuerpo': (
            'De parte de todo el equipo de *Mi Restaurante*, te deseamos un cumple increible.\n\n'
            'Para celebrarlo, te regalamos *{{2}}* en tu proxima visita este mes. '
            'Solo muestra este mensaje al mesero.'
        ),
        'footer': 'Valido hasta {{3}}. Un regalo por persona.',
        'botones_json': [
            {'type': 'QUICK_REPLY', 'text': 'Reservar para celebrar'},
        ],
        'variables_json': [
            {'nombre': 'cliente',        'ejemplo': 'Hector'},
            {'nombre': 'regalo',         'ejemplo': 'un postre gratis'},
            {'nombre': 'fecha_vencimiento', 'ejemplo': '30/04/2026'},
        ],
    },
]


# ---------------------------------------------------------------------------
# Logica del seeder
# ---------------------------------------------------------------------------

def ejecutar(sesion_id: int, limpiar: bool = False):
    try:
        sesion = SesionWhatsApp.objects.select_related('config_meta').get(id=sesion_id)
    except SesionWhatsApp.DoesNotExist:
        print(f"ERROR: La sesion id={sesion_id} no existe.")
        return 1

    if sesion.proveedor != 'meta':
        print(f"ERROR: La sesion id={sesion_id} tiene proveedor='{sesion.proveedor}', se requiere 'meta'.")
        return 1

    config = getattr(sesion, 'config_meta', None)
    if not config:
        print(f"ERROR: La sesion id={sesion_id} no tiene ConfigMeta asociada.")
        print("       Configurala primero en /whatsapp/sesiones/?action=change&pk={}".format(sesion_id))
        return 1

    print(f"\nSesion objetivo:")
    print(f"  ID:       {sesion.id}")
    print(f"  Nombre:   {sesion.nombre or '(sin nombre)'}")
    print(f"  Numero:   {sesion.numero or '(sin numero)'}")
    print(f"  WABA:     {config.waba_id}")
    print(f"  Phone ID: {config.phone_number_id}\n")

    if limpiar:
        nombres = [p['nombre'] for p in PLANTILLAS_RESTAURANTE]
        qs = PlantillaWhatsApp.objects.filter(config_meta=config, nombre__in=nombres)
        borradas = qs.count()
        qs.delete()
        print(f"Eliminadas {borradas} plantilla(s) del set de restaurante.")
        return 0

    creadas, actualizadas, saltadas = 0, 0, 0
    for spec in PLANTILLAS_RESTAURANTE:
        existente = PlantillaWhatsApp.objects.filter(
            config_meta=config, nombre=spec['nombre'], idioma=spec['idioma']
        ).first()

        if existente:
            # Solo actualizamos si esta en BORRADOR (no pisamos lo que ya esta en Meta).
            if existente.estado_meta == 'BORRADOR':
                for k, v in spec.items():
                    setattr(existente, k, v)
                existente.save()
                actualizadas += 1
                print(f"  ↻ Actualizada: {spec['nombre']} ({spec['idioma']})")
            else:
                saltadas += 1
                print(f"  ⊘ Saltada ({existente.get_estado_meta_display()}): {spec['nombre']}")
            continue

        PlantillaWhatsApp.objects.create(
            config_meta=config,
            estado_meta='BORRADOR',
            **spec,
        )
        creadas += 1
        print(f"  ✓ Creada: {spec['nombre']} [{spec['categoria']}]")

    print(f"\nResumen: {creadas} creadas · {actualizadas} actualizadas · {saltadas} saltadas (ya en Meta).")
    print(f"\nProximos pasos:")
    print(f"  1. Revisa el listado en /whatsapp/plantillas/?sesion={sesion.id}")
    print(f"  2. Edita si necesitas ajustar algun cuerpo o header.")
    print(f"  3. 'Someter a Meta' por cada plantilla para que empiece el proceso de aprobacion.")
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sesion-id', type=int, default=19,
                        help='ID de la sesion Meta donde crear las plantillas (default: 19)')
    parser.add_argument('--limpiar', action='store_true',
                        help='Elimina las plantillas del set en lugar de crearlas')
    args = parser.parse_args()

    sys.exit(ejecutar(args.sesion_id, args.limpiar))
