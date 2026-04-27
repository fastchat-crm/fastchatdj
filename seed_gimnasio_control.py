"""Seed: Departamento 'Gimnasio Control' con flujo Sandow Fitness completo.

Crea (o reemplaza) el depto + todo el árbol de OpcionDepartamentoChatBot.

Tipos de nodo válidos del modelo (usar SOLO estos):
    'menu'      → presenta opciones, ESPERA input. Hijos = botones (≤3) o lista (≤10).
    'respuesta' → envía texto y avanza al primer hijo (o termina si no hay).
                  Si tiene config.cta_url, manda interactive cta_url (botón URL).
    'handoff'   → deriva a humano (estado.en_handoff=True).
    'fin'       → cierra el flujo.
    'pregunta','http','condicional','switch','set_variable','esperar' (avanzados).

Convenciones para Meta interactive:
    config={'cta_url': 'https://...', 'cta_display_text': '📸 Subir'}  → botón URL
    config={'mensaje': '...'}    → override del texto del nodo (opcional)
    config={'opciones': [...]}   → lista custom de opciones (opcional)

Nota sobre cadenas como "Pagar → Subir Comprobante":
    Meta solo permite 1 botón CTA URL por mensaje. Para 2 acciones secuenciales
    (pagar + después subir recibo) se usan DOS nodos `respuesta` encadenados.
    El motor envía el primero, avanza al hijo, envía el segundo, fin.

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

# Placeholders — reemplazá con URLs reales antes de producción.
URL_PAYPHONE_SANDOW = 'https://pay.payphonetodoesposible.com/sandowfitness'
URL_FORM_COMPROBANTE = 'https://docs.google.com/forms/d/e/REEMPLAZAR/viewform'
URL_MAPS_SEDE1 = 'https://maps.google.com/?q=-2.1325,-79.5878'

ARBOL = [
    {
        'tipo': 'menu', 'nombre': 'Saludo inicial', 'es_inicio': True,
        'respuesta': SALUDO,
        'hijos': [
            # ───────── Rama VER PRECIOS ─────────
            {
                'tipo': 'menu', 'nombre': '🏆 Ver Precios', 'boton_id': 'ver_precios',
                'respuesta': (
                    '¡Excelente! En Sandow Fitness tenemos todo listo para tu cambio físico '
                    'en nuestras dos sedes de Milagro. 🏋💪\n\n'
                    'Selecciona tu sede o revisá las promociones.'
                ),
                'hijos': [
                    # Sede 1
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
                            # Tarjeta de crédito → cadena de 2 nodos: pagar + subir comprobante
                            {
                                'tipo': 'respuesta', 'nombre': '💳 Tarjeta de Crédito',
                                'boton_id': 'pago_tarjeta_sede1',
                                'respuesta': (
                                    '¡Excelente elección! 💳 Pagar con tarjeta es rápido y 100% seguro.\n'
                                    'Tocá el botón de abajo — te llevará a PayPhone para que ingreses '
                                    'el valor exacto de tu plan.'
                                ),
                                'config': {
                                    'cta_url': URL_PAYPHONE_SANDOW,
                                    'cta_display_text': '💳 Pagar Membresía',
                                },
                                # Después de mandar el CTA pagar, encadenamos el de subir comprobante.
                                'hijos': [
                                    {
                                        'tipo': 'respuesta',
                                        'nombre': 'Comprobante post-tarjeta',
                                        'respuesta': (
                                            '⚠️ *MUY IMPORTANTE:* apenas termines de pagar, hacele captura '
                                            'al recibo y subilo desde el botón. Una asesora activa tu '
                                            'membresía en breve. 💪'
                                        ),
                                        'config': {
                                            'cta_url': URL_FORM_COMPROBANTE,
                                            'cta_display_text': '📸 Subir Comprobante',
                                        },
                                    },
                                ],
                            },
                            # Transferencia → datos bancarios + comprobante
                            {
                                'tipo': 'respuesta', 'nombre': '🏦 Transferencia',
                                'boton_id': 'pago_transferencia_sede1',
                                'respuesta': (
                                    '¡Perfecto! 🤝 Acá tenés nuestros datos sin recargos:\n\n'
                                    '🏦 Banco Produbanco (Cta Corriente)\n'
                                    '👤 Sandow Fitness SAS\n'
                                    '📋 RUC: 0993367918001\n'
                                    '💳 Cuenta: *27059002064*\n\n'
                                    'Una vez transferido, tocá el botón para enviarnos el comprobante.'
                                ),
                                'config': {
                                    'cta_url': URL_FORM_COMPROBANTE,
                                    'cta_display_text': '📸 Subir Comprobante',
                                },
                            },
                            # Ubicación GPS — cta_url con Google Maps
                            {
                                'tipo': 'respuesta', 'nombre': '📍 Ver Ubicación GPS',
                                'boton_id': 'ver_ubicacion_sede1',
                                'respuesta': (
                                    '📍 *Sandow Fitness · Sede 1 García*\n'
                                    'Av. García Moreno y 9 de Octubre, Milagro, Guayas\n\n'
                                    'Tocá el botón para abrir en Google Maps.'
                                ),
                                'config': {
                                    'cta_url': URL_MAPS_SEDE1,
                                    'cta_display_text': '🗺️ Abrir en Maps',
                                },
                            },
                        ],
                    },
                    # Sede 2
                    {
                        'tipo': 'menu', 'nombre': '📍 Sede 2 Pdte.', 'boton_id': 'sede_pdte',
                        'respuesta': (
                            '🏢 *SEDE 2 PDTE. - Planes y Horarios*\n'
                            'Mismos planes y comodidades que Sede 1. Te conecto con un asesor '
                            'para coordinar tu inscripción.'
                        ),
                        'hijos': [
                            {
                                'tipo': 'handoff', 'nombre': '👤 Hablar con asesor',
                                'boton_id': 'asesor_sede2',
                                'respuesta': 'Te conecto con un asesor para Sede 2.',
                            },
                        ],
                    },
                    # Promociones — hoja simple
                    {
                        'tipo': 'respuesta', 'nombre': '🎁 Ver Promociones',
                        'boton_id': 'ver_promos',
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
            # ───────── Rama HABLAR CON ASESOR ─────────
            {
                'tipo': 'handoff', 'nombre': '👤 Hablar con asesor',
                'boton_id': 'hablar_asesor',
                'respuesta': 'Te derivo con un asesor humano. ¡Un momento por favor!',
            },
        ],
    },
]


# ─────────────────── Lógica seed ───────────────────
TIPOS_VALIDOS = {
    'inicio', 'menu', 'respuesta', 'pregunta', 'http',
    'condicional', 'switch', 'set_variable', 'handoff', 'esperar', 'fin',
}


def crear_arbol(dep, items, padre=None):
    creados = 0
    for orden, item in enumerate(items, start=1):
        tipo = item.get('tipo', 'respuesta')
        if tipo not in TIPOS_VALIDOS:
            print(f"  ⚠ tipo '{tipo}' inválido en '{item.get('nombre')}', usando 'respuesta'")
            tipo = 'respuesta'
        op = OpcionDepartamentoChatBot(
            departamento=dep,
            opcion_padre=padre,
            tipo_nodo=tipo,
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
        print(f"Depto '{NOMBRE_DEPTO}' ya existe (id={dep.id}). Limpiando opciones previas...")
        # Hard delete para no acumular soft-deleted con los mismos boton_id
        OpcionDepartamentoChatBot.objects.filter(departamento=dep).delete()
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
    print()
    print("Próximos pasos:")
    print(f"  1. Reemplazá las URLs placeholder (PayPhone, Google Form, Maps) por reales.")
    print(f"  2. Asigná el depto a la sesión: SesionWhatsApp.departamento_default = depto #{dep.id}")
    print(f"     y SesionWhatsApp.modo_bot = 'tradicional'.")


if __name__ == '__main__':
    main()
