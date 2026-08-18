"""Clasificación liviana de mensajes — regex, cero llamadas LLM.

Detecta saludos, confirmaciones breves (acks) y consultas amplias para decidir
si se consulta FAISS, cuánto contexto se recupera y si se responde sin LLM.
"""
import re
import unicodedata

# Palabras que NO se añaden como ancla semántica al query FAISS
_GREETING_WORDS = frozenset({
    'hola', 'hi', 'hello', 'hey', 'buenas', 'buenos', 'saludos',
    'ok', 'okay', 'si', 'sí', 'no', 'gracias', 'thanks',
})

# Mensajes de confirmación breve / smalltalk — se salta FAISS y memoria, solo historial
_ACK_RE = re.compile(
    r'^(ok|okay|okey|entendido|perfecto|excelente|bien|claro|ya|dale|listo|genial|'
    r'super|chévere|chevere|gracias|thanks|de acuerdo|muy bien|está bien|👍|'
    r'de acuerdo|eso es todo|nada más|nada mas|'
    r'vale|va|bueno|buenísimo|buenisimo|joya|bárbaro|barbaro|de nada|'
    r'gracias\s+a\s+(ti|vos|usted)|igualmente|a\s+la\s+orden|'
    r'(muchas|mil)\s+gracias|muchísimas\s+gracias|muchisimas\s+gracias|'
    r'chao|chau|adi[oó]s|bye|hasta\s+luego|hasta\s+mañana|hasta\s+pronto|nos\s+vemos|'
    r'(ja|je|ji){2,}|x?d+|👌|🙏|❤️|😊|😂|🤣|jsjs\w*)[\s!.,;:…]*$',
    re.IGNORECASE | re.UNICODE,
)

_GREETING_RE = re.compile(
    r'^(hola+|hi+|hello+|hey+|ey+|buenas?|buenos\s+d[ií]as?|buenas?\s+tardes?'
    r'|buenas?\s+noches?|buen\s+d[ií]a|saludos?|qu[eé]\s+tal|c[oó]mo\s+est[aá]s?'
    r'|good\s+morning|good\s+afternoon|good\s+evening)\W*$',
    re.IGNORECASE | re.UNICODE,
)

_AMPLIA_RE = re.compile(
    r'(men[uú]|carta|qu[eé]\s+tiene[sn]?|qu[eé]\s+ofrecen?|lista\s+de|cat[aá]logo'
    r'|todas?\s+(las?|los?)\s+opciones?|todo\s+lo\s+que|todos?\s+(los?|las?)\s+platos?'
    r'|qu[eé]\s+hay|productos?|servicios?|precios?\s+de\s+todo|todo\s+el\s+men[uú]'
    r'|qu[eé]\s+venden?|qu[eé]\s+sirven?|qu[eé]\s+tienen\s+disponible)',
    re.IGNORECASE | re.UNICODE,
)


def _es_saludo(texto: str) -> bool:
    return bool(_GREETING_RE.match(texto.strip()))


def _es_ack_simple(texto: str) -> bool:
    """True si el mensaje es una confirmación breve que no necesita buscar en FAISS."""
    t = texto.strip()
    return len(t) <= 30 and bool(_ACK_RE.match(t))


def _es_consulta_amplia(texto: str) -> bool:
    """True si el usuario pide información amplia (menú completo, catálogo, lista de productos)."""
    return bool(_AMPLIA_RE.search(texto.strip()))


def normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('utf-8')
    texto = re.sub(r'[^a-zA-Z0-9\s]', '', texto)
    return texto.lower()
