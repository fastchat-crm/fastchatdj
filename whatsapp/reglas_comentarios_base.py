"""Catálogo de reglas comentario→DM listas para usar.

Una cuenta social recién conectada arranca sin ninguna regla, y escribir nueve
desde cero antes de que sirva de algo es fricción pura. Acá vive un juego base
que cubre los comentarios que realmente aparecen —precio, disponibilidad,
envíos, agendar, reclamos— para que el usuario edite textos en vez de inventar
la estructura.

Se cargan desde el botón «Cargar reglas base» de `/instagram/reglas-comentarios/`
(y su equivalente en Facebook y TikTok), o programáticamente con
`crear_reglas_base(sesion, canal, request)`.

**El orden importa.** `procesar_reglas_comentario` aplica la PRIMERA regla que
matchea, y una regla sin keywords matchea todo. Por eso la de cortesía va
siempre última (orden 90): si estuviera primera, taparía a las demás y ningún
comentario llegaría nunca a la regla de precio.
"""

# Etiquetas que crean las reglas base. Se crean solo si no existen.
ETIQUETAS_BASE = {
    'Interesado': ('#198754', 'Preguntó por precio, disponibilidad o quiere comprar'),
    'Agenda':     ('#0d6efd', 'Pidió turno, cita o reserva desde un comentario'),
    'Soporte':    ('#dc3545', 'Reportó un problema o reclamo en un comentario'),
}

# `etiqueta` referencia una clave de ETIQUETAS_BASE; None = sin etiqueta.
# `respuesta_publica` vacía = no responder a la vista de todos.
REGLAS_BASE = [
    {
        'orden': 10,
        'nombre': 'Pregunta por precio',
        'keywords': 'precio, precios, cuanto, cuánto, cuanto cuesta, cuánto cuesta, '
                    'costo, valor, vale, cotizar, cotización, cotizacion, tarifa',
        'respuesta_publica': '¡Hola! Te paso los precios por mensaje privado 📩',
        'mensaje_dm': '¡Hola! Vi tu comentario sobre precios 👋\n\n'
                      'Contame qué te interesa y te paso el detalle al toque.',
        'etiqueta': 'Interesado',
    },
    {
        # Va ANTES de «Quiere comprar» a propósito: "quiero sacar turno" es una
        # intención de agenda, no de compra, y si comprar corriera primero se
        # la llevaría. Lo específico siempre antes que lo genérico.
        'orden': 20,
        'nombre': 'Quiere agendar',
        'keywords': 'cita, turno, agendar, agenda, reservar, reserva, '
                    'sacar turno, cupo, disponibilidad de horario',
        'respuesta_publica': '¡Perfecto! Te escribo por privado para coordinar 📅',
        'mensaje_dm': '¡Hola! Vamos a coordinar tu turno 📅\n\n'
                      '¿Qué día y horario te queda cómodo?',
        'etiqueta': 'Agenda',
    },
    {
        'orden': 30,
        'nombre': 'Quiere comprar',
        # Sin el `quiero` suelto: es demasiado genérico y se comía "quiero
        # turno", "quiero info", "quiero saber el precio".
        'keywords': 'lo quiero, quiero comprar, comprar, me interesa, lo llevo, '
                    'adquirir, como compro, cómo compro, donde compro, dónde compro',
        'respuesta_publica': '¡Genial! Te escribo por privado para ayudarte 🙌',
        'mensaje_dm': '¡Hola! Vi que te interesa 🙌\n\n'
                      '¿Querés que te ayude a concretarlo? Contame qué necesitás.',
        'etiqueta': 'Interesado',
    },
    {
        'orden': 40,
        'nombre': 'Pide información',
        'keywords': 'info, informacion, información, mas info, más info, detalles, '
                    'me pasas, me pasás, datos',
        'respuesta_publica': '¡Claro! Te mando la info por privado 📩',
        'mensaje_dm': '¡Hola! Acá va la info que pediste 👇\n\n'
                      'Decime qué te gustaría saber y te cuento todo.',
        'etiqueta': None,
    },
    {
        'orden': 50,
        'nombre': 'Consulta disponibilidad',
        'keywords': 'disponible, disponibilidad, stock, hay, quedan, tienen, '
                    'tenes, tenés, queda',
        'respuesta_publica': 'Te confirmo disponibilidad por privado 📩',
        'mensaje_dm': '¡Hola! Sobre tu consulta de disponibilidad 👋\n\n'
                      'Decime cuál te interesa y te confirmo si está.',
        'etiqueta': 'Interesado',
    },
    {
        'orden': 60,
        'nombre': 'Pregunta por envíos',
        'keywords': 'envio, envío, envios, envíos, envian, envían, delivery, '
                    'domicilio, mandan, despacho',
        'respuesta_publica': 'Sí, hacemos envíos. Te doy los detalles por privado 📦',
        'mensaje_dm': '¡Hola! Sobre los envíos 📦\n\n'
                      'Contame a qué zona sería y te digo tiempos y costo.',
        'etiqueta': None,
    },
    {
        'orden': 70,
        'nombre': 'Ubicación y horarios',
        'keywords': 'donde, dónde, ubicacion, ubicación, direccion, dirección, '
                    'horario, horarios, abren, atienden, sucursal',
        'respuesta_publica': 'Te paso ubicación y horarios por privado 📍',
        'mensaje_dm': '¡Hola! 📍\n\n'
                      'Te comparto nuestra ubicación y horarios de atención. '
                      '¿Querés que te reserve un horario?',
        'etiqueta': None,
    },
    {
        'orden': 80,
        'nombre': 'Reclamo o problema',
        # Sin respuesta pública a propósito: un reclamo contestado en el hilo
        # queda expuesto para todos y suele escalar. Se atiende en privado.
        'keywords': 'problema, reclamo, no funciona, no llego, no llegó, ayuda, '
                    'soporte, error, falla, malo, pesimo, pésimo, estafa',
        'respuesta_publica': '',
        'mensaje_dm': 'Hola, vi tu comentario y quiero ayudarte 🙏\n\n'
                      'Contame qué pasó y lo resolvemos por acá.',
        'etiqueta': 'Soporte',
    },
    {
        'orden': 90,
        'nombre': 'Cortesía (cualquier comentario)',
        # Sin keywords: matchea TODO. Por eso va última — si subiera de orden,
        # taparía a todas las anteriores.
        'keywords': '',
        'respuesta_publica': '¡Gracias por comentar! 🙌',
        'mensaje_dm': '',
        'etiqueta': None,
    },
]


def _obtener_etiquetas(usuario):
    """Crea (si faltan) las etiquetas que usan las reglas base.

    La unicidad de `EtiquetaContacto` es por (usuario_creacion, nombre), así que
    se busca y crea siempre en el ámbito del usuario dueño de la sesión.
    """
    from .models import EtiquetaContacto

    mapa = {}
    for nombre, (color, descripcion) in ETIQUETAS_BASE.items():
        etiqueta = EtiquetaContacto.objects.filter(
            usuario_creacion=usuario, nombre__iexact=nombre, status=True
        ).first()
        if not etiqueta:
            etiqueta = EtiquetaContacto(nombre=nombre, color=color, descripcion=descripcion)
            etiqueta.usuario_creacion = usuario
            etiqueta.save()
        mapa[nombre] = etiqueta
    return mapa


def crear_reglas_base(sesion, canal, request=None):
    """Crea el juego base de reglas para una sesión y canal.

    Es idempotente: una regla cuyo nombre ya existe en esa sesión y canal se
    saltea, así se puede volver a pulsar el botón sin duplicar nada ni pisar los
    textos que el usuario haya editado.

    Devuelve `(creadas, salteadas)`.
    """
    from .models import ReglaComentario

    usuario = getattr(request, 'user', None) or sesion.usuario
    etiquetas = _obtener_etiquetas(usuario)

    existentes = set(
        ReglaComentario.objects
        .filter(sesion=sesion, canal=canal, status=True)
        .values_list('nombre', flat=True)
    )

    creadas = salteadas = 0
    for base in REGLAS_BASE:
        if base['nombre'] in existentes:
            salteadas += 1
            continue

        etiqueta = etiquetas.get(base['etiqueta']) if base['etiqueta'] else None
        regla = ReglaComentario(
            sesion=sesion,
            canal=canal,
            nombre=base['nombre'],
            keywords=base['keywords'],
            respuesta_publica=base['respuesta_publica'],
            mensaje_dm=base['mensaje_dm'],
            etiqueta=etiqueta,
            orden=base['orden'],
            activa=True,
        )
        if request is not None:
            regla.save(request)
        else:
            regla.usuario_creacion = usuario
            regla.save()
        creadas += 1

    return creadas, salteadas
