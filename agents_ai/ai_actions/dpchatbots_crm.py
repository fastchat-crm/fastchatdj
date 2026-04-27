"""Generador IA de DepartamentoChatBot completo (con menu jerarquico).

Punto de entrada: `generar(descripcion, tipo_negocio, tono, apikey_obj, usuario)`.
La logica de validacion HTTP / construccion de respuesta se queda en la view
(`crm/view_departamento_chatbot.py`); aca solo vive la pieza IA y la persistencia
del arbol resultante.
"""
import logging

from django.db import transaction

from .base import IAActionError, invocar_json
from .prompts import get_prompt

logger = logging.getLogger(__name__)


# ============================================================================
# Persistencia del arbol generado
# ============================================================================
def _crear_opciones_recursivo(departamento, opciones_lista, parent=None,
                              orden_inicial: int = 0) -> int:
    """Crea OpcionDepartamentoChatBot en cascada respetando jerarquia del JSON IA.

    El modelo usa `nombre` (visible al usuario) y `respuesta` (mensaje del bot).
    La IA puede devolver `texto_boton` (preferido) o `nombre`. Devuelve el
    conteo total de opciones creadas (incluyendo descendientes).
    """
    from crm.models import OpcionDepartamentoChatBot

    creadas = 0
    for i, op in enumerate(opciones_lista):
        if not isinstance(op, dict):
            continue
        texto = (op.get('texto_boton') or op.get('nombre') or '').strip()
        if not texto:
            continue
        respuesta_txt = (op.get('respuesta') or '').strip()
        nueva = OpcionDepartamentoChatBot.objects.create(
            departamento=departamento,
            opcion_padre=parent,
            nombre=texto[:100],
            respuesta=respuesta_txt[:2000],
            orden=orden_inicial + i,
            tipo_nodo='respuesta',
            es_inicio=(parent is None and i == 0),
            usuario_creacion=departamento.usuario_creacion,
        )
        creadas += 1
        hijos = op.get('hijos') or []
        if isinstance(hijos, list) and hijos:
            creadas += _crear_opciones_recursivo(departamento, hijos, parent=nueva)
    return creadas


# ============================================================================
# Punto de entrada publico
# ============================================================================
def generar(*, descripcion: str, tipo_negocio: str, tono: str,
            apikey_obj, usuario) -> dict:
    """Genera un DepartamentoChatBot completo via LLM y lo persiste.

    Args:
        descripcion: descripcion del negocio (>=30 chars). Obligatorio.
        tipo_negocio: tipo opcional ('restaurante', 'clinica', etc.).
        tono: 'amable', 'formal', 'cercano', etc. Default 'amable'.
        apikey_obj: instancia ApiKeyIA validada (debe tener clave y estar activa).
        usuario: Usuario que dispara la accion (audit / FK usuario_creacion).

    Returns:
        dict con keys: departamento_id, nombre, opciones_count, tokens, modelo.

    Raises:
        IAActionError — input invalido, JSON malformado, LLM error.
    """
    from crm.models import DepartamentoChatBot

    descripcion = (descripcion or '').strip()
    tipo_negocio = (tipo_negocio or '').strip() or 'no especificado'
    tono = (tono or 'amable').strip() or 'amable'
    if len(descripcion) < 30:
        raise IAActionError("Descripcion muy corta (minimo 30 chars).")

    prompt = get_prompt(
        'dpchatbots_crm',
        descripcion=descripcion,
        tipo_negocio=tipo_negocio,
        tono=tono,
        tono_title=tono.title(),
    )

    payload, tokens, modelo = invocar_json(
        prompt,
        apikey_obj=apikey_obj,
        origen='dpchatbot',
        prompt_preview=descripcion[:300],
        max_tokens=16000,
        temperature=0.4,
    )

    nombre = (payload.get('nombre_departamento') or '').strip()
    if not nombre:
        raise IAActionError("La IA no devolvio nombre_departamento.")

    bienvenida = (payload.get('mensaje_bienvenida') or '').strip()
    opciones_arbol = payload.get('opciones') or []
    if not isinstance(opciones_arbol, list):
        opciones_arbol = []

    with transaction.atomic():
        depto = DepartamentoChatBot.objects.create(
            nombre=nombre,
            mensaje_saludo=bienvenida,
            activo_tradicional=True,
            usuario_creacion=usuario,
        )
        opciones_count = _crear_opciones_recursivo(depto, opciones_arbol, parent=None)

    return {
        'departamento_id': depto.id,
        'nombre': depto.nombre,
        'opciones_count': opciones_count,
        'tokens': tokens,
        'modelo': modelo,
    }
