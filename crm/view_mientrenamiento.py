import json
import os
import sys
from django.conf import settings
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
from core.funciones import addData, secure_module, log, get_encrypt


def guardar_detalles_agente(agente, detalles_data, archivos):
    try:
        # Lista para guardar los IDs de los detalles que deben mantenerse activos
        ids_activos = []

        for detalle_data in detalles_data:
            detalle_id = detalle_data.get('id')
            # Buscar el detalle existente o crear uno nuevo
            detalle = DetalleAgentesAI.objects.filter(pk=detalle_id,
                                                      agente=agente).first() if detalle_id else DetalleAgentesAI()

            detalle.agente = agente
            detalle.tipo = detalle_data.get('tipo', 1)
            detalle.descripcion = detalle_data.get('descripcion', '').strip()
            detalle.status = True  # Siempre True para los que estamos procesando

            if detalle.tipo == 1:  # ENLACE
                enlace = detalle_data.get('enlace', '').strip()
                if enlace:
                    detalle.enlace = enlace
                    detalle.tipo_dato_enlace = detalle_data.get('tipo_dato_enlace', 1)
                    detalle.archivo = None  # Limpiar archivo si existía

                    # Campos específicos para enlaces
                    detalle.requiere_token = detalle_data.get('requiere_token', False)
                    detalle.token_autorizacion = detalle_data.get('token_autorizacion', '').strip() if detalle_data.get('requiere_token') else None
                    detalle.usar_cache = detalle_data.get('usar_cache', False)
                    detalle.tiempo_cache_horas = detalle_data.get('tiempo_cache_horas', 1)
                detalle.save()
                ids_activos.append(detalle.id)

            elif detalle.tipo == 2:  # ARCHIVO
                archivo_key = f'detalle_archivo_{detalle_data.get("id_frontend")}'
                if archivo_key in archivos:
                    detalle.archivo = archivos[archivo_key]
                    detalle.enlace = None  # Limpiar enlace si existía
                    detalle.tipo_dato_enlace = 1  # Valor por defecto

                    # Limpiar campos específicos de enlaces
                    detalle.requiere_token = False
                    detalle.token_autorizacion = None
                    detalle.usar_cache = False
                    detalle.tiempo_cache_horas = 1
                detalle.save()
                ids_activos.append(detalle.id)

            elif detalle.tipo == 3:  # TEXTO
                detalle.enlace = None
                detalle.archivo = None
                detalle.tipo_dato_enlace = 1

                # Limpiar campos específicos de enlaces
                detalle.requiere_token = False
                detalle.token_autorizacion = None
                detalle.usar_cache = False
                detalle.tiempo_cache_horas = 1
                detalle.save()
                ids_activos.append(detalle.id)

        # Actualizar a status=False los detalles que no están en ids_activos
        DetalleAgentesAI.objects.filter(agente=agente).exclude(id__in=ids_activos).update(status=False)

        return True
    except Exception as ex:
        line = sys.exc_info()[-1].tb_lineno
        print(f"Error en línea {line}: {str(ex)}")
        return False

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
                    elif action == 'procesaragente':
                        filtro = AgentesIA.objects.get(pk=int(request.POST['id']), perfil=perfil)
                        # Disparar el mismo proceso que DetalleAgentesAI.save()
                        # pero desde el agente directamente
                        from agents_ai.vectorstore_manager import VectorStoreManager
                        base_dir = os.path.join(settings.MEDIA_ROOT, 'vectorstores')
                        nombre_vs = f"agente_{filtro.id}"
                        textos_raw = []
                        detalles_archivo = filtro.detalleagentesai_set.filter(status=True, tipo=2, archivo__isnull=False)
                        detalles_texto = filtro.detalleagentesai_set.filter(status=True, tipo=3).exclude(descripcion__isnull=True).exclude(descripcion='')
                        for det in detalles_archivo:
                            try:
                                raw = VectorStoreManager._extract_raw_text(det.archivo.path)
                                if raw:
                                    textos_raw.append(raw)
                            except Exception:
                                pass
                        for det in detalles_texto:
                            if det.descripcion:
                                textos_raw.append(det.descripcion.strip())
                        if not textos_raw:
                            res_json = {"error": True, "message": "No hay archivos ni textos cargados en este agente."}
                        else:
                            texto_completo = "\n\n".join(textos_raw)
                            _UMBRAL = 40_000
                            filtro.contexto_estatico = texto_completo[:_UMBRAL]
                            if len(texto_completo) > _UMBRAL:
                                # Construir FAISS para la parte que no cabe
                                apikey_obj = filtro.apikey.filter(estado=True).first()
                                if apikey_obj:
                                    try:
                                        vs_manager = VectorStoreManager(
                                            storage_dir=base_dir,
                                            provider='gemini' if apikey_obj.proveedor == 2 else 'openai',
                                            apikey=apikey_obj.descripcion
                                        )
                                        documentos = []
                                        for det in detalles_archivo:
                                            documentos.extend(vs_manager.load_and_split(det.archivo.path, metadata={"detalle_id": det.id}))
                                        for det in detalles_texto:
                                            if det.descripcion:
                                                documentos.extend(vs_manager.build_from_string(det.descripcion, metadata={"detalle_id": det.id}))
                                        if documentos:
                                            vs_path = vs_manager.build_and_save(documentos, nombre_vs)
                                            filtro.vectorstore_path = os.path.relpath(vs_path, settings.MEDIA_ROOT)
                                    except Exception as ex:
                                        pass
                                filtro.save()
                                res_json = {"error": False, "message": f"✅ Procesado: {len(texto_completo):,} chars. Documento grande → FAISS + contexto estático.", "reload": True}
                            else:
                                filtro.vectorstore_path = None
                                filtro.save()
                                res_json = {"error": False, "message": f"✅ Procesado: {len(texto_completo):,} chars. Contexto estático listo (sin FAISS).", "reload": True}
                    elif action == 'reactivarapikey':
                        filtro = ApiKeyIA.objects.get(pk=int(request.POST['id']), perfil=perfil)
                        filtro.estado = True
                        filtro.msgerror = None
                        filtro.save()
                        log(f"API Key reactivada {filtro}", request, "change", obj=filtro.id)
                        res_json = {"error": False, "reload": True}
                    elif action == 'testapikey':
                        filtro = ApiKeyIA.objects.get(pk=int(request.POST['id']), perfil=perfil)
                        try:
                            if filtro.proveedor == 2:  # Gemini
                                from langchain_google_genai import ChatGoogleGenerativeAI
                                llm = ChatGoogleGenerativeAI(model='gemini-2.5-flash', google_api_key=filtro.descripcion)
                            else:  # OpenAI
                                from langchain_community.chat_models import ChatOpenAI
                                llm = ChatOpenAI(model_name='gpt-4o-mini', openai_api_key=filtro.descripcion)
                            llm.invoke('responde solo: ok')
                            # Éxito — reactivar si estaba desactivada
                            if not filtro.estado:
                                filtro.estado = True
                                filtro.msgerror = None
                                filtro.save()
                            res_json = {"error": False, "message": "✅ API Key válida y funcional.", "activo": True}
                        except Exception as ex:
                            filtro.estado = False
                            filtro.msgerror = str(ex)[:500]
                            filtro.save()
                            res_json = {"error": False, "message": f"❌ Error: {str(ex)[:300]}", "activo": False}
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
                elif action == 'vercontexto':
                    try:
                        pk = int(request.GET['id'])
                        filtro = AgentesIA.objects.get(pk=pk, perfil=perfil)
                        contexto = filtro.contexto_estatico or ''
                        prompt_tpl = filtro.prompt_template or ''
                        # Armar preview del prompt completo con valores de ejemplo
                        prompt_preview = ''
                        try:
                            prompt_preview = prompt_tpl.replace(
                                '{context}', contexto[:3000] + ('…' if len(contexto) > 3000 else '')
                            ).replace(
                                '{descripcion_agente}', filtro.descripcion or ''
                            ).replace(
                                '{contexto_extra}', '[Historial de la conversación irá aquí]'
                            ).replace(
                                '{question}', '[Pregunta del usuario irá aquí]'
                            )
                        except Exception:
                            prompt_preview = prompt_tpl
                        detalles = list(filtro.detalleagentesai_set.filter(status=True).values(
                            'tipo', 'archivo', 'enlace', 'descripcion'
                        ))
                        return JsonResponse({
                            "result": True,
                            "nombre": filtro.nombre,
                            "descripcion": filtro.descripcion or '',
                            "chars_contexto": len(contexto),
                            "chars_prompt": len(prompt_tpl),
                            "contexto": contexto,
                            "prompt_preview": prompt_preview,
                            "tiene_faiss": bool(filtro.vectorstore_path),
                            "modo": "estatico" if contexto and not filtro.vectorstore_path else ("faiss" if filtro.vectorstore_path else "sin_datos"),
                            "detalles_count": len(detalles),
                            "detalles": detalles,
                        })
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
            agentes = list(perfil.get_agentes())
            for a in agentes:
                ok, enc = get_encrypt(a.id)
                a.chat_url = f'/crm/entrenamiento/chat/{enc}/' if ok else ''
                keys = list(a.apikey.all())
                a.keys_total = len(keys)
                a.keys_activas = sum(1 for k in keys if k.estado)
                # estado: 'ok' → al menos una activa, 'err' → todas inactivas, 'warn' → sin keys
                if not keys:
                    a.estado_agente = 'warn'
                elif a.keys_activas > 0:
                    a.estado_agente = 'ok'
                else:
                    a.estado_agente = 'err'
            data['agentes'] = agentes
            data['apis'] = perfil.get_apis()
    except Exception as ex:
        error_line = sys.exc_info()[-1].tb_lineno
        messages.error(request, f"Error inesperado: {ex} - Línea {error_line}")
        return redirect('/panel/')

    return render(request, 'crm/entrenamiento/form.html', data)
