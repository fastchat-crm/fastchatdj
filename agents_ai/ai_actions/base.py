"""Capa base compartida por todas las acciones IA de `ai_actions/`.

Centraliza:
- Validacion de ApiKeyIA (`validar_apikey`)
- Construccion del LLM con modo JSON forzado segun provider (`build_llm`)
- Parser tolerante de JSON LLM (`parse_json_response`)
- Registro de `ConsumoTokenIA` + alertas (`log_consumo`)
- Helper de alto nivel `invocar_json(prompt, ...) -> (dict, tokens, modelo)`

NO modifica archivos existentes de `agents_ai/`. Consume `agents_ai.providers`
solo para extraer tokens y resolver el nombre del provider por id.
"""
import json
import logging
import re

from agents_ai.providers import get_provider

logger = logging.getLogger(__name__)


# ============================================================================
# Excepcion de dominio
# ============================================================================
class IAActionError(Exception):
    """Error en una accion IA cuyo mensaje es seguro de mostrar al usuario."""


# ============================================================================
# Validacion de ApiKey
# ============================================================================
def validar_apikey(apikey_obj) -> str:
    """Valida que la apikey existe, esta activa y tiene clave. Devuelve la clave."""
    if not apikey_obj:
        raise IAActionError("No hay API Key IA disponible.")
    if not getattr(apikey_obj, 'estado', True):
        raise IAActionError("La API Key IA esta deshabilitada.")
    clave = (getattr(apikey_obj, 'descripcion', '') or '').strip()
    if not clave:
        raise IAActionError("La API Key IA no tiene clave configurada.")
    return clave


# ============================================================================
# Construccion del LLM (con modo JSON forzado cuando el provider lo soporta)
# ============================================================================
def build_llm(apikey_obj, *, force_json: bool = True, max_tokens: int = 16000,
              temperature: float = 0.3):
    """Construye una instancia LangChain del LLM segun `apikey_obj.proveedor`.

    Si `force_json=True` y el provider soporta JSON nativo (Gemini, OpenAI),
    se activa el modo JSON via constructor kwargs. Para providers sin soporte
    nativo (Claude y futuros), se delega al provider y el prompt debe pedir
    JSON explicitamente.

    Returns:
        (llm, modelo_usado, provider) — tupla con la instancia LLM, el nombre
        del modelo concreto y la instancia BaseProvider.
    """
    clave = validar_apikey(apikey_obj)
    provider = get_provider(apikey_obj.proveedor)
    modelo = (getattr(apikey_obj, 'modelo', '') or '').strip() or provider.default_model()
    base_url = (getattr(apikey_obj, 'base_url', '') or '').strip() or None

    if force_json:
        if provider.name == 'gemini':
            from langchain_google_genai import ChatGoogleGenerativeAI
            llm = ChatGoogleGenerativeAI(
                model=modelo,
                google_api_key=clave,
                max_output_tokens=max_tokens,
                temperature=temperature,
                model_kwargs={'response_mime_type': 'application/json'},
            )
            return llm, modelo, provider
        if provider.name == 'openai':
            from langchain_community.chat_models import ChatOpenAI
            kwargs = dict(
                model_name=modelo,
                openai_api_key=clave,
                max_tokens=max_tokens,
                temperature=temperature,
                model_kwargs={'response_format': {'type': 'json_object'}},
            )
            if base_url:
                kwargs['openai_api_base'] = base_url
            llm = ChatOpenAI(**kwargs)
            return llm, modelo, provider
        # Otros providers (Claude, Ollama, DeepSeek, Huawei): sin force_json nativo,
        # depender del prompt.

    llm = provider.get_llm(clave, modelo, max_tokens, temperature, base_url=base_url)
    return llm, modelo, provider


# ============================================================================
# Parser tolerante de JSON LLM
# ============================================================================
def parse_json_response(texto) -> dict:
    """Extrae un dict JSON de la respuesta LLM tolerando prosa/fences/truncamiento.

    Estrategias en cascada:
      1. Parse directo.
      2. Quitar fences ```json ... ``` y reintentar.
      3. Buscar primer bloque `{ ... }` balanceado.
      4. Reparacion pesada (escapa control-chars, cierra strings/llaves abiertas).

    Lanza `IAActionError` si ninguna estrategia tiene exito.
    """
    if not texto:
        raise IAActionError("La IA devolvio una respuesta vacia.")
    t = str(texto).strip()

    # 1) Parse directo
    try:
        return json.loads(t)
    except Exception:
        pass

    # 2) Buscar bloque entre fences ```json ... ```
    if '```' in t:
        m = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', t, re.IGNORECASE)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass

    # 3) Quitar fences sueltas y buscar bloque balanceado { ... }
    t2 = re.sub(r'^```(?:json)?\s*', '', t)
    t2 = re.sub(r'\s*```\s*$', '', t2)
    start = t2.find('{')
    if start != -1:
        depth = 0
        for i in range(start, len(t2)):
            ch = t2[i]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    cand = t2[start:i + 1]
                    try:
                        return json.loads(cand)
                    except Exception:
                        break

    # 4) Reparacion pesada (truncamiento, control-chars sin escapar, llaves abiertas)
    try:
        return json.loads(_reparar_json_llm(t))
    except Exception as ex:
        logger.warning(
            "JSON LLM no parseable tras 4 intentos (%s). raw[:500]=%s",
            ex, t[:500],
        )
        raise IAActionError(
            "La IA no devolvio un JSON valido. Posibles causas: respuesta truncada "
            "(reduci el detalle), modelo confundido (proba otro proveedor), o quota agotada."
        )


def _reparar_json_llm(texto: str) -> str:
    """Repara errores comunes en JSON devuelto por LLMs.

    - Quita fences ```json
    - Extrae desde el primer { hasta el ultimo }
    - Escapa chars de control dentro de strings (\\n, \\r, \\t, \\u00XX)
    - Cierra strings sin cerrar (truncamiento)
    - Cierra llaves/corchetes faltantes
    """
    s = (texto or '').strip()
    s = re.sub(r'^```(?:json)?\s*', '', s)
    s = re.sub(r'\s*```\s*$', '', s)
    i = s.find('{')
    j = s.rfind('}')
    if i >= 0:
        s = s[i:] if j <= i else s[i:j + 1]

    out = []
    in_string = False
    escape_next = False
    for ch in s:
        if escape_next:
            out.append(ch)
            escape_next = False
            continue
        if ch == '\\':
            out.append(ch)
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string:
            if ch == '\n':
                out.append('\\n')
            elif ch == '\r':
                out.append('\\r')
            elif ch == '\t':
                out.append('\\t')
            elif ord(ch) < 0x20:
                out.append(f'\\u{ord(ch):04x}')
            else:
                out.append(ch)
        else:
            out.append(ch)
    s = ''.join(out)

    if s.count('"') % 2 == 1:
        s += '"'
    abiertas_llaves = s.count('{') - s.count('}')
    abiertos_corch = s.count('[') - s.count(']')
    if abiertos_corch > 0:
        s += ']' * abiertos_corch
    if abiertas_llaves > 0:
        s += '}' * abiertas_llaves
    return s


# ============================================================================
# Registro de consumo de tokens
# ============================================================================
def log_consumo(ai_message, *, apikey_obj, modelo: str, origen: str,
                agente=None, conversacion=None, prompt_preview: str = '') -> int:
    """Registra `ConsumoTokenIA` y dispara `verificar_alerta_consumo`.

    Nunca relanza errores: si algo falla (DB, alerta, extract_tokens), solo
    registra warning y devuelve 0. Devuelve `tokens_total` calculado.
    """
    try:
        from crm.alertas_consumo import verificar_alerta_consumo
        from crm.models import ConsumoTokenIA

        provider = get_provider(apikey_obj.proveedor)
        try:
            tokens_in, tokens_out = provider.extract_tokens(ai_message)
        except Exception:
            tokens_in, tokens_out = 0, 0
        tokens_in = int(tokens_in or 0)
        tokens_out = int(tokens_out or 0)
        total = tokens_in + tokens_out

        ConsumoTokenIA.objects.create(
            apikey=apikey_obj,
            agente=agente,
            conversacion=conversacion,
            tokens_entrada=tokens_in,
            tokens_salida=tokens_out,
            tokens_total=total,
            modelo=(modelo or '')[:100],
            origen=(origen or '')[:30],
            prompt_preview=(prompt_preview or '')[:300],
        )
        if total:
            try:
                verificar_alerta_consumo(apikey_obj, total)
            except Exception:
                logger.exception("verificar_alerta_consumo fallo (no critico)")
        return total
    except Exception:
        logger.exception("Error registrando ConsumoTokenIA (no critico)")
        return 0


# ============================================================================
# Helper de alto nivel: build + invoke + parse JSON + log tokens
# ============================================================================
def invocar_json(prompt: str, *, apikey_obj, origen: str,
                 agente=None, conversacion=None,
                 max_tokens: int = 16000, temperature: float = 0.3,
                 prompt_preview: str = '') -> tuple[dict, int, str]:
    """Pipeline completo para acciones IA que esperan JSON estructurado.

    Pasos:
      1. `build_llm(force_json=True)` segun provider.
      2. `llm.invoke(prompt)`.
      3. `log_consumo(...)` (no relanza si falla).
      4. `parse_json_response(...)` sobre el contenido.

    Returns:
        (data_dict, tokens_total, modelo_usado)

    Raises:
        IAActionError — apikey invalida, provider falla, JSON no parseable.
    """
    llm, modelo, provider = build_llm(
        apikey_obj, force_json=True,
        max_tokens=max_tokens, temperature=temperature,
    )
    try:
        msg = llm.invoke(prompt)
    except Exception as ex:
        raise IAActionError(f"Error invocando LLM ({provider.name}): {ex}")

    contenido = getattr(msg, 'content', None) or str(msg)

    tokens = log_consumo(
        msg, apikey_obj=apikey_obj, modelo=modelo,
        origen=origen, agente=agente, conversacion=conversacion,
        prompt_preview=prompt_preview or str(prompt)[:300],
    )

    data = parse_json_response(contenido)
    return data, tokens, modelo
