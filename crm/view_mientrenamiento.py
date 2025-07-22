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
    try:
        ids_a_mantener = []

        for detalle_data in detalles_data:
            detalle_id = detalle_data.get('id')
            detalle = DetalleAgentesAI.objects.filter(pk=detalle_id,
                                                      agente=agente).first() if detalle_id else DetalleAgentesAI()

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
    except Exception as ex:
        line = sys.exc_info()[-1].tb_lineno
        pass

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
                    if action == 'addagente':
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
                line = sys.exc_info()[-1].tb_lineno
                res_json.append({'error': True, "message": f"Intente Nuevamente: {ex}"})
            return JsonResponse(res_json, safe=False)
        else:
            if 'action' in request.GET:
                data["action"] = action = request.GET['action']
                if action == 'addagente':
                    try:
                        form = AgentesIAForm()
                        form.fields['apikey'].queryset = ApiKeyIA.objects.filter(perfil=perfil, status=True)
                        data["form"] = form
                        template = get_template("crm/entrenamiento/agente/form.html")
                        return JsonResponse({"result": True, 'data': template.render(data)})
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})
                elif action == 'changeagente':
                    try:
                        pk = int(request.GET['id'])
                        filtro = AgentesIA.objects.get(pk=pk)
                        data["filtro"] = filtro
                        data["form"] = form = AgentesIAForm(instance=filtro)
                        form.fields['apikey'].queryset = ApiKeyIA.objects.filter(perfil=perfil, status=True)
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
            data['agentes'] = perfil.get_agentes()
            data['apis'] = perfil.get_apis()
    except Exception as ex:
        error_line = sys.exc_info()[-1].tb_lineno
        messages.error(request, f"Error inesperado: {ex} - Línea {error_line}")
        return redirect('/panel/')

    return render(request, 'crm/entrenamiento/form.html', data)
