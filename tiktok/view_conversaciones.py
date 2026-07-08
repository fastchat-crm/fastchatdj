"""Conversaciones de TikTok: listado filtrado por proveedor. Se poblará cuando
la Business Messaging API esté aprobada y el webhook activo."""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render

from core.funciones import addData, paginador, secure_module
from whatsapp.models import ConversacionWhatsApp
from whatsapp.permisos_sesion import sesiones_vista_completa


@login_required
@secure_module
def conversacionesTikTokView(request):
    data = {
        'titulo': 'Conversaciones TikTok',
        'descripcion': 'DMs de tus cuentas TikTok Business',
        'ruta': request.path,
    }
    addData(request, data)

    sesiones = sesiones_vista_completa(request.user).filter(proveedor='tiktok')
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

    listado = qs.order_by('-fecha_registro')
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    data['cuentas'] = sesiones.order_by('nombre')
    paginador(request, listado, 50, data, url_vars)
    return render(request, 'tiktok/conversaciones/listado.html', data)
