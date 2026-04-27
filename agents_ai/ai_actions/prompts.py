"""Registro central de prompts para `ai_actions/`.

Convencion: clave = '<modulo>_<app>' (mismo nombre del archivo de la accion).
Cada valor es un template `str.format()` con placeholders documentados al lado.

Si una accion tiene varios prompts (ej. plantillas WA con / sin contexto), usar
sub-claves: `'plantillas_wa.con_contexto'`, `'plantillas_wa.sin_contexto'`.
"""

PROMPTS = {
    # ─────────────────────────────────────────────────────────────────────
    # CRM — AgentesIA (asistente de creacion de agente)
    # Placeholders: {tono}, {idioma}, {descripcion_usuario}
    # ─────────────────────────────────────────────────────────────────────
    'agentes_crm': (
        "Eres un arquitecto de agentes conversacionales. El usuario describe lo que necesita "
        "y tu tarea es devolver SOLO un JSON valido con estos campos:\n"
        '  - "nombre": string corto (max 60 chars), descriptivo.\n'
        '  - "descripcion": string (max 400 chars) — resumen del rol y alcance del agente.\n'
        '  - "prompt_template": string — plantilla completa de sistema para el agente. '
        'DEBE incluir los placeholders literales {{descripcion_agente}}, {{contexto_extra}}, {{question}} y {{context}}. '
        'Usa el tono solicitado y sigue el patron: instrucciones -> "====" -> "{{context}}" -> "====" -> "Respuesta:". '
        'NO incluyas datos inventados, solo reglas de comportamiento y estilo.\n'
        '  - "contexto_estatico": string opcional — conocimiento fijo/FAQ sugerido que el usuario '
        'deberia agregar (puede estar vacio si no aplica).\n'
        '  - "anotar_listas": bool — true solo si el agente debe recordar listas de productos/servicios.\n'
        "\n"
        "Tono: {tono}. Idioma: {idioma}.\n"
        "Necesidad del usuario:\n"
        "{descripcion_usuario}\n"
        "\n"
        "Devuelve exclusivamente el JSON, sin explicaciones, sin ```.\n"
    ),

    # ─────────────────────────────────────────────────────────────────────
    # CRM — Departamento ChatBot
    # Placeholders: {tipo_negocio}, {descripcion}, {tono}, {tono_title}
    # ─────────────────────────────────────────────────────────────────────
    'dpchatbots_crm': (
        "Sos un experto en chatbots de WhatsApp Business. Te paso la descripcion "
        "de un negocio y vos generas un departamento completo con menu jerarquico.\n"
        "\n"
        "NEGOCIO ({tipo_negocio}):\n"
        "{descripcion}\n"
        "\n"
        "TONO: {tono}\n"
        "\n"
        "Devolve SOLO un objeto JSON valido (sin prosa, sin fences ```), con esta estructura exacta:\n"
        "\n"
        "{{\n"
        '  "nombre_departamento": "string corto, ej \'Atencion al cliente\'",\n'
        '  "descripcion_departamento": "string 1-2 frases, que resuelve este departamento",\n'
        '  "mensaje_bienvenida": "string que el bot envia al cliente al entrar al departamento. {tono_title} en tono. Hasta 250 chars. Puede usar emojis.",\n'
        '  "opciones": [\n'
        "    {{\n"
        '      "texto_boton": "string <=24 chars (es lo que ve el cliente como boton)",\n'
        '      "respuesta": "string que el bot envia al elegir esta opcion. Hasta 500 chars.",\n'
        '      "hijos": [\n'
        "        {{\n"
        '          "texto_boton": "...",\n'
        '          "respuesta": "...",\n'
        '          "hijos": []\n'
        "        }}\n"
        "      ]\n"
        "    }}\n"
        "  ]\n"
        "}}\n"
        "\n"
        "REGLAS:\n"
        "- 4 a 7 opciones de primer nivel.\n"
        "- Hasta 2 niveles de profundidad (opciones de opciones). Algunas pueden no tener hijos.\n"
        "- Si el negocio tiene sucursales, mencionalas con sus nombres.\n"
        "- Inclui siempre una opcion para 'hablar con humano' o 'asesor' al final.\n"
        "- Tono {tono}. Respuestas naturales, no roboticas.\n"
        "- Emojis si pero sin abusar (1-2 por mensaje).\n"
        "- NO inventes datos que no estan en la descripcion (precios, horarios, nombres de personas).\n"
        "\n"
        "Devolve SOLO el JSON.\n"
    ),
}


def get_prompt(clave: str, **kwargs) -> str:
    """Devuelve el prompt formateado. Lanza KeyError si la clave no existe
    o si falta algun placeholder en kwargs."""
    template = PROMPTS[clave]
    return template.format(**kwargs)
