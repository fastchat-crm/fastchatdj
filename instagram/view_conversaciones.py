"""Conversaciones de Instagram: listado filtrado por proveedor con acceso
directo al inbox compartido (deep-link ?conv=)."""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render

from core.funciones import addData, paginador, secure_module
from whatsapp.models import ConversacionWhatsApp
from whatsapp.permisos_sesion import sesiones_vista_completa


@login_required
@secure_module
def conversacionesInstagramView(request):
    data = {
        'titulo': 'Conversaciones Instagram',
        'descripcion': 'DMs de tus cuentas Instagram; abre cualquiera en el inbox',
        'ruta': request.path,
    }
    addData(request, data)

    sesiones = sesiones_vista_completa(request.user).filter(proveedor='instagram')
    qs = ConversacionWhatsApp.objects.filter(
        status=True, contacto__sesion__in=sesiones
    ).select_related('contacto', 'contacto__sesion', 'asignado_a')

    url_vars = ''
    criterio = (request.GET.get('criterio') or '').strip()
    if criterio:
        qs = qs.filter(
            Q(contacto__contacto_nombre__icontains=criterio)
            | Q(contacto__contacto_numero__icontains=criterio)
        )
        data['criterio'] = criterio
        url_vars += f'&criterio={criterio}'

    estado = (request.GET.get('estado') or '').strip()
    if estado:
        qs = qs.filter(estado_atencion=estado)
        data['estado'] = estado
        url_vars += f'&estado={estado}'

    sesion_id = (request.GET.get('cuenta') or '').strip()
    if sesion_id.isdigit():
        qs = qs.filter(contacto__sesion_id=int(sesion_id))
        data['cuenta_filtro'] = int(sesion_id)
        url_vars += f'&cuenta={sesion_id}'

    listado = qs.order_by('-fecha_registro')
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    data['cuentas'] = sesiones.order_by('nombre')
    paginador(request, listado, 50, data, url_vars)
    return render(request, 'instagram/conversaciones/listado.html', data)
