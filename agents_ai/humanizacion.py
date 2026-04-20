"""Utilidades para que las respuestas del bot parezcan humanas en WhatsApp.

Dos piezas:

- `dividir_en_burbujas(texto, max_chars=180)` — parte la respuesta en 2-4 burbujas
  respetando párrafos, oraciones y listas. No rompe ítems de lista (líneas que
  empiezan con "-", "•", "1.", etc.).

- `calcular_delays(burbuja, previa=None, jitter=True)` — devuelve un par
  `(lectura, escritura)` en segundos que simula lo que tardaría una persona en
  leer la burbuja anterior y escribir la actual. Con jitter ±20 % para evitar
  cadencia robótica.
"""
from __future__ import annotations

import random
import re


# Umbrales calibrados para WhatsApp latinoamericano típico
_CHARS_POR_BURBUJA_IDEAL = 180
_CHARS_POR_BURBUJA_MAX   = 320
_MAX_BURBUJAS            = 4

_LECTURA_CHARS_POR_SEG   = 70      # lectura rápida en pantalla
_ESCRITURA_CHARS_POR_SEG = 25      # tipeo humano promedio
_LECTURA_MAX_SEG         = 2.5
_ESCRITURA_MIN_SEG       = 0.6
_ESCRITURA_MAX_SEG       = 6.0

_INICIO_ITEM_LISTA = re.compile(r'^\s*(?:[-*•·]|\d+[.)])\s+', re.UNICODE)


def _es_linea_de_lista(linea: str) -> bool:
    return bool(_INICIO_ITEM_LISTA.match(linea))


def _partir_por_oraciones(texto: str) -> list[str]:
    """Parte un párrafo por oraciones preservando los signos de puntuación.

    Regex tolera signos de apertura en español (¿¡) y evita partir dentro de
    decimales o URLs. Si no hay match, devuelve el texto completo como 1 oración.
    """
    texto = texto.strip()
    if not texto:
        return []
    # Split con lookahead por [.!?] seguido de espacio + mayúscula/número/signo apertura
    partes = re.split(r'(?<=[.!?])\s+(?=[A-Z¿¡0-9])', texto)
    return [p.strip() for p in partes if p.strip()]


def dividir_en_burbujas(
    texto: str,
    max_chars: int = _CHARS_POR_BURBUJA_IDEAL,
    max_burbujas: int = _MAX_BURBUJAS,
) -> list[str]:
    """Divide una respuesta larga en varias burbujas de WhatsApp.

    Reglas:
    - Respeta párrafos (separados por línea en blanco).
    - Nunca rompe una línea de lista — mantiene la lista junta en una burbuja.
    - Si un párrafo es grande sin lista, lo parte por oraciones.
    - Acumula hasta `max_chars` por burbuja. Si agregar una oración pasa de
      `_CHARS_POR_BURBUJA_MAX` crea nueva burbuja.
    - Máximo `max_burbujas`. Si hay más, junta el resto en la última.
    - Si el texto entero cabe en `max_chars`, devuelve 1 sola burbuja (no divide por dividir).
    """
    texto = (texto or '').strip()
    if not texto:
        return []
    if len(texto) <= max_chars:
        return [texto]

    # Párrafos por doble salto de línea
    parrafos = [p.strip() for p in re.split(r'\n\s*\n', texto) if p.strip()]

    burbujas: list[str] = []
    buffer: list[str] = []
    buffer_len = 0

    def flush_buffer():
        nonlocal buffer, buffer_len
        if buffer:
            burbujas.append('\n\n'.join(buffer).strip())
            buffer = []
            buffer_len = 0

    for parrafo in parrafos:
        lineas = parrafo.split('\n')
        tiene_lista = any(_es_linea_de_lista(l) for l in lineas)

        # Listas y párrafos que caben se agregan como bloque completo.
        # Flush antes de agregar si el buffer ya tiene algo Y sumar este
        # párrafo superaría el ideal — así la burbuja actual cierra natural.
        if tiene_lista or len(parrafo) <= max_chars:
            if buffer and buffer_len + len(parrafo) + 2 > max_chars:
                flush_buffer()
            buffer.append(parrafo)
            buffer_len += len(parrafo) + 2
            # Si igual excede el máximo duro, cerrar ya.
            if buffer_len >= _CHARS_POR_BURBUJA_MAX:
                flush_buffer()
            continue

        # Párrafo grande sin lista → partir por oraciones
        oraciones = _partir_por_oraciones(parrafo)
        for oracion in oraciones:
            if buffer and buffer_len + len(oracion) + 1 > max_chars:
                flush_buffer()
            buffer.append(oracion)
            buffer_len += len(oracion) + 1
            if buffer_len >= _CHARS_POR_BURBUJA_MAX:
                flush_buffer()

    flush_buffer()

    # Colapsar si se pasó del máximo: unir la cola en la última burbuja
    if len(burbujas) > max_burbujas:
        cola = '\n\n'.join(burbujas[max_burbujas - 1:])
        burbujas = burbujas[:max_burbujas - 1] + [cola]

    return burbujas


def calcular_delays(
    burbuja: str,
    previa: str | None = None,
    jitter: bool = True,
) -> tuple[float, float]:
    """Calcula `(lectura_seg, escritura_seg)` para una burbuja.

    - `lectura_seg`: tiempo estimado que el humano tardaría en leer la respuesta
      previa antes de escribir esta. Si no hay previa, 0.
    - `escritura_seg`: tiempo proporcional al largo de la burbuja actual.
    - Con `jitter=True`, ambos valores varían ±20 % para no ser periódicos.
    """
    prev_len = len(previa or '')
    lectura = min(_LECTURA_MAX_SEG, prev_len / _LECTURA_CHARS_POR_SEG) if prev_len else 0.0

    escritura = max(
        _ESCRITURA_MIN_SEG,
        min(_ESCRITURA_MAX_SEG, len(burbuja) / _ESCRITURA_CHARS_POR_SEG),
    )

    if jitter:
        lectura *= random.uniform(0.8, 1.2)
        escritura *= random.uniform(0.8, 1.2)

    return round(lectura, 2), round(escritura, 2)


# ---------------------------------------------------------------------------
# Saludos variados por franja horaria
# ---------------------------------------------------------------------------

_SALUDOS_MANANA = [
    '¡Buen día!', '¡Buenos días!', 'Holaaa, buen día 🌞', 'Hola, buen día',
    '¡Épa, buenas!', 'Hola 👋',
]
_SALUDOS_TARDE = [
    '¡Buenas tardes!', 'Holaaa, buenas tardes', 'Hola, qué tal',
    '¡Épa, buenas!', 'Hola 👋', 'Buenas',
]
_SALUDOS_NOCHE = [
    '¡Buenas noches!', 'Hola, buenas noches', 'Holaa 👋', 'Buenas',
    'Hola, qué tal',
]
_CIERRES = [
    '¿En qué te puedo ayudar?', '¿Qué necesitás?', 'Contame, ¿en qué ando?',
    '¿Cómo te ayudo?', '¿En qué te doy una mano?',
]


def saludo_por_hora(franja: str, nombre: str | None = None) -> str:
    """Devuelve un saludo aleatorio acorde a la franja ('mañana'|'tarde'|'noche').

    Si se pasa un nombre lo incluye en 50% de los casos (los humanos no repiten
    el nombre en cada saludo). Siempre incluye un cierre pregunta-abierta
    aleatorio para que el cliente pueda continuar.
    """
    if franja == 'mañana':
        saludo = random.choice(_SALUDOS_MANANA)
    elif franja == 'tarde':
        saludo = random.choice(_SALUDOS_TARDE)
    else:
        saludo = random.choice(_SALUDOS_NOCHE)

    nombre = (nombre or '').strip()
    if nombre and nombre.lower() not in ('cliente', '') and random.random() < 0.5:
        saludo = f"{saludo} {nombre}"

    return f"{saludo} {random.choice(_CIERRES)}"


# ---------------------------------------------------------------------------
# Detector de ánimo del mensaje — señal blanda para el prompt
# ---------------------------------------------------------------------------

_ANIMO_PATRONES = (
    # (nombre, regex)
    ('frustracion', re.compile(
        r'\b(no\s+(funciona|sirve|anda|va)|est[aá]\s+mal|muy\s+mal|harto|basta|'
        r'no\s+puede\s+ser|p[eé]simo|inserv[ií]ble|in[uú]til|odio|fatal)\b',
        re.IGNORECASE | re.UNICODE,
    )),
    ('enojo', re.compile(
        r'\b(furioso|enojad[oa]|bronca|me\s+cag[oa]|me\s+(jode|jodes)|'
        r'cabr[oó]n|ladr[oó]n|estafa|mentira|denuncia)\b',
        re.IGNORECASE | re.UNICODE,
    )),
    ('urgencia', re.compile(
        r'\b(urgente|urg[eé]|r[aá]pido|ya\s+mismo|lo\s+antes\s+posible|pero\s+ya|'
        r'necesito\s+(ya|ahora)|apurado|apurada)\b',
        re.IGNORECASE | re.UNICODE,
    )),
    ('agradecimiento', re.compile(
        r'\b(gracias|muchas\s+gracias|mil\s+gracias|te\s+(pas[aá]ste|amo)|'
        r'bendiciones|agradecido|agradecida|genio|crack)\b',
        re.IGNORECASE | re.UNICODE,
    )),
    ('buen_humor', re.compile(
        r'(\b(?:j[aeo]){2,}[aeo]*\b|\bxd+\b|\blol\b|😂|🤣|😁|😄)',
        re.IGNORECASE | re.UNICODE,
    )),
    ('duda', re.compile(
        r'\b(no\s+entiendo|no\s+entend[ií]|no\s+s[eé]\s+si|como\s+funciona|'
        r'me\s+explicas|m[aá]s\s+info)\b',
        re.IGNORECASE | re.UNICODE,
    )),
)

_GUIAS_ANIMO = {
    'frustracion':    'empatizá primero, validá la molestia, y recién después ofrecé solución o escalá a un asesor humano',
    'enojo':          'respondé con calma, no discutas, validá el enojo, ofrecé contacto con un humano si es grave',
    'urgencia':       'respondé corto y directo, sin rodeos, priorizá la acción',
    'agradecimiento': 'agradecé de vuelta breve y cálido, sin exagerar',
    'buen_humor':     'podés responder con un toque de humor suave si encaja, manteniendo profesionalismo',
    'duda':           'explicá paso a paso, con ejemplos simples, ofrecé reformular si no queda claro',
    'neutral':        'tono natural según el estilo configurado',
}


def detectar_animo(texto: str) -> tuple[str, str]:
    """Devuelve `(etiqueta, guia)` según señales en el texto del cliente.

    - `etiqueta` : frustracion|enojo|urgencia|agradecimiento|buen_humor|duda|neutral
    - `guia`     : frase corta con instrucción para el prompt del bot

    Prioriza en este orden: enojo > frustración > urgencia > duda > agradecimiento
    > buen_humor > neutral. Así el tono negativo nunca queda enmascarado por un
    "gracias" de fin de frase.
    """
    t = (texto or '').strip()
    if not t:
        return 'neutral', _GUIAS_ANIMO['neutral']

    orden_prioridad = (
        'enojo', 'frustracion', 'urgencia', 'duda',
        'agradecimiento', 'buen_humor',
    )
    detectados = {nombre for nombre, rx in _ANIMO_PATRONES if rx.search(t)}

    for etiqueta in orden_prioridad:
        if etiqueta in detectados:
            return etiqueta, _GUIAS_ANIMO[etiqueta]

    return 'neutral', _GUIAS_ANIMO['neutral']
