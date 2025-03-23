from datetime import date
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse

from fastchatdj import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from core.funciones import addData, MiPaginador, secure_module, paginador
from django.db.models import Q
from django.utils.timezone import activate
from django.template.response import TemplateResponse

activate(settings.TIME_ZONE)
from seguridad.models import AudiUsuarioTabla
from django.contrib.admin.models import LogEntry


@login_required
@secure_module
def auditoria(request):
    data = {
        'modulo': 'Seguridad',
        'titulo': 'ACTIVIDAD DE USUARIOS',
        'titulo1': 'Listado de actividades de usuarios',
        'titulo2': 'Auditoria',
        'ruta': '/seguridad/auditoria/',
        'user': request.user.username,
    }
    model = AudiUsuarioTabla

    addData(request, data)

    if 'action' in request.GET:
        data["action"] = action = request.GET["action"]
        if action == 'ver_detalle_aud':
            try:
                with transaction.atomic():
                    #data["auditoria"] = auditoria = AudiUsuarioTabla.objects.get(id=int(request.GET["pk"]))
                    data["auditoria"] = auditoria = LogEntry.objects.get(id=int(request.GET["pk"]))

                    if auditoria.datos_json and auditoria.datos_json != '[]':
                        import json
                        datos = json.loads(auditoria.datos_json)
                        modelo = datos[0]["model"]
                        campos = [x for x in list(datos[0]["fields"].keys()) if x != '__ff_detalle_ff__']
                        if modelo in ('auth.user', 'autenticacion.Usuario'):
                            campos_temp = campos
                            campos = []
                            for c in campos_temp:
                                if c != 'password' and c != 'user_permissions':
                                    campos.append(c)
                        campos_tabla = [str(x).replace('_', ' ').strip().capitalize() for x in campos]
                        campos_tabla = campos_tabla
                        data["campos_tabla"] = ['Registro'] + campos_tabla
                        data["campos"] = ['__ff_detalle_ff__'] + campos
                        data["datos"] = datos
                        contenido = TemplateResponse(request, 'seguridad/auditoria/detalle_auditoria.html',
                                                     data).render().content.decode()
                        return JsonResponse({"resp": True, "contenido": contenido})
            except Exception as ex:
                pass
            return JsonResponse({"resp": False})

    criterio, filtros, desde, hasta, url_vars = request.GET.get('criterio', '').strip(), Q(id__gt=0), request.GET.get(
        'desde', ''), request.GET.get('hasta', ''), ''
    if criterio:
        filtros = filtros & (Q(user__username__icontains=criterio) | Q(change_message__icontains=criterio))
        data["criterio"] = criterio
        url_vars += '&criterio=' + criterio
    if desde and hasta:
        filtros = filtros & (Q(action_time__gte=desde) & Q(action_time__lte=hasta))
        data["desde"] = desde
        data['hasta'] = hasta
        url_vars += '&desde=' + desde + '&hasta=' + hasta
    #auditoria = AudiUsuarioTabla.objects.filter(filtros)
    auditoria = LogEntry.objects.filter(filtros)
    data["url_vars"] = url_vars
    paginador(request, auditoria, 15, data)
    return render(request, 'seguridad/auditoria/auditoria.html', data)
