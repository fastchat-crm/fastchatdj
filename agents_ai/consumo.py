"""Cálculo del costo en USD del consumo de tokens IA.

Tabla de precios por 1.000 tokens (entrada, salida) según el pricing público
de cada proveedor. Es un ESTIMADO para el dashboard de consumo — el costo real
lo factura el proveedor. Modelos locales (Ollama) valen 0. Modelos no listados
caen al precio del prefijo de su familia o al default conservador.
"""

PRECIO_USD_POR_1K_TOKENS = {
    'gemini-2.5-flash':          (0.00030, 0.00250),
    'gemini-2.5-flash-lite':     (0.00010, 0.00040),
    'gemini-2.5-pro':            (0.00125, 0.01000),
    'gemini-1.5-flash':          (0.000075, 0.00030),
    'gemini-1.5-flash-8b':       (0.0000375, 0.00015),
    'gemini-1.5-pro':            (0.00125, 0.00500),
    'gpt-4o-mini':               (0.00015, 0.00060),
    'gpt-4o':                    (0.00250, 0.01000),
    'gpt-4.1':                   (0.00200, 0.00800),
    'gpt-4.1-mini':              (0.00040, 0.00160),
    'gpt-4.1-nano':              (0.00010, 0.00040),
    'gpt-4-turbo':               (0.01000, 0.03000),
    'gpt-3.5-turbo':             (0.00050, 0.00150),
    'claude-haiku-4-5-20251001': (0.00100, 0.00500),
    'claude-sonnet-4-6':         (0.00300, 0.01500),
    'claude-sonnet-4-5':         (0.00300, 0.01500),
    'claude-opus-4-7':           (0.01500, 0.07500),
    'claude-opus-4-6':           (0.01500, 0.07500),
    'deepseek-chat':             (0.00027, 0.00110),
    'deepseek-reasoner':         (0.00055, 0.00219),
    'DeepSeek-V3':               (0.00027, 0.00110),
    'DeepSeek-R1':               (0.00055, 0.00219),
    'Qwen3-32B':                 (0.00030, 0.00090),
    'llama3.1':                  (0.0, 0.0),
    'llama3.2':                  (0.0, 0.0),
    'qwen2.5':                   (0.0, 0.0),
    'mistral':                   (0.0, 0.0),
    'deepseek-r1':               (0.0, 0.0),
}

_PRECIO_POR_PREFIJO = (
    ('gemini-', (0.00030, 0.00250)),
    ('gpt-',    (0.00050, 0.00200)),
    ('claude-', (0.00300, 0.01500)),
    ('deepseek', (0.00055, 0.00219)),
    ('llama',   (0.0, 0.0)),
    ('qwen',    (0.00030, 0.00090)),
    ('mistral', (0.0, 0.0)),
)

_PRECIO_DEFAULT = (0.00100, 0.00400)


def precio_modelo(modelo: str) -> tuple:
    """(usd_entrada, usd_salida) por 1.000 tokens para el modelo dado."""
    m = (modelo or '').strip()
    if m in PRECIO_USD_POR_1K_TOKENS:
        return PRECIO_USD_POR_1K_TOKENS[m]
    ml = m.lower()
    for prefijo, precio in _PRECIO_POR_PREFIJO:
        if ml.startswith(prefijo.lower()):
            return precio
    return _PRECIO_DEFAULT


def costo_usd(modelo: str, tokens_entrada: int, tokens_salida: int) -> float:
    """Costo estimado en USD de una llamada (o un agregado) al modelo dado."""
    p_in, p_out = precio_modelo(modelo)
    return round(
        (tokens_entrada or 0) / 1000.0 * p_in + (tokens_salida or 0) / 1000.0 * p_out,
        6,
    )


def costo_queryset_por_modelo(qs) -> list:
    """Agrega un queryset de ConsumoTokenIA por modelo con costo estimado USD.

    Devuelve [{'modelo', 'llamadas', 'entrada', 'salida', 'total', 'costo_usd'}, ...]
    ordenado por costo descendente.
    """
    from django.db.models import Count, Sum
    filas = (
        qs.values('modelo')
          .annotate(
              llamadas=Count('id'),
              entrada=Sum('tokens_entrada'),
              salida=Sum('tokens_salida'),
              total=Sum('tokens_total'),
          )
    )
    resultado = []
    for r in filas:
        resultado.append({
            'modelo': r['modelo'] or '(sin modelo)',
            'llamadas': r['llamadas'],
            'entrada': r['entrada'] or 0,
            'salida': r['salida'] or 0,
            'total': r['total'] or 0,
            'costo_usd': costo_usd(r['modelo'], r['entrada'] or 0, r['salida'] or 0),
        })
    resultado.sort(key=lambda x: x['costo_usd'], reverse=True)
    return resultado


def costo_total_queryset(qs) -> float:
    """Costo total estimado en USD de un queryset de ConsumoTokenIA."""
    return round(sum(f['costo_usd'] for f in costo_queryset_por_modelo(qs)), 4)
