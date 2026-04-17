import json
import os
import sys
from datetime import date, datetime, timedelta
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.template.loader import get_template

from core.custom_models import FormError
from core.funciones import addData, paginador, secure_module, log, remover_caracteres_especiales_unicode, generar_nombre
from core.funciones_adicionales import convertir_archivo_a_base64
from core.funciones_excel_panda import export_query_to_excel
from seguridad.templatetags.templatefunctions import encrypt
from .forms import ContactoForm, MensajeWhatsAppProgramadoForm, AddContactoForm
from .models import Contacto, SesionWhatsApp, MensajeWhatsAppProgramado
from django.contrib import messages

from .services import WhatsAppService


@login_required
@secure_module
def contactoView(request):
    data = {'titulo': 'Contacto',
            'modulo': 'Whatsapp',
            'ruta': request.path,
            'fecha': str(date.today())
            }
    model = Contacto
    Formulario = ContactoForm
    whatsapp_service = WhatsAppService()

    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        try:
            with transaction.atomic():
                if action == 'add':
                    form = AddContactoForm(request.POST, request=request)
                    if form.is_valid():
                        sesion = form.cleaned_data['sesion']
                        numero_telefono = ''.join(c for c in form.cleaned_data['numero_telefono'] if c.isdigit())
                        if len(numero_telefono) > 12 or len(numero_telefono) < 9:
                            raise ValueError("El número de teléfono debe tener entre 9 y 12 dígitos.")
                        if Contacto.objects.filter(sesion=sesion, contacto_numero=numero_telefono).exists():
                            raise ValueError("Ya existe un contacto con este número en la sesión seleccionada.")
                        form.instance.from_number = f'{numero_telefono}@s.whatsapp.net'
                        form.instance.contacto_numero = numero_telefono
                        if 'contacto_foto' in request.FILES:
                            file = request.FILES['contacto_foto']
                            nombredocumento = remover_caracteres_especiales_unicode(file.name)
                            file.name = generar_nombre(nombredocumento, file.name)
                            imagen_base64 = convertir_archivo_a_base64(file)
                            form.instance.contacto_foto = imagen_base64
                        form.save()
                        log(f"Registro un contacto {form.instance.__str__()}", request, "add", obj=form.instance.id)
                        messages.success(request, f"Contacto {form.instance.contacto_nombre} registrado correctamente")
                        res_json.append({'error': False, "reload": True})
                    else:
                        raise FormError(form)

                elif action == 'change':
                    filtro = model.objects.get(pk=int(encrypt(request.POST['pk'])))
                    form = Formulario(request.POST, instance=filtro, request=request)
                    if form.is_valid() and filtro:
                        if 'contacto_foto' in request.FILES:
                            file = request.FILES['contacto_foto']
                            nombredocumento = remover_caracteres_especiales_unicode(file.name)
                            file.name = generar_nombre(nombredocumento, file.name)
                            imagen_base64 = convertir_archivo_a_base64(file)
                            form.instance.contacto_foto = imagen_base64
                        form.save()
                        log(f"Edito un contacto  {form.instance.__str__()}", request, "change", obj=form.instance.id)
                        res_json.append({'error': False, "reload": True})
                    else:
                        raise FormError(form)

                elif action == 'delete':
                    filtro = model.objects.get(pk=int(request.POST['id']))
                    filtro.status = False
                    filtro.save(request)
                    log(f"Elimino un contacto {filtro.__str__()}", request, "del", obj=filtro.id)
                    messages.success(request, f"Registro Eliminado")
                    res_json={"error":False}
                elif action == 'addMensajeProgramado':
                    filtro = model.objects.get(pk=int(encrypt(request.POST['pk'])))
                    if not filtro.sesion.es_baileys:
                        raise ValueError("Los mensajes programados solo estan disponibles para sesiones Baileys. Las sesiones Meta requieren plantillas pre-aprobadas.")
                    form = MensajeWhatsAppProgramadoForm(request.POST, request.FILES, request=request)
                    if not form.is_valid():
                        raise FormError(form)

                    fecha, hora = form.cleaned_data['fecha'], form.cleaned_data['hora']
                    ahora = datetime.now()
                    hora_minima = (ahora + timedelta(minutes=10)).time()
                    if fecha < ahora.date():
                        raise ValueError("La fecha seleccionada no puede ser anterior al día de hoy.")

                    if fecha == ahora.date() and hora < hora_minima:
                        raise ValueError( f"⏰ La hora programada debe ser al menos 10 minutos después de la hora actual ({hora_minima.strftime('%H:%M')}).")

                    form.instance.contacto = filtro
                    if 'archivo' in request.FILES:
                        file = request.FILES['archivo']
                        nombredocumento, _ = os.path.splitext(remover_caracteres_especiales_unicode(file.name))
                        file.name = generar_nombre(nombredocumento, file.name)
                        form.instance.archivo = file
                    form.save()
                    log(f"Agrego un mensaje programado para el contacto {filtro.__str__()}", request, "add", obj=form.instance.id)
                    res_json.append({'error': False, "reload": True})
                    messages.success(request, f"Mensaje agregado correctamente")
                elif action == 'changeMensajeProgramado':
                    filtro = MensajeWhatsAppProgramado.objects.get(pk=int(encrypt(request.POST['pk'])))
                    if not filtro.contacto.sesion.es_baileys:
                        raise ValueError("Los mensajes programados solo estan disponibles para sesiones Baileys.")
                    form = MensajeWhatsAppProgramadoForm(request.POST, request.FILES, request=request, instance=filtro)
                    if not form.is_valid():
                        raise FormError(form)

                    fecha, hora = form.cleaned_data['fecha'], form.cleaned_data['hora']
                    ahora = datetime.now()
                    hora_minima = (ahora + timedelta(minutes=10)).time()
                    if fecha != filtro.fecha or hora != filtro.hora:
                        if fecha < ahora.date():
                            raise ValueError("La fecha seleccionada no puede ser anterior al día de hoy.")

                        if fecha == ahora.date() and hora < hora_minima:
                            raise ValueError( f"⏰ La hora programada debe ser al menos 10 minutos después de la hora actual ({hora_minima.strftime('%H:%M')}).")

                    if 'archivo' in request.FILES:
                        file = request.FILES['archivo']
                        nombredocumento, _ = os.path.splitext(remover_caracteres_especiales_unicode(file.name))
                        file.name = generar_nombre(nombredocumento, file.name)
                        form.instance.archivo = file
                    form.save()
                    log(f"Edito un mensaje programado para el contacto {filtro.__str__()}", request, "change", obj=form.instance.id)
                    res_json.append({'error': False, "reload": True})
                    messages.success(request, f"Mensaje editado correctamente")
                elif action  == 'sendMensajeProgramado':
                    mensaje = MensajeWhatsAppProgramado.objects.get(pk=int(request.POST['id']))
                    if not mensaje:
                        raise ValueError("Mensaje programado no encontrado.")
                    if not mensaje.contacto.sesion.es_baileys:
                        raise ValueError("Los mensajes programados solo estan disponibles para sesiones Baileys.")
                    if not mensaje.enviado:
                        sesion_id = mensaje.sesion.session_id
                        from_number = mensaje.from_number
                        archivo = mensaje.archivo
                        texto = mensaje.mensaje
                        response = whatsapp_service.send_text_message(sesion_id, from_number, texto,simularEscritura=True)
                        if not response.get('success', False):
                            raise ValueError(f"Error al enviar mensaje programado: {mensaje.__str__()}")
                        if archivo:
                            filename = archivo.name.split('/')[1] if '/' in archivo.name else archivo.name
                            response_archivo = whatsapp_service.send_media_message(sesion_id, from_number,
                                                                                   caption=texto,
                                                                                   file_content=archivo.read(),
                                                                                   filename=filename)
                            if not response_archivo.get('success', False):
                                raise ValueError(f"Error al enviar archivo del mensaje programado: {mensaje.__str__()}")
                        mensaje.enviado = True
                        mensaje.fecha_envio = datetime.now()
                        mensaje.enviado_por = request.user
                        mensaje.save(request)
                        log(f"Mensaje programado enviado: {mensaje.__str__()}", request, "sendMensajeProgramado", obj=mensaje.id)
                        messages.success(request, f"Mensaje enviado correctamente")
                    res_json.append({'error': False, "reload": True})
                elif action == 'deleteMensajeProgramado':
                    mensaje = MensajeWhatsAppProgramado.objects.get(pk=int(request.POST['id']))
                    if not mensaje:
                        raise ValueError("Mensaje programado no encontrado.")
                    mensaje.status = False
                    mensaje.save(request)
                    log(f"Elimino un mensaje programado {mensaje.__str__()}", request, "deleteMensajeProgramado", obj=mensaje.id)
                    messages.success(request, f"Mensaje programado eliminado correctamente")
                    res_json = {"error": False}


        except ValueError as ex:
            res_json.append({'error': True, "message": str(ex)})
        except FormError as ex:
            res_json.append(ex.dict_error)
        except Exception as ex:
            line = sys.exc_info()[-1].tb_lineno
            res_json.append({'error': True, "message": f"{ex} - Line {line}"})
        return JsonResponse(res_json, safe=False)

    elif request.method == 'GET':
        addData(request, data)
        if 'action' in request.GET:
            data["action"] = action = request.GET['action']
            if action == 'add':
                try:
                    data["form"] = form = AddContactoForm()
                    form.fields['sesion'].queryset = SesionWhatsApp.objects.filter(status=True, usuario=request.user).distinct()
                    form.fields['numero_telefono'].initial = '593'
                    template = get_template("whatsapp/contacto/form.html")
                    return JsonResponse({"result": True, 'data': template.render(data)})
                except Exception as ex:
                    return JsonResponse({"result": False, 'message': str(ex)})

            elif action == 'change':
                try:
                    pk = int(request.GET['id'])
                    filtro = model.objects.get(pk=pk)
                    data["filtro"] = filtro
                    data["pk"] = pk
                    data["form"] = Formulario(instance=filtro)
                    template = get_template("whatsapp/contacto/form.html")
                    return JsonResponse({"result": True, 'data': template.render(data)})
                except Exception as ex:
                    return JsonResponse({"result": False, 'message': str(ex)})

            elif action == 'ver':
                pk = int(request.GET['id'])
                filtro = model.objects.get(pk=pk)
                data["pk"] = pk
                data["form"] = Formulario(instance=filtro, ver=True)
                return render(request, 'whatsapp/contacto/form.html', data)

            elif action == 'mensajes_programados':
                try:
                    contacto = model.objects.get(pk=int(request.GET['id']))
                    if not contacto.sesion.es_baileys:
                        messages.error(request, "Los mensajes programados solo estan disponibles para sesiones Baileys. Las sesiones Meta requieren plantillas pre-aprobadas.")
                        return redirect(request.path)
                    filtros, url_vars = Q(contacto=contacto, status=True), f'&action={action}&id={contacto.id}'
                    listado = MensajeWhatsAppProgramado.objects.filter(filtros).order_by('fecha')
                    data.update({
                        'titulo': f'Mensajes programados para {contacto.contacto_nombre}',
                        'listado': listado,
                        'contacto': contacto,
                        'url_vars': url_vars,
                    })
                    paginador(request, listado, 20, data, url_vars)
                    return render(request, 'whatsapp/contacto/listado_programados.html', data)
                except Exception as ex:
                    messages.error(request, f"Error al cargar los mensajes programados: {str(ex)}")
                    return redirect(request.path)
            elif action == 'addMensajeProgramado':
                try:
                    pk = int(request.GET['id'])
                    filtro = model.objects.get(pk=pk)
                    if not filtro.sesion.es_baileys:
                        messages.error(request, "Los mensajes programados solo estan disponibles para sesiones Baileys.")
                        return redirect(request.path)
                    data["filtro"] = filtro
                    data["pk"] = pk
                    data["form"] = form = MensajeWhatsAppProgramadoForm()
                    form.fields['fecha'].initial = datetime.now().date()
                    form.fields['hora'].initial  = (datetime.now() + timedelta(minutes=11)).replace(second=0, microsecond=0).time()
                    template = get_template("whatsapp/contacto/form_mensaje_programado.html")
                    return JsonResponse({"result": True, 'data': template.render(data)})
                except Exception as ex:
                    return JsonResponse({"result": False, 'message': str(ex)})
            elif action == 'changeMensajeProgramado':
                try:
                    pk = int(request.GET['id'])
                    filtro = MensajeWhatsAppProgramado.objects.get(pk=pk)
                    data["filtro"] = filtro
                    data["pk"] = pk
                    data["form"] = form = MensajeWhatsAppProgramadoForm(instance=filtro)
                    template = get_template("whatsapp/contacto/form_mensaje_programado.html")
                    return JsonResponse({"result": True, 'data': template.render(data)})
                except Exception as ex:
                    return JsonResponse({"result": False, 'message': str(ex)})

        from django.db.models import Count as DbCount
        criterio, filtros, url_vars = request.GET.get('criterio', '').strip(), Q(status=True, sesion__usuario=request.user), ''
        id = request.GET.get('id', '')
        solo_duplicados = request.GET.get('solo_duplicados', '')
        mis_sesiones = SesionWhatsApp.objects.filter(status=True, usuario=request.user).distinct()
        sesion_id = request.GET.get('sesion_id', str(mis_sesiones.first().id) if mis_sesiones.exists() else '')

        # Números que aparecen en más de una sesión del usuario
        numeros_duplicados = set(
            model.objects.filter(status=True, sesion__usuario=request.user)
            .values('contacto_numero')
            .annotate(_n=DbCount('sesion', distinct=True))
            .filter(_n__gt=1)
            .values_list('contacto_numero', flat=True)
        )
        # Dict {numero: [nombre_sesion, ...]} para mostrar en qué sesiones duplica
        dup_sesiones = {}
        if numeros_duplicados:
            for row in (
                model.objects.filter(status=True, sesion__usuario=request.user, contacto_numero__in=numeros_duplicados)
                .values('contacto_numero', 'sesion__nombre', 'sesion__numero')
                .order_by('contacto_numero', 'sesion__nombre')
            ):
                num = row['contacto_numero']
                label = row['sesion__nombre'] or row['sesion__numero'] or num
                dup_sesiones.setdefault(num, []).append(label)

        if criterio:
            filtros = filtros & (Q(contacto_nombre__icontains=criterio) | Q(contacto_numero__icontains=criterio))
            data["criterio"] = criterio
            url_vars += '&criterio=' + criterio
        if id:
            filtros = filtros & (Q(id=id))
            data["id"] = id
            url_vars += '&id=' + id
        if sesion_id:
            filtros = filtros & (Q(sesion_id=sesion_id))
            data["sesion_id"] = int(sesion_id)
            url_vars += '&sesion_id=' + sesion_id
        if solo_duplicados:
            filtros = filtros & Q(contacto_numero__in=numeros_duplicados)
            url_vars += '&solo_duplicados=1'
            data["solo_duplicados"] = True

        listado = model.objects.filter(filtros)
        data["mis_sesiones"] = mis_sesiones
        data["numeros_duplicados"] = numeros_duplicados
        data["total_duplicados"] = len(numeros_duplicados)
        data["dup_sesiones_json"] = json.dumps(dup_sesiones, ensure_ascii=False)
        data["list_count"] = listado.count()
        data["url_vars"] = url_vars
        paginador(request, listado.order_by('contacto_nombre'), 20, data, url_vars)
        if 'export_to_excel' in request.GET:
            query = listado.values(
                'contacto_nombre',
                'contacto_numero',
                'from_number',
                'fecha_ultimo_mensaje',
                'estado',
            ).query
            response = export_query_to_excel(str(query), [], f'reporte_contactos{str(datetime.now().date())}')
            return response
        return render(request, 'whatsapp/contacto/listado.html', data)
