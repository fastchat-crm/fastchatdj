from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse

from core.funciones import addData, paginador, secure_module, log
from .models import ConversacionWhatsApp, MensajeWhatsApp
from .redis_publish import enviar_mensaje

@login_required
@secure_module
def conversacionesView(request):
    data = {
        'titulo': 'Conversaciones WhatsApp',
        'modulo': 'Conversaciones WhatsApp',
        'ruta': request.path
    }
    addData(request, data)

    # ====================== VER MENSAJES =========================
    if request.method == 'GET' and 'action' in request.GET:
        action = request.GET['action']
        if action == 'ver_mensajes':
            pk = int(request.GET['pk'])
            conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)
            mensajes = MensajeWhatsApp.objects.filter(conversacion=conversacion).order_by('fecha')
            data['conversacion'] = conversacion
            data['mensajes'] = mensajes
            return render(request, 'whatsapp/conversaciones/mensajes.html', data)

    # ====================== ENVIAR MENSAJE =========================
    if request.method == 'POST':
        res_json = []
        try:
            with transaction.atomic():
                action = request.POST['action']
                if action == 'send':
                    pk = int(request.POST['pk'])
                    texto = request.POST.get('mensaje')
                    conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)

                    # Enviamos al Node.js
                    enviar_mensaje(conversacion.sesion.numero, conversacion.contacto_numero, texto)

                    # Guardamos en BD
                    MensajeWhatsApp.objects.create(
                        conversacion=conversacion,
                        remitente=conversacion.sesion.numero,
                        mensaje=texto,
                        tipo='texto',
                        fecha=timezone.now()
                    )
                    log(f"Mensaje enviado a {conversacion.contacto_numero}", request, "add", obj=conversacion.id)
                    messages.success(request, 'Mensaje enviado correctamente.')
                    res_json.append({'error': False, 'reload': True})
        except Exception as ex:
            res_json.append({'error': True, 'message': str(ex)})
        return JsonResponse(res_json, safe=False)

    # ====================== LISTADO CONVERSACIONES =========================
    criterio, filtros, url_vars = request.GET.get('criterio', '').strip(), Q(status=True), ''
    if criterio:
        filtros = filtros & (Q(contacto_numero__icontains=criterio) | Q(contacto_nombre__icontains=criterio))
        data["criterio"] = criterio
        url_vars += '&criterio=' + criterio

    listado = ConversacionWhatsApp.objects.filter(filtros)
    data["list_count"] = listado.count()
    data["url_vars"] = url_vars
    paginador(request, listado.order_by('-fecha_ultimo_mensaje'), 10, data, url_vars)
    return render(request, 'whatsapp/conversaciones/listado.html', data)

