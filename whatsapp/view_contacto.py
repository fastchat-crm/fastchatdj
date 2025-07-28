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
                    data["filtro"] = filtro
                    data["pk"] = pk
                    data["form"] = MensajeWhatsAppProgramadoForm()
                    template = get_template("whatsapp/contacto/form_mensaje_programado.html")
                    return JsonResponse({"result": True, 'data': template.render(data)})
                except Exception as ex:
                    return JsonResponse({"result": False, 'message': str(ex)})

        criterio, filtros, url_vars = request.GET.get('criterio', '').strip(), Q(status=True, sesion__usuario=request.user), ''
        id = request.GET.get('id', '')
        mis_sesiones = SesionWhatsApp.objects.filter(status=True, usuario=request.user).distinct()
        sesion_id = request.GET.get('sesion_id', str(mis_sesiones.first().id) if mis_sesiones.exists() else '')
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
        listado = model.objects.filter(filtros)
        data["mis_sesiones"] = mis_sesiones
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
