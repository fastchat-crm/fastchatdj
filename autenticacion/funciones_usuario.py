"""Helpers del listado de usuarios administrativos (`view_usuario.py`).

`filtros_listado_usuarios` es la fuente única del Q de filtros: la usan el
listado GET, la exportación a Excel y el cambio masivo de contraseña — así las
acciones masivas afectan EXACTAMENTE a lo que el operador está viendo filtrado.
"""
from itertools import permutations

from django.db.models import Q


def filtros_listado_usuarios(params):
    """Construye el Q de filtros del listado a partir de un QueryDict
    (request.GET del listado o el querystring reenviado por acciones masivas)."""
    filtros = Q(id__gt=0)

    id_ = params.get('id', '')
    if id_:
        filtros &= Q(id=id_)

    documento = params.get('documento', '')
    if documento:
        filtros &= Q(documento=documento)

    status_perfil = params.get('status_perfil', '')
    if status_perfil == '1':
        filtros &= Q(status=True)
    elif status_perfil == '0':
        filtros &= Q(status=False)
    elif status_perfil == '2':
        filtros &= Q(is_superuser=True)
    elif status_perfil == '3':
        filtros &= Q(is_staff=True)

    grupoid = [int(x) for x in params.getlist('grupoid') if str(x).strip().isdigit()]
    if grupoid:
        filtros &= Q(groups__in=grupoid)

    criterio = (params.get('criterio', '') or '').strip()
    if criterio:
        palabras = criterio.split()
        q_obj = Q()
        if len(palabras) == 1:
            palabra = palabras[0]
            q_obj |= Q(first_name__icontains=palabra)
            q_obj |= Q(last_name__icontains=palabra)
            q_obj |= Q(username__icontains=palabra)
        elif 2 <= len(palabras) <= 4:
            for combo in permutations(palabras, len(palabras)):
                sub_q = Q()
                for i, palabra in enumerate(combo):
                    if i % 2 == 0:
                        sub_q &= Q(first_name__icontains=palabra)
                    else:
                        sub_q &= Q(last_name__icontains=palabra)
                q_obj |= sub_q
        else:
            q_obj &= (Q(first_name__icontains=palabras[0]) &
                      Q(last_name__icontains=palabras[1]) &
                      Q(last_name__icontains=palabras[2]))
        filtros &= q_obj

    return filtros


def exportar_usuarios_excel(listado):
    """Arma el Workbook de openpyxl con el listado filtrado de usuarios."""
    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Usuarios'
    encabezados = [
        'Cod', 'Apellidos', 'Nombres', 'Usuario', 'Documento', 'Email',
        'Teléfono', 'Grupos', 'Activo', 'Super Usuario', 'Staff',
        'Fecha Registro', 'Último Acceso',
    ]
    ws.append(encabezados)
    for celda in ws[1]:
        celda.font = Font(bold=True)

    def _si_no(valor):
        return 'Sí' if valor else 'No'

    def _fecha(valor):
        return valor.strftime('%d/%m/%Y %H:%M') if valor else ''

    for u in listado:
        ws.append([
            u.id,
            u.last_name or '',
            u.first_name or '',
            u.username or '',
            u.documento or '',
            u.email or '',
            u.telefono or '',
            ', '.join(g.name for g in u.groups.all()),
            _si_no(u.is_active),
            _si_no(u.is_superuser),
            _si_no(u.is_staff),
            _fecha(getattr(u, 'fecha_registro', None) or u.date_joined),
            _fecha(u.last_login),
        ])

    for col in ws.columns:
        letra = col[0].column_letter
        ancho = max((len(str(c.value or '')) for c in col), default=10)
        ws.column_dimensions[letra].width = min(max(ancho + 2, 10), 45)
    return wb
