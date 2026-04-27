"""Registro central de prompts para `ai_actions/`.

Convencion: clave = '<modulo>_<app>' (mismo nombre del archivo de la accion).
Cada valor es un template `str.format()` con placeholders documentados al lado.

Si una accion tiene varios prompts (ej. plantillas WA con / sin contexto), usar
sub-claves: `'plantillas_wa.con_contexto'`, `'plantillas_wa.sin_contexto'`.
"""

PROMPTS = {
    # ─────────────────────────────────────────────────────────────────────
    # WhatsApp — Campanas de marketing (multi-canal)
    # Placeholders: {canal_principal}, {descripcion_usuario}
    # ─────────────────────────────────────────────────────────────────────
    'campanas_wa': (
        "Eres un especialista en campanas de marketing por WhatsApp/Instagram/Messenger. "
        "Genera SOLO un JSON valido con estos campos para crear una campana:\n"
        '  - "nombre": string corto (max 60 chars).\n'
        '  - "descripcion": string (max 200 chars) interna para el operador.\n'
        '  - "mensaje_texto": string — el mensaje a enviar, tono directo, incluye placeholders '
        '{{nombre}} y/o {{numero}} donde corresponda. Max 800 chars. No uses markdown ni emojis excesivos.\n'
        '  - "tipo": uno de ["texto", "plantilla", "media"].\n'
        '  - "throttle_por_minuto": int entre 10 y 60.\n'
        "Canal principal: {canal_principal}.\n"
        "Objetivo de la campana del usuario:\n"
        "{descripcion_usuario}\n"
        "\n"
        "Devuelve exclusivamente el JSON, sin explicaciones, sin ```.\n"
    ),

    # ─────────────────────────────────────────────────────────────────────
    # WhatsApp — Horarios de atencion (semanales)
    # Placeholders: {descripcion}
    # ─────────────────────────────────────────────────────────────────────
    'horarios_wa.semanales': (
        "Convierte la descripcion en horarios semanales. Responde con SOLO un objeto JSON "
        "(sin explicaciones, sin ``` markdown, sin texto fuera del JSON).\n"
        "\n"
        "Esquema:\n"
        "{{\n"
        '  "horarios": [\n'
        '    {{"dia_semana": 0-6, "hora_inicio": "HH:MM", "hora_fin": "HH:MM"}}\n'
        "  ]\n"
        "}}\n"
        "Donde dia_semana: 0=Lun, 1=Mar, 2=Mie, 3=Jue, 4=Vie, 5=Sab, 6=Dom. "
        "Permite multiples bloques por dia. No inventes dias no mencionados.\n"
        "\n"
        "Descripcion:\n"
        "{descripcion}\n"
    ),

    # ─────────────────────────────────────────────────────────────────────
    # WhatsApp — Excepciones / feriados
    # Placeholders: {anio_actual}, {descripcion}
    # ─────────────────────────────────────────────────────────────────────
    'horarios_wa.excepciones': (
        "Convierte la descripcion en excepciones/feriados. Responde con SOLO un objeto JSON "
        "(sin explicaciones, sin ``` markdown, sin texto fuera del JSON).\n"
        "\n"
        "Esquema:\n"
        "{{\n"
        '  "excepciones": [\n'
        '    {{"fecha": "YYYY-MM-DD", "abierto": true|false, "motivo": "string corto"}}\n'
        "  ]\n"
        "}}\n"
        "Si no se especifica anio, usa {anio_actual}. Para feriados latinoamericanos/ecuatorianos, "
        "resuelve las fechas exactas cuando se mencionen por nombre (ej. 'Navidad' -> "
        "{anio_actual}-12-25). 'abierto' = false cuando es feriado cerrado, true cuando "
        "es horario especial.\n"
        "\n"
        "Descripcion:\n"
        "{descripcion}\n"
    ),

    # ─────────────────────────────────────────────────────────────────────
    # WhatsApp — PlantillaWhatsApp (Meta) — generacion de UNA plantilla
    # Placeholders: {contexto_negocio}, {descripcion_usuario}
    # ─────────────────────────────────────────────────────────────────────
    'plantillas_wa.uno': (
        "Eres un experto en plantillas de WhatsApp Business (Meta Cloud API).\n"
        "Genera UNA plantilla de mensaje basandote en:\n"
        "\n"
        "CONTEXTO DEL NEGOCIO:\n"
        "{contexto_negocio}\n"
        "\n"
        "SOLICITUD DEL USUARIO:\n"
        "{descripcion_usuario}\n"
        "\n"
        "Responde SOLO con un bloque JSON valido (sin markdown, sin texto extra) con esta estructura exacta:\n"
        "{{\n"
        '  "nombre": "slug_en_minusculas_con_guiones_bajos",\n'
        '  "categoria": "UTILITY o MARKETING o AUTHENTICATION",\n'
        '  "idioma": "es",\n'
        '  "header_tipo": "NONE o TEXT o IMAGE",\n'
        '  "header_contenido": "texto del header o vacio si NONE",\n'
        '  "cuerpo": "texto principal con {{{{1}}}}, {{{{2}}}}, etc para variables",\n'
        '  "footer": "pie opcional o vacio",\n'
        '  "variables_json": [\n'
        '    {{"nombre": "nombre_descriptivo", "ejemplo": "valor de ejemplo"}}\n'
        "  ]\n"
        "}}\n"
        "\n"
        "Reglas:\n"
        "- Los placeholders deben ser estrictamente {{{{1}}}}, {{{{2}}}}, {{{{3}}}}... en orden consecutivo.\n"
        "- El nombre debe ser slug valido: solo a-z, 0-9 y guiones bajos, maximo 512 chars.\n"
        "- El footer tiene maximo 60 caracteres.\n"
        "- UTILITY es para confirmaciones, recordatorios, seguimiento. MARKETING para promos, ofertas, engagement.\n"
        "- Usa emojis con moderacion. Escribe en espanol.\n"
        "- El cuerpo debe ser natural, profesional y conciso.\n"
    ),

    # ─────────────────────────────────────────────────────────────────────
    # WhatsApp — PlantillaWhatsApp (Meta) — generacion en lote (N plantillas)
    # Placeholders: {n}, {descripcion}, {contexto_negocio}
    # ─────────────────────────────────────────────────────────────────────
    'plantillas_wa.lote': (
        "Eres un experto en plantillas de WhatsApp Business (Meta Cloud API). Genera "
        "{n} plantillas optimizadas. Devuelve SOLO un JSON valido (sin ```), con esta estructura:\n"
        "{{\n"
        '  "plantillas": [\n'
        "    {{\n"
        '      "nombre": "snake_case_unico_max_60_chars",\n'
        '      "idioma": "es" o "es_MX" o "en_US" segun corresponda,\n'
        '      "categoria": "UTILITY" | "MARKETING" | "AUTHENTICATION",\n'
        '      "header_tipo": "NONE" | "TEXT",\n'
        '      "header_contenido": "string sin emojis ni markdown, max 60 chars (vacio si NONE)",\n'
        '      "cuerpo": "texto del mensaje con placeholders {{{{1}}}}, {{{{2}}}}... segun necesidad. Max 1024 chars.",\n'
        '      "footer": "string opcional, max 60 chars, sin emojis"\n'
        "    }}\n"
        "  ]\n"
        "}}\n"
        "\n"
        "REGLAS DURAS de Meta:\n"
        "- nombre: solo a-z 0-9 _ (snake_case), unico por cuenta WABA, max 60 chars.\n"
        "- header_contenido: SIN newlines, SIN asteriscos *_~`, SIN emojis, max 60 chars.\n"
        "- footer: mismas reglas que header.\n"
        "- cuerpo: max 1024 chars, puede usar *negrita*, _cursiva_, ~tachado~, `monospace`. Usa {{{{1}}}} {{{{2}}}} para variables dinamicas.\n"
        "- categoria UTILITY = transaccional (confirmaciones, recordatorios, tracking).\n"
        "- categoria MARKETING = promocional/engagement (Meta cobra mas + restricciones de opt-in).\n"
        "- categoria AUTHENTICATION = solo para OTP/2FA, no usar para otro caso.\n"
        "\n"
        "Descripcion del usuario:\n"
        "{descripcion}\n"
        "\n"
        "Contexto del negocio (si aplica):\n"
        "{contexto_negocio}\n"
        "\n"
        "Idioma sugerido: detectalo del contexto (default es_MX si latam, es_ES si espanol generico).\n"
        "\n"
        "Devuelve EXCLUSIVAMENTE el JSON pedido.\n"
    ),

    # ─────────────────────────────────────────────────────────────────────
    # CRM — HerramientaAgente (asistente de configuracion via lenguaje natural)
    # Placeholders: {descripcion_usuario}
    # ─────────────────────────────────────────────────────────────────────
    'herramientas_crm': (
        "Eres un asistente que ayuda a configurar una herramienta de consulta API\n"
        "para un chatbot que conversa con clientes por WhatsApp.\n"
        "\n"
        "El usuario describira en lenguaje natural que necesita consultar. Genera la\n"
        "configuracion de la herramienta respondiendo SOLO con JSON valido — sin texto\n"
        "adicional, sin markdown, sin explicaciones.\n"
        "\n"
        "El JSON debe tener EXACTAMENTE esta estructura:\n"
        "\n"
        "{{\n"
        '  "nombre_amigable": "<titulo corto para humanos, max 80 chars>",\n'
        '  "nombre": "<identificador en snake_case sin espacios, max 50 chars>",\n'
        '  "descripcion": "<2-3 frases claras: que hace y CUANDO usarla; el LLM lo leera para decidir cuando invocarla>",\n'
        '  "metodo": "GET" o "POST",\n'
        '  "ubicacion_params": "query" | "json" | "form" | "path",\n'
        '  "url": "<URL de ejemplo; puedes usar {{{{param}}}} si ubicacion_params es \'path\'>",\n'
        '  "timeout": 10,\n'
        '  "plantilla_respuesta": "<plantilla Jinja con {{{{variable}}}} para formatear la respuesta al cliente; o cadena vacia>",\n'
        '  "parametros": [\n'
        "    {{\n"
        '      "nombre": "<slug snake_case>",\n'
        '      "tipo": "string" | "integer" | "number" | "boolean",\n'
        '      "requerido": true | false,\n'
        '      "descripcion": "<que es este dato — lo vera el LLM>",\n'
        '      "pregunta_sugerida": "<como el agente le pregunta al usuario en espanol natural>",\n'
        '      "ejemplo": "<valor ejemplo>"\n'
        "    }}\n"
        "  ]\n"
        "}}\n"
        "\n"
        "Reglas:\n"
        "- Si el usuario no especifica URL, inventa una razonable (ej: https://api.cliente.com/recurso).\n"
        "- Incluye SOLO los parametros realmente necesarios. Si algo lo puedes obtener del contexto del bot (numero de WhatsApp), no lo pidas.\n"
        "- 'pregunta_sugerida' debe ser conversacional, calida y en espanol ecuatoriano neutro.\n"
        "- Para consultas: usa GET. Para crear/agendar/registrar: usa POST.\n"
        "\n"
        "Descripcion del usuario:\n"
        "{descripcion_usuario}\n"
    ),

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
