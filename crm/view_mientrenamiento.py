import json
import sys
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.template.loader import get_template

from core.custom_forms import FormError
from crm.forms import PerfilNegocioIAForm, ProductoIAForm, ServicioIAForm, RespuestaEntrenadaIAForm, IndustriaForm, \
    ActividadEconomicaForm, AgentesIAForm, ApiKeyIAForm
from crm.models import PerfilNegocioIA, ProductoIA, ServicioIA, RespuestaEntrenadaIA, Industria, ActividadEconomica, \
    AgentesIA, DetalleAgentesAI, ApiKeyIA
from core.funciones import addData, secure_module, log


def guardar_detalles_agente(agente, detalles_data, archivos):
    ids_a_mantener = []

    for detalle_data in detalles_data:
        detalle_id = detalle_data.get('id')
        detalle = DetalleAgentesAI.objects.filter(pk=detalle_id, agente=agente).first() if detalle_id else DetalleAgentesAI()

        detalle.agente = agente
        detalle.tipo = detalle_data.get('tipo', 1)
        detalle.descripcion = detalle_data.get('descripcion', '').strip()

        if detalle.tipo == 1:  # ENLACE
            enlace = detalle_data.get('enlace', '').strip()
            if enlace:
                detalle.enlace = enlace
                detalle.tipo_dato_enlace = detalle_data.get('tipo_dato_enlace', 1)
                detalle.archivo = None  # limpiar archivo si antes era tipo 2
                detalle.save()
                ids_a_mantener.append(detalle.id)

        elif detalle.tipo == 2:  # ARCHIVO
            archivo_key = f'detalle_archivo_{detalle_data.get("id_frontend")}'
            if archivo_key in archivos:
                detalle.archivo = archivos[archivo_key]
                detalle.enlace = None  # limpiar enlace si antes era tipo 1
                detalle.tipo_dato_enlace = 1  # resetear a valor por defecto
                detalle.save()
                ids_a_mantener.append(detalle.id)
            elif detalle.pk:  # mantener archivo ya guardado
                detalle.save()
                ids_a_mantener.append(detalle.id)

        elif detalle.tipo == 3:  # TEXTO
            # Solo se requiere guardar descripción y tipo
            detalle.enlace = None
            detalle.archivo = None
            detalle.tipo_dato_enlace = 1
            detalle.save()
            ids_a_mantener.append(detalle.id)

    # Eliminar detalles que ya no existen en el formulario
    DetalleAgentesAI.objects.filter(agente=agente).exclude(id__in=ids_a_mantener).delete()

@login_required
@secure_module
def entrenamiento_ia_view(request):
    data = {
        'titulo': 'Entrenamiento de IA',
        'descripcion': 'Personalización de mi perfil de IA',
        'ruta': request.path,
    }
    addData(request, data)

    try:
        perfil, creado = PerfilNegocioIA.objects.get_or_create(usuario=request.user)

        if request.method == 'POST':
            res_json = []
            action = request.POST['action']
            try:
                with transaction.atomic():
                    if action == 'actualizar_perfil_negocio':
                        form = PerfilNegocioIAForm(request.POST, instance=perfil)
                        if form.is_valid():
                            with transaction.atomic():
                                form.save()
                                log(f"Usuario actualizó su perfil IA: {form.instance}", request, 'change')
                                messages.success(request, "Información guardada correctamente.")
                                res_json.append({'error': False, 'reload': True})
                        else:
                            raise FormError(form)
                    elif action == 'addproducto':
                        form = ProductoIAForm(request.POST, request=request)
                        if form.is_valid():
                            form.instance.perfil = perfil
                            form.save()
                            log(f"Registro un producto IA {form.instance.__str__()}", request, "add",
                                obj=form.instance.id)
                            res_json.append({'error': False, "reload": True})
                        else:
                            raise FormError(form)
                    elif action == 'changeproducto':
                        filtro = ProductoIA.objects.get(pk=int(request.POST['pk']))
                        form = ProductoIAForm(request.POST, instance=filtro, request=request)
                        if form.is_valid() and filtro:
                            form.save()
                            log(f"Edito un producto IA  {form.instance.__str__()}", request, "change",
                                obj=form.instance.id)
                            res_json.append({'error': False, "reload": True})
                        else:
                            raise FormError(form)

                    elif action == 'deleteproducto':
                        filtro = ProductoIA.objects.get(pk=int(request.POST['id']))
                        filtro.status = False
                        filtro.save(request)
                        log(f"Elimino un producto IA {filtro.__str__()}", request, "del", obj=filtro.id)
                        messages.success(request, f"Registro Eliminado")
                        res_json = {"error": False}

                    elif action == 'addservicio':
                        form = ServicioIAForm(request.POST, request=request)
                        if form.is_valid():
                            form.instance.perfil = perfil
                            form.save()
                            log(f"Registro un servicio IA {form.instance.__str__()}", request, "add",
                                obj=form.instance.id)
                            res_json.append({'error': False, "reload": True})
                        else:
                            raise FormError(form)
                    elif action == 'changeservicio':
                        filtro = ServicioIA.objects.get(pk=int(request.POST['pk']))
                        form = ServicioIAForm(request.POST, instance=filtro, request=request)
                        if form.is_valid() and filtro:
                            form.save()
                            log(f"Edito un servicio IA  {form.instance.__str__()}", request, "change",
                                obj=form.instance.id)
                            res_json.append({'error': False, "reload": True})
                        else:
                            raise FormError(form)

                    elif action == 'deleteservicio':
                        filtro = ServicioIA.objects.get(pk=int(request.POST['id']))
                        filtro.status = False
                        filtro.save(request)
                        log(f"Elimino un servicio IA {filtro.__str__()}", request, "del", obj=filtro.id)
                        messages.success(request, f"Registro Eliminado")
                        res_json = {"error": False}

                    elif action == 'addrespuesta':
                        form = RespuestaEntrenadaIAForm(request.POST, request=request)
                        if form.is_valid():
                            form.instance.perfil = perfil
                            form.save()
                            log(f"Registro un respuesta IA {form.instance.__str__()}", request, "add",
                                obj=form.instance.id)
                            res_json.append({'error': False, "reload": True})
                        else:
                            raise FormError(form)
                    elif action == 'changerespuesta':
                        filtro = RespuestaEntrenadaIA.objects.get(pk=int(request.POST['pk']))
                        form = RespuestaEntrenadaIAForm(request.POST, instance=filtro, request=request)
                        if form.is_valid() and filtro:
                            form.save()
                            log(f"Edito un respuesta IA  {form.instance.__str__()}", request, "change",
                                obj=form.instance.id)
                            res_json.append({'error': False, "reload": True})
                        else:
                            raise FormError(form)

                    elif action == 'deleterespuesta':
                        filtro = RespuestaEntrenadaIA.objects.get(pk=int(request.POST['id']))
                        filtro.status = False
                        filtro.save(request)
                        log(f"Elimino un respuesta IA {filtro.__str__()}", request, "del", obj=filtro.id)
                        messages.success(request, f"Registro Eliminado")
                        res_json = {"error": False}
                    elif action == 'add_new_industria':
                        form = IndustriaForm(request.POST, request=request)
                        if form.is_valid():
                            form.save()
                            log(f"Registro una industria {form.instance.__str__()}", request, "add",
                                obj=form.instance.id)
                            res_json.append({'error': False, 'reload': True, 'close_popup': True, 'message': 'Registro creado exitosamente'})
                        else:
                            raise FormError(form)

                    elif action == 'add_new_actividad':
                        form = ActividadEconomicaForm(request.POST, request=request)
                        if form.is_valid():
                            form.save()
                            log(f"Registro una actividad economica {form.instance.__str__()}", request, "add",
                                obj=form.instance.id)
                            res_json.append({'error': False, 'reload': True, 'close_popup': True, 'message': 'Registro creado exitosamente'})
                        else:
                            raise FormError(form)

                    elif action == 'addagente':
                        form = AgentesIAForm(request.POST, request.FILES, request=request)
                        if form.is_valid():
                            form.instance.perfil = perfil
                            agente = form.save()

                            # Procesar los detalles si existen
                            if 'detalles_json' in request.POST:
                                detalles_data = json.loads(request.POST['detalles_json'])
                                guardar_detalles_agente(agente, detalles_data, request.FILES)

                            log(f"Registro un agente IA {agente.__str__()}", request, "add", obj=agente.id)
                            res_json.append({'error': False, "reload": True})
                        else:
                            raise FormError(form)
                    elif action == 'changeagente':
                        filtro = AgentesIA.objects.get(pk=int(request.POST['pk']))
                        form = AgentesIAForm(request.POST, request.FILES, instance=filtro, request=request)
                        if form.is_valid() and filtro:
                            agente = form.save()

                            # Eliminar detalles existentes y crear los nuevos
                            if 'detalles_json' in request.POST:
                                detalles_data = json.loads(request.POST['detalles_json'])
                                guardar_detalles_agente(agente, detalles_data, request.FILES)

                            log(f"Edito un agente IA {agente.__str__()}", request, "change", obj=agente.id)
                            res_json.append({'error': False, "reload": True})
                        else:
                            raise FormError(form)

                    elif action == 'deleteagente':
                        filtro = AgentesIA.objects.get(pk=int(request.POST['id']))
                        filtro.status = False
                        filtro.save(request)
                        log(f"Elimino un agente {filtro.__str__()}", request, "del", obj=filtro.id)
                        messages.success(request, f"Registro Eliminado")
                        res_json = {"error": False}

                    elif action == 'addapikey':
                        form = ApiKeyIAForm(request.POST, request.FILES, request=request)
                        if form.is_valid():
                            form.instance.perfil = perfil
                            agente = form.save()

                            # Procesar los detalles si existen
                            if 'detalles_json' in request.POST:
                                detalles_data = json.loads(request.POST['detalles_json'])
                                guardar_detalles_agente(agente, detalles_data, request.FILES)

                            log(f"Registro un api key IA {agente.__str__()}", request, "add", obj=agente.id)
                            res_json.append({'error': False, "reload": True})
                        else:
                            raise FormError(form)
                    elif action == 'changeapikey':
                        filtro = ApiKeyIA.objects.get(pk=int(request.POST['pk']))
                        form = ApiKeyIAForm(request.POST, request.FILES, instance=filtro, request=request)
                        if form.is_valid() and filtro:
                            form.save()
                            log(f"Edito un api key IA {form.instance.__str__()}", request, "change", obj=form.instance.id)
                            res_json.append({'error': False, "reload": True})
                        else:
                            raise FormError(form)

                    elif action == 'deleteapikey':
                        filtro = ApiKeyIA.objects.get(pk=int(request.POST['id']))
                        filtro.status = False
                        filtro.save(request)
                        log(f"Elimino un api key IA {filtro.__str__()}", request, "del", obj=filtro.id)
                        messages.success(request, f"Registro Eliminado")
                        res_json = {"error": False}

            except ValueError as ex:
                res_json.append({'error': True, "message": str(ex)})
            except FormError as ex:
                res_json.append(ex.dict_error)
            except Exception as ex:
                res_json.append({'error': True, "message": f"Intente Nuevamente: {ex}"})
            return JsonResponse(res_json, safe=False)

        else:
            if 'action' in request.GET:
                data["action"] = action = request.GET['action']
                if action == 'addproducto':
                    try:
                        data["form"] = ProductoIAForm()
                        template = get_template("crm/entrenamiento/producto/form.html")
                        return JsonResponse({"result": True, 'data': template.render(data)})
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})

                elif action == 'changeproducto':
                    try:
                        pk = int(request.GET['id'])
                        filtro = ProductoIA.objects.get(pk=pk)
                        data["filtro"] = filtro
                        data["form"] = ProductoIAForm(instance=filtro)
                        template = get_template("crm/entrenamiento/producto/form.html")
                        return JsonResponse({"result": True, 'data': template.render(data)})
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})

                elif action == 'addservicio':
                    try:
                        data["form"] = ServicioIAForm()
                        template = get_template("crm/entrenamiento/servicio/form.html")
                        return JsonResponse({"result": True, 'data': template.render(data)})
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})

                elif action == 'changeservicio':
                    try:
                        pk = int(request.GET['id'])
                        filtro = ServicioIA.objects.get(pk=pk)
                        data["filtro"] = filtro
                        data["form"] = ServicioIAForm(instance=filtro)
                        template = get_template("crm/entrenamiento/servicio/form.html")
                        return JsonResponse({"result": True, 'data': template.render(data)})
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})

                elif action == 'addrespuesta':
                    try:
                        data["form"] = RespuestaEntrenadaIAForm()
                        template = get_template("crm/entrenamiento/respuesta/form.html")
                        return JsonResponse({"result": True, 'data': template.render(data)})
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})

                elif action == 'changerespuesta':
                    try:
                        pk = int(request.GET['id'])
                        filtro = RespuestaEntrenadaIA.objects.get(pk=pk)
                        data["filtro"] = filtro
                        data["form"] = RespuestaEntrenadaIAForm(instance=filtro)
                        template = get_template("crm/entrenamiento/respuesta/form.html")
                        return JsonResponse({"result": True, 'data': template.render(data)})
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})

                elif action == 'add_new_industria':
                    try:
                        data['titulo'] = f'Formulario de Industria'
                        data["form"] = IndustriaForm()
                        return render(request, 'crm/industria/form_href.html', data)
                    except Exception as ex:
                        pass

                elif action == 'datos_popup_industria':
                    ids = json.loads(request.GET['ids'])
                    data["listado"] = listado = Industria.objects.filter(status=True)
                    if listado.exclude(id__in=ids).exists():
                        data["ids"] = list(listado.exclude(id__in=ids).values_list('id', flat=True))
                        template = get_template("crm/industria/popup.html")
                        json_content = template.render(data)
                        return JsonResponse({"result": True, 'data': json_content, 'nuevo_registro': True})
                    else:
                        return JsonResponse({"result": True, 'nuevo_registro': False})

                elif action == 'add_new_actividad':
                    try:
                        data['titulo'] = f'Formulario de Industria'
                        data["form"] = ActividadEconomicaForm()
                        return render(request, 'crm/actividad_economica/form_href.html', data)
                    except Exception as ex:
                        pass

                elif action == 'datos_popup_actividad':
                    ids = json.loads(request.GET['ids'])
                    data["listado"] = listado = ActividadEconomica.objects.filter(status=True)
                    if listado.exclude(id__in=ids).exists():
                        data["ids"] = list(listado.exclude(id__in=ids).values_list('id', flat=True))
                        template = get_template("crm/actividad_economica/popup.html")
                        json_content = template.render(data)
                        return JsonResponse({"result": True, 'data': json_content, 'nuevo_registro': True})
                    else:
                        return JsonResponse({"result": True, 'nuevo_registro': False})

                if action == 'addagente':
                    try:
                        data["form"] = AgentesIAForm()
                        template = get_template("crm/entrenamiento/agente/form.html")
                        return JsonResponse({"result": True, 'data': template.render(data)})
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})

                elif action == 'changeagente':
                    try:
                        pk = int(request.GET['id'])
                        filtro = AgentesIA.objects.get(pk=pk)
                        data["filtro"] = filtro
                        data["form"] = AgentesIAForm(instance=filtro)
                        data['detalles_existentes'] = filtro.obtener_detalles_agente()
                        template = get_template("crm/entrenamiento/agente/form.html")
                        return JsonResponse({"result": True, 'data': template.render(data)})
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})

                if action == 'addapikey':
                    try:
                        data["form"] = ApiKeyIAForm()
                        template = get_template("crm/entrenamiento/apikey/form.html")
                        return JsonResponse({"result": True, 'data': template.render(data)})
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})

                elif action == 'changeapikey':
                    try:
                        pk = int(request.GET['id'])
                        filtro = ApiKeyIA.objects.get(pk=pk)
                        data["filtro"] = filtro
                        data["form"] = ApiKeyIAForm(instance=filtro)
                        template = get_template("crm/entrenamiento/apikey/form.html")
                        return JsonResponse({"result": True, 'data': template.render(data)})
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})


            data['form'] = PerfilNegocioIAForm(instance=perfil)
            data['productos'] = perfil.get_productos()
            data['servicios'] = perfil.get_servicios()
            data['respuestas'] = perfil.get_respuestas()
            data['agentes'] = perfil.get_agentes()
            data['apis'] = perfil.get_apis()

    except Exception as ex:
        error_line = sys.exc_info()[-1].tb_lineno
        messages.error(request, f"Error inesperado: {ex} - Línea {error_line}")
        return redirect('/panel/')

    return render(request, 'crm/entrenamiento/form.html', data)
