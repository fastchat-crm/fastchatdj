"""
Cálculo de COSTO en USD del consumo de tokens IA.

El sistema registra tokens (ConsumoTokenIA) pero no dinero. Aquí traducimos
tokens -> USD usando una tabla de precios por modelo (USD por 1.000.000 tokens),
separando precio de entrada (prompt) y de salida (respuesta).

⚠️ IMPORTANTE: este despliegue usa **Ollama Cloud (ollama.com) con API key**, que
NO cobra por tokens: es una **suscripción fija mensual** (Free $0 · Pro $20/mes ·
Max $100/mes) con límites de USO por GPU-time (sesión reset 5h, semanal reset 7d),
no un tope de tokens. Por eso los modelos bajo suscripción tienen costo_usd = 0 y
se valora el consumo con `costo_referencia_usd`. Las tarifas por millón de esta
tabla aplican a proveedores de PAGO POR TOKEN (OpenAI/Gemini/Claude). Si un modelo
no está en la tabla, se usa DEFAULT.
"""

# USD por 1.000.000 de tokens: (entrada, salida)
PRECIOS_USD_POR_MILLON = {
    # OpenAI
    'gpt-4o-mini':        (0.15,  0.60),
    'gpt-4o':             (2.50, 10.00),
    'gpt-4-turbo':        (10.00, 30.00),
    'gpt-4':              (30.00, 60.00),
    'gpt-4.1':            (2.00,  8.00),
    'gpt-4.1-mini':       (0.40,  1.60),
    'gpt-3.5-turbo':      (0.50,  1.50),
    'o1-mini':            (1.10,  4.40),
    # Anthropic (Claude)
    'claude-3-5-sonnet':  (3.00, 15.00),
    'claude-3-5-haiku':   (0.80,  4.00),
    'claude-3-opus':      (15.00, 75.00),
    'claude-sonnet-4':    (3.00, 15.00),
    'claude-haiku-4':     (1.00,  5.00),
    # Google (Gemini)
    'gemini-2.5-pro':     (1.25, 10.00),
    'gemini-2.5-flash':   (0.30,  2.50),
    'gemini-1.5-flash':   (0.075, 0.30),
    'gemini-1.5-pro':     (1.25,  5.00),
    # Embeddings (solo entrada; salida = 0)
    'text-embedding-3-small': (0.02, 0.0),
    'text-embedding-3-large': (0.13, 0.0),
    'text-embedding-ada-002': (0.10, 0.0),

    # ── Modelos OPEN servidos vía Ollama Cloud (ollama.com) — PAGO por token.
    #    ⚠️ ESTIMACIONES: ajusta a tu tarifa real de ollama.com. (USD por millón)
    'gemma4:31b':         (0.20, 0.60),
    'gemma4':             (0.20, 0.60),
    'gemma3':             (0.15, 0.45),
    'gemma2':             (0.15, 0.45),
    'gemma':              (0.15, 0.45),
    'ministral-3:14b':    (0.10, 0.30),
    'ministral':          (0.10, 0.30),
    'mistral':            (0.15, 0.45),
    'mixtral':            (0.30, 0.90),
    'llama3':             (0.15, 0.45),
    'llama':              (0.15, 0.45),
    'qwen':               (0.15, 0.45),
    'deepseek':           (0.30, 0.90),
    'phi':                (0.10, 0.30),
    'gpt-oss:20b':        (0.15, 0.45),
    'gpt-oss':            (0.15, 0.45),
    'ollama':             (0.15, 0.45),
}

# Precio por defecto si el modelo no está en la tabla (conservador ~ gpt-4o-mini)
DEFAULT_USD_POR_MILLON = (0.15, 0.60)

LOCAL_PREFIJOS = ()
LOCAL_SUFIJOS = ('-local', ':local')

# ── MODELO DE FACTURACIÓN DE ESTE DESPLIEGUE ────────────────────────────────
# Ollama Cloud (ollama.com) se paga con SUSCRIPCIÓN FIJA MENSUAL: el costo
# marginal por token es $0 (ya está incluido en el plan). Por eso los modelos
# servidos bajo la suscripción tienen costo_usd = 0, y para valorar el consumo
# usamos `costo_referencia_usd` (lo que costaría en un modelo de pago por token).
# Ollama Cloud NO cobra por tokens: es tarifa PLANA con límites de USO (GPU-time),
# no un tope de tokens. Planes: Free $0 · Pro $20/mes (50x uso, 3 modelos) ·
# Max $100/mes. Límites por sesión (reset 5h) y semanales (reset 7 días).
SUSCRIPCION_MENSUAL_USD = 20.0  # ⚠️ EDITA según tu plan: Free=0 / Pro=20 / Max=100
SUSCRIPCION_PREFIJOS = (
    'gemma', 'ministral', 'mistral', 'mixtral', 'llama', 'qwen',
    'deepseek', 'phi', 'gpt-oss', 'ollama',
)

# Modelo de referencia para el "costo equivalente" (lo que costaría ese mismo
# consumo en un proveedor de pago por token). Editable.
MODELO_REFERENCIA = 'gpt-4o-mini'


def es_local(modelo: str) -> bool:
    """True solo si el modelo está explícitamente marcado como on-prem/local."""
    m = (modelo or '').strip().lower()
    if not m:
        return False
    if any(m.startswith(pre) for pre in LOCAL_PREFIJOS):
        return True
    if '127.0.0.1' in m or 'localhost' in m or any(m.endswith(suf) for suf in LOCAL_SUFIJOS):
        return True
    return False


def en_suscripcion(modelo: str) -> bool:
    """True si el modelo se sirve bajo la suscripción fija (costo por token $0)."""
    m = (modelo or '').strip().lower()
    return bool(m) and any(m.startswith(pre) for pre in SUSCRIPCION_PREFIJOS)


def _tarifa(modelo: str):
    """Devuelve (precio_in, precio_out) por millón para un nombre de modelo,
    tolerando sufijos de fecha/versión. Locales y modelos bajo suscripción = (0, 0)."""
    m = (modelo or '').strip().lower()
    if not m:
        return DEFAULT_USD_POR_MILLON
    if es_local(m) or en_suscripcion(m):
        return (0.0, 0.0)
    if m in PRECIOS_USD_POR_MILLON:
        return PRECIOS_USD_POR_MILLON[m]
    # match por prefijo más largo (el nombre de la tabla es prefijo del modelo real)
    mejor = None
    for clave, precio in PRECIOS_USD_POR_MILLON.items():
        if m.startswith(clave) and (mejor is None or len(clave) > len(mejor[0])):
            mejor = (clave, precio)
    return mejor[1] if mejor else DEFAULT_USD_POR_MILLON


def costo_usd(modelo: str, tokens_entrada: int, tokens_salida: int) -> float:
    """Costo REAL en USD de una llamada según el modelo usado."""
    p_in, p_out = _tarifa(modelo)
    ti = int(tokens_entrada or 0)
    to = int(tokens_salida or 0)
    return (ti * p_in + to * p_out) / 1_000_000.0


def costo_referencia_usd(tokens_entrada: int, tokens_salida: int,
                         modelo_ref: str = None) -> float:
    """Costo EQUIVALENTE: lo que costaría ese consumo en un modelo de pago
    conocido (por defecto MODELO_REFERENCIA). Sirve para comparar proveedores."""
    ref = (modelo_ref or MODELO_REFERENCIA)
    p_in, p_out = PRECIOS_USD_POR_MILLON.get(ref, DEFAULT_USD_POR_MILLON)
    ti = int(tokens_entrada or 0)
    to = int(tokens_salida or 0)
    return (ti * p_in + to * p_out) / 1_000_000.0


def costo_desde_consumo(consumo) -> float:
    """Costo USD real de un registro ConsumoTokenIA."""
    return costo_usd(getattr(consumo, 'modelo', ''),
                     getattr(consumo, 'tokens_entrada', 0),
                     getattr(consumo, 'tokens_salida', 0))
