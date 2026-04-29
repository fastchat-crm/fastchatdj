"""
crm/herramienta_templates.py

Plantillas pre-cargadas de HerramientaAgente por sector. El cliente elige
una, el wizard se rellena con los valores y luego solo cambia URL + headers.

Formato: mismo schema que el modelo HerramientaAgente (parametros como lista
de dicts con nombre/tipo/descripcion/pregunta_sugerida/requerido/ejemplo).
"""

HERRAMIENTA_TEMPLATES = [
    # ─── Seguros ──────────────────────────────────────────────────────
    {
        'key': 'seguros_poliza',
        'sector': 'Seguros',
        'icon': 'fa-shield-alt',
        'color': '#1c7ed6',
        'nombre_amigable': 'Consultar estado de póliza',
        'nombre': 'consultar_poliza',
        'descripcion': (
            'Consulta el estado, vigencia y cobertura de una póliza de seguro '
            'usando la cédula del asegurado. Úsala cuando el cliente pregunte por '
            'el estado de su póliza, cobertura, vencimiento o prima pendiente.'
        ),
        'metodo': 'GET',
        'url': 'https://api.ejemplo-seguros.com/polizas/{cedula}',
        'ubicacion_params': 'path',
        'timeout': 10,
        'plantilla_respuesta': (
            'Tu póliza {{ numero }} está {{ estado }}. '
            'Vigente hasta {{ fecha_vencimiento }}. '
            'Prima pendiente: ${{ prima_pendiente }}.'
        ),
        'parametros': [
            {
                'nombre': 'cedula', 'tipo': 'string', 'requerido': True,
                'descripcion': 'Cédula de identidad de 10 dígitos del asegurado',
                'pregunta_sugerida': '¿Me puedes dar tu número de cédula para consultar tu póliza?',
                'ejemplo': '0912345678',
            },
        ],
        'headers': {'Authorization': 'Bearer TU_TOKEN_AQUI'},
    },
    # ─── Restaurantes ────────────────────────────────────────────────
    {
        'key': 'restaurante_reserva',
        'sector': 'Restaurantes',
        'icon': 'fa-utensils',
        'color': '#fa5252',
        'nombre_amigable': 'Consultar reserva',
        'nombre': 'consultar_reserva',
        'descripcion': (
            'Consulta los detalles de una reserva del restaurante usando el nombre '
            'del titular y la fecha. Úsala cuando el cliente pregunte por su reserva, '
            'el horario confirmado, el número de personas o quiera verificar si existe.'
        ),
        'metodo': 'GET',
        'url': 'https://api.ejemplo-restaurante.com/reservas',
        'ubicacion_params': 'query',
        'timeout': 10,
        'plantilla_respuesta': (
            'Reserva a nombre de {{ nombre }} confirmada para el {{ fecha }} a las {{ hora }}, '
            '{{ personas }} personas. Mesa: {{ mesa }}.'
        ),
        'parametros': [
            {
                'nombre': 'nombre', 'tipo': 'string', 'requerido': True,
                'descripcion': 'Nombre completo del titular de la reserva',
                'pregunta_sugerida': '¿A nombre de quién está la reserva?',
                'ejemplo': 'Juan Pérez',
            },
            {
                'nombre': 'fecha', 'tipo': 'string', 'requerido': True,
                'descripcion': 'Fecha de la reserva en formato YYYY-MM-DD',
                'pregunta_sugerida': '¿Qué día es la reserva?',
                'ejemplo': '2026-05-12',
            },
        ],
        'headers': {'Accept': 'application/json'},
    },
    # ─── Universidades ───────────────────────────────────────────────
    {
        'key': 'universidad_notas',
        'sector': 'Universidades',
        'icon': 'fa-graduation-cap',
        'color': '#7048e8',
        'nombre_amigable': 'Consultar notas de una materia',
        'nombre': 'consultar_notas',
        'descripcion': (
            'Consulta las notas del estudiante en una materia específica del semestre '
            'actual, usando cédula y código o nombre de la materia. Úsala cuando el '
            'estudiante pregunte por sus calificaciones, promedios o estado académico.'
        ),
        'metodo': 'GET',
        'url': 'https://api.ejemplo-universidad.edu/estudiantes/{cedula}/materias',
        'ubicacion_params': 'path',
        'timeout': 15,
        'plantilla_respuesta': (
            'Materia: {{ materia }}. Nota parcial 1: {{ nota1 }}, parcial 2: {{ nota2 }}, '
            'examen final: {{ final }}. Promedio: {{ promedio }} — {{ estado }}.'
        ),
        'parametros': [
            {
                'nombre': 'cedula', 'tipo': 'string', 'requerido': True,
                'descripcion': 'Cédula del estudiante (10 dígitos)',
                'pregunta_sugerida': '¿Me compartes tu número de cédula?',
                'ejemplo': '0912345678',
            },
            {
                'nombre': 'materia', 'tipo': 'string', 'requerido': False,
                'descripcion': 'Código o nombre de la materia a consultar. Si no se provee, devuelve todas.',
                'pregunta_sugerida': '¿De qué materia quieres consultar? (Si prefieres todas, no te preocupes)',
                'ejemplo': 'MAT-101',
            },
        ],
        'headers': {'Authorization': 'Bearer TU_TOKEN_AQUI'},
    },
]


# Nota: El prompt PROMPT_IA_ASISTIDA fue movido a
# `agents_ai/ai_actions/prompts.py` (clave 'herramientas_crm') como parte
# de la centralizacion de acciones IA. La accion vive ahora en
# `agents_ai/ai_actions/herramientas_crm.py`.
