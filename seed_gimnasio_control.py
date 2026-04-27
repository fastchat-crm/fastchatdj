"""Seed: Departamento 'Gimnasio Control' con flujo Sandow Fitness completo.

Crea (o reemplaza) el depto + todo el árbol de OpcionDepartamentoChatBot.
Cada nodo está marcado con tipo_nodo correcto para que la integración Meta
emita interactive buttons / list / cta_url cuando corresponda:

    tipo_nodo='menu'      → emite 'interactive button' (≤3 hijos) o 'list' (>3)
    tipo_nodo='respuesta' → emite mensaje 'text' plano
    tipo_nodo='handoff'   → cierra a humano
    tipo_nodo='fin'       → cierra el flujo
    config_json soporta extras Meta:
        {"meta_type": "cta_url", "url": "...", "display_text": "💳 Pagar"}
        {"meta_type": "location", "lat": -2.13, "lng": -79.58, "name": "...", "address": "..."}

Uso:
    python seed_gimnasio_control.py
"""
import os
import sys
import django

# Django setup standalone
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')
django.setup()

from crm.models import DepartamentoChatBot, OpcionDepartamentoChatBot  # noqa: E402


# ─────────────────── Datos del flujo ───────────────────
NOMBRE_DEPTO = 'Gimnasio Control'
COLOR = '#16a34a'
SALUDO = (
    '¡Hola! 🌙 Gracias por escribir a Sandow Fitness.\n\n'
    'En este momento estamos fuera de nuestro horario de atención (Lun-Sab 5:00 AM - 11:00 PM). 🔋\n'
    'Si querés ver nuestros precios al instante, tocá el botón de abajo.'
)

ARBOL = [
    {
        'tipo': 'menu', 'nombre': 'Saludo inicial', 'es_inicio': True,
        'respuesta': SALUDO,
        'hijos': [
            {
                'tipo': 'menu', 'nombre': '🏆 Ver Precios', 'boton_id': 'ver_precios',
                'respuesta': (
                    '¡Excelente! En Sandow Fitness tenemos todo listo para tu cambio físico '
                    'en nuestras dos sedes de Milagro. 🏋💪\n\n'
                    'Selecciona tu sede o revisá las promociones.'
                ),
                'hijos': [
                    {
                        'tipo': 'menu', 'nombre': '📍 Sede 1 García', 'boton_id': 'sede_garcia',
                        'respuesta': (
                            '🏢 *SEDE 1 - Planes y Horarios*\n'
                            '_Todos los planes incluyen: Wifi, casilleros, vestidores, duchas e instructores._ 🏋\n\n'
                            '👑 *Plan Elite X ($35)* — 5:30AM-10:00PM — 2 SEDES + CrossFit\n'
                            '🥇 *Plan Elite + ($27)* — 5:30AM-10:00PM — Musculación, Funcional, Box, Dance\n'
                            '⚡ *Plan Pro Move ($21)* — 5:30AM-1:00PM — Musculación, Funcional, Box, Dance\n'
                            '💪 *Plan Base Fit ($18)* — 11:00AM-2:00PM — Solo Musculación\n\n'
                            '🥇 Plan Anual $180 · 💪 Semestral $105 · ⚡ 4 Meses $85\n\n'
                            '¿Cómo te gustaría pagar?'
                        ),
                        'hijos': [
                            {
                                'tipo': 'respuesta', 'nombre': '💳 Tarjeta de Crédito',
                                'boton_id': 'pago_tarjeta_sede1',
                                'respuesta': (
                                    '¡Excelente elección! 💳 Pagar con tarjeta es rápido y 100% seguro.\n'
                                    'Tocá el botón "Pagar Membresía" — te llevará a PayPhone para que '
                                    'ingreses el valor exacto.'
                                ),
                                'config': {
                                    'meta_type': 'cta_url',
                                    'display_text': '💳 Pagar Membresía',
                                    'url': 'https://pay.payphonetodoesposible.com/sandowfitness',
                                },
                                'hijos': [
                                    {
                                        'tipo': 'menu', 'nombre': 'Solicitar comprobante',
                                        'respuesta': (
                                            '⚠️ MUY IMPORTANTE: Apenas termines de pagar, hacele captura '
                                            'al recibo y tocá el botón abajo para activar tu membresía. 👇'
                                        ),
                                        'hijos': [
                                            {
                                                'tipo': 'handoff', 'nombre': '📸 Enviar Comprobante',
                                                'boton_id': 'enviar_comprobante_tarjeta',
                                                'respuesta': (
                                                    '¡Mil gracias por elegir Sandow Fitness! 😊💪 '
                                                    'Una asesora te atenderá en breve para activar tu plan.'
                                                ),
                                            },
                                        ],
                                    },
                                ],
                            },
                            {
                                'tipo': 'menu', 'nombre': '🏦 Transferencia',
                                'boton_id': 'pago_transferencia_sede1',
                                'respuesta': (
                                    '¡Perfecto! 🤝 Acá tenés nuestros datos sin recargos:\n\n'
                                    '🏦 Banco Produbanco (Cta Corriente)\n'
                                    '👤 Sandow Fitness SAS\n'
                                    '📋 RUC: 0993367918001\n'
                                    '💳 Cuenta: *27059002064*\n\n'
                                    'Una vez transferido, tocá el botón para enviarnos el comprobante.'
                                ),
                                'hijos': [
                                    {
                                        'tipo': 'handoff', 'nombre': '📸 Enviar Comprobante',
                                        'boton_id': 'enviar_comprobante_transf',
                                        'respuesta': 'Listo! Te conecto con un asesor para validar el pago. 💪',
                                    },
                                ],
                            },
                            {
                                'tipo': 'respuesta', 'nombre': '📍 Ver Ubicación GPS',
                                'boton_id': 'ver_ubicacion_sede1',
                                'respuesta': '📍 Sandow Fitness · Sede 1 García\nAv. García Moreno y 9 de Octubre, Milagro.',
                                'config': {
                                    'meta_type': 'location',
                                    'lat': -2.1325, 'lng': -79.5878,
                                    'name': 'Sandow Fitness - Sede 1 García',
                                    'address': 'Av. García Moreno y 9 de Octubre, Milagro, Guayas',
                                },
                            },
                        ],
                    },
                    {
                        'tipo': 'menu', 'nombre': '📍 Sede 2 Pdte.', 'boton_id': 'sede_pdte',
                        'respuesta': (
                            '🏢 *SEDE 2 PDTE. - Planes y Horarios*\n'
                            'Mismos planes, mismas comodidades. Elegí cómo querés pagar.'
                        ),
                        'hijos': [
                            {
                                'tipo': 'handoff', 'nombre': '👤 Hablar con asesor',
                                'boton_id': 'asesor_sede2',
                                'respuesta': 'Te conecto con un asesor para Sede 2.',
                            },
                        ],
                    },
                    {
                        'tipo': 'respuesta', 'nombre': '🎁 Ver Promociones', 'boton_id': 'ver_promos',
                        'respuesta': (
                            '🎁 *Promo de la semana*\n'
                            '· 2x1 en plan Pro Move (trae a un amigo)\n'
                            '· Plan Anual con 15% off → $153\n'
                            '· Inscripción gratis pagando con tarjeta\n\n'
                            'Válida hasta el domingo. ¡Aprovechá!'
                        ),
                    },
                ],
            },
            {
                'tipo': 'handoff', 'nombre': '👤 Hablar con asesor',
                'boton_id': 'hablar_asesor',
                'respuesta': 'Te derivo con un asesor humano. ¡Un momento por favor!',
            },
        ],
    },
]


# ─────────────────── Lógica seed ───────────────────
def crear_arbol(dep, items, padre=None):
    creados = 0
    for orden, item in enumerate(items, start=1):
        op = OpcionDepartamentoChatBot(
            departamento=dep,
            opcion_padre=padre,
            tipo_nodo=item.get('tipo', 'respuesta'),
            nombre=(item.get('nombre') or '')[:100],
            respuesta=item.get('respuesta', ''),
            boton_id=item.get('boton_id', ''),
            es_inicio=bool(item.get('es_inicio', False)) and padre is None,
            orden=orden,
            config=item.get('config', {}) or {},
        )
        op.save()
        creados += 1
        if item.get('hijos'):
            creados += crear_arbol(dep, item['hijos'], padre=op)
    return creados


def main():
    # 1. Crear o reusar el depto
    dep = DepartamentoChatBot.objects.filter(nombre=NOMBRE_DEPTO).first()
    if dep:
        print(f"Depto '{NOMBRE_DEPTO}' ya existe (id={dep.id}). Limpiando opciones previas…")
        OpcionDepartamentoChatBot.objects.filter(departamento=dep).update(status=False)
        dep.color = COLOR
        dep.mensaje_saludo = SALUDO
        dep.save()
    else:
        dep = DepartamentoChatBot(
            nombre=NOMBRE_DEPTO,
            color=COLOR,
            mensaje_saludo=SALUDO,
        )
        dep.save()
        print(f"Depto creado: '{NOMBRE_DEPTO}' (id={dep.id}).")

    # 2. Crear opciones
    creados = crear_arbol(dep, ARBOL)
    print(f"OK · {creados} opciones cargadas en depto id={dep.id}.")
    print(f"Editá en: /crm/departamentos_chatbots/?action=change&id={dep.id}&full=1")


if __name__ == '__main__':
    main()
