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
    AgentesIA, DetalleAgentesAI, ApiKeyIA, ReglaFinConversacion, AccionFinConversacion, ConsumoTokenIA, \
    AlertaConsumoIA, AuditoriaAgenteIA
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
                    elif action == 'agente_regla_fin_guardar':
                        agente = AgentesIA.objects.get(id=request.POST['pk'], perfil=perfil)
                        regla, _ = ReglaFinConversacion.objects.get_or_create(agente=agente)
                        regla.activo = request.POST.get('activo') == 'true'
                        regla.usar_senal_llm = request.POST.get('usar_senal_llm') == 'true'
                        regla.frases_cierre = request.POST.get('frases_cierre', '').strip() or None
                        regla.save()
                        return JsonResponse({'error': False})

                    elif action == 'agente_regla_fin_accion_add':
                        agente = AgentesIA.objects.get(id=request.POST['pk'], perfil=perfil)
                        regla, _ = ReglaFinConversacion.objects.get_or_create(agente=agente)
                        tipo = request.POST.get('tipo', 'ninguna')
                        destino = request.POST.get('destino', '').strip() or None
                        plantilla_mensaje = request.POST.get('plantilla_mensaje', '').strip() or None
                        accion = AccionFinConversacion.objects.create(
                            regla=regla, tipo=tipo,
                            destino=destino, plantilla_mensaje=plantilla_mensaje,
                        )
                        return JsonResponse({
                            'error': False,
                            'accion': {
                                'id': accion.id,
                                'tipo': accion.get_tipo_display(),
                                'destino': accion.destino or '',
                            }
                        })

                    elif action == 'agente_regla_fin_accion_delete':
                        accion = AccionFinConversacion.objects.get(id=request.POST['accion_id'])
                        accion.delete()
                        return JsonResponse({'error': False})

                    elif action == 'alerta_consumo_save':
                        from autenticacion.models import Usuario as UsuarioModel
                        pk = int(request.POST['id'])
                        apikey = ApiKeyIA.objects.get(pk=pk, perfil=perfil)
                        alerta, _ = AlertaConsumoIA.objects.get_or_create(apikey=apikey)
                        alerta.umbral_diario  = int(request.POST.get('umbral_diario',  0) or 0)
                        alerta.umbral_mensual = int(request.POST.get('umbral_mensual', 0) or 0)
                        alerta.save()
                        ids_usuarios = json.loads(request.POST.get('notificar_a', '[]'))
                        alerta.notificar_a.set(UsuarioModel.objects.filter(pk__in=[int(i) for i in ids_usuarios if str(i).isdigit()]))
                        log(f"Alertas de consumo configuradas para ApiKey {apikey}", request, "change", obj=apikey.id)
                        return JsonResponse({'error': False})

                    elif action == 'reactivarapikey':
                        filtro = ApiKeyIA.objects.get(pk=int(request.POST['id']), perfil=perfil)
                        filtro.estado = True
                        filtro.msgerror = None
                        filtro.save()
                        log(f"API Key reactivada {filtro}", request, "change", obj=filtro.id)
                        res_json = {"error": False, "reload": True}
                    elif action == 'auditoria_generar':
                        from agents_ai.auditor_agente import ejecutar_auditoria
                        agente = AgentesIA.objects.get(pk=int(request.POST['agente_id']), perfil=perfil)
                        dias = int(request.POST.get('dias', 30) or 30)
                        auditoria = ejecutar_auditoria(agente, usuario=request.user, dias=dias)
                        if auditoria.estado == 'error':
                            res_json = {'error': True, 'message': auditoria.error_mensaje or 'Fallo la auditoria'}
                        else:
                            res_json = {
                                'error': False,
                                'auditoria_id': auditoria.id,
                                'tokens': auditoria.tokens_usados,
                                'modelo': auditoria.modelo_usado,
                                'razonamiento': auditoria.razonamiento,
                                'sugerencias': auditoria.sugerencias,
                                'metricas': auditoria.metricas,
                            }
                    elif action == 'auditoria_aplicar':
                        from agents_ai.auditor_agente import aplicar_sugerencia
                        auditoria = AuditoriaAgenteIA.objects.select_related('agente__perfil').get(
                            pk=int(request.POST['auditoria_id']), agente__perfil=perfil,
                        )
                        campo = request.POST.get('campo')
                        if campo not in ('prompt_template', 'contexto_estatico'):
                            raise ValueError('Campo no soportado')
                        aplicar_sugerencia(auditoria, campo, usuario=request.user)
                        log(f"Aplicada sugerencia IA ({campo}) del agente {auditoria.agente}", request, "change", obj=auditoria.agente.id)
                        res_json = {'error': False, 'campo': campo, 'estado': auditoria.estado}
                    elif action == 'auditoria_revertir':
                        from agents_ai.auditor_agente import revertir_auditoria
                        auditoria = AuditoriaAgenteIA.objects.select_related('agente__perfil').get(
                            pk=int(request.POST['auditoria_id']), agente__perfil=perfil,
                        )
                        revertir_auditoria(auditoria, usuario=request.user)
                        log(f"Revertida auditoria IA del agente {auditoria.agente}", request, "change", obj=auditoria.agente.id)
                        res_json = {'error': False, 'estado': auditoria.estado}
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

                    # ── Herramientas Agente (tool-calling dinámico) ───────────
                    elif action == 'herramienta_save':
                        from crm.forms import HerramientaAgenteForm
                        from crm.models import HerramientaAgente as _HA
                        from django.core.exceptions import ValidationError as _VE
                        agente = AgentesIA.objects.get(pk=int(request.POST['agente_id']), perfil=perfil)
                        pk = request.POST.get('pk')
                        instancia = _HA.objects.get(pk=int(pk), agente=agente) if pk else None
                        form = HerramientaAgenteForm(request.POST, instance=instancia, request=request)
                        if not form.is_valid():
                            raise FormError(form)
                        obj = form.save(commit=False)
                        obj.agente = agente
                        # Parámetros (schema dinámico) y headers desde JSON del front
                        try:
                            obj.parametros = json.loads(request.POST.get('parametros_json', '[]'))
                        except Exception:
                            raise ValueError('Parámetros inválidos (JSON malformado).')
                        try:
                            obj.headers = json.loads(request.POST.get('headers_json', '{}'))
                        except Exception:
                            raise ValueError('Headers inválidos (JSON malformado).')
                        try:
                            obj.clean()
                        except _VE as ve:
                            mensajes = '; '.join(f"{k}: {', '.join(v)}" for k, v in ve.message_dict.items()) if hasattr(ve, 'message_dict') else str(ve)
                            raise ValueError(mensajes)
                        obj.save()
                        log(f"{'Edito' if pk else 'Creo'} herramienta '{obj.nombre}' del agente {agente.nombre}",
                            request, "change" if pk else "add", obj=obj.id)
                        return JsonResponse({'error': False, 'id': obj.id})

                    elif action == 'herramienta_delete':
                        from crm.models import HerramientaAgente as _HA
                        filtro = _HA.objects.get(pk=int(request.POST['id']), agente__perfil=perfil)
                        filtro.status = False
                        filtro.save(request)
                        log(f"Elimino herramienta {filtro.nombre}", request, "del", obj=filtro.id)
                        return JsonResponse({'error': False})

                    elif action == 'herramienta_toggle_activo':
                        from crm.models import HerramientaAgente as _HA
                        filtro = _HA.objects.get(pk=int(request.POST['id']), agente__perfil=perfil)
                        filtro.activo = not filtro.activo
                        filtro.save(update_fields=['activo'])
                        return JsonResponse({'error': False, 'activo': filtro.activo})

                    elif action == 'herramienta_simular':
                        from django.utils import timezone as _tz
                        from types import SimpleNamespace
                        from agents_ai.agente_consultor import AgenteConsultor
                        from crm.models import LogHerramientaAgente as _Log, HerramientaAgente as _HA

                        agente_id = int(request.POST.get('agente_id') or 0)
                        agente = AgentesIA.objects.get(pk=agente_id, perfil=perfil)
                        # Validar que tenga al menos una herramienta activa
                        if not agente.herramientas.filter(activo=True, status=True).exists():
                            return JsonResponse({'error': True, 'message': 'El agente no tiene herramientas activas para simular.'})

                        mensaje = (request.POST.get('mensaje') or '').strip()
                        if not mensaje:
                            return JsonResponse({'error': True, 'message': 'Escribe un mensaje.'})

                        apikey_obj = agente.apikey.filter(estado=True).first()
                        if not apikey_obj:
                            return JsonResponse({'error': True, 'message': 'El agente no tiene una API Key activa.'})

                        vs_path = os.path.join(settings.MEDIA_ROOT, agente.vectorstore_path) if agente.vectorstore_path else None
                        vs_enlaces_path = None
                        try:
                            if agente.vectorstore_enlaces_path:
                                vs_enlaces_path = os.path.join(settings.MEDIA_ROOT, agente.vectorstore_enlaces_path)
                        except Exception:
                            pass

                        session_id = f"sim-herr-{agente.id}-{request.user.id}"
                        fake_conv = SimpleNamespace(id=session_id, contacto=None)

                        before = _tz.now()
                        try:
                            consultor = AgenteConsultor(
                                vectorstore_path=vs_path, vectorstore_enlaces_path=vs_enlaces_path,
                                provider=apikey_obj.proveedor, apikey=apikey_obj.descripcion,
                                conversacion=fake_conv,
                                prompt_template_text=(agente.prompt_template or '').strip() or PROMPT_TEMPLATES.get('es', ''),
                                contexto_estatico=agente.contexto_estatico or None,
                                perfil=agente.perfil, agente=agente,
                            )
                            resultado = consultor.consultar_con_listas(mensaje, agente.descripcion)
                        except Exception as ex:
                            return JsonResponse({'error': True, 'message': f'Fallo invocando el agente: {ex}'})

                        # Capturar invocaciones de HerramientaAgente disparadas durante este turno
                        logs_qs = _Log.objects.filter(
                            herramienta__agente=agente, fecha__gte=before,
                        ).select_related('herramienta').order_by('fecha')[:10]
                        traza = []
                        for lg in logs_qs:
                            traza.append({
                                'herramienta': lg.herramienta.nombre_amigable,
                                'slug': lg.herramienta.nombre,
                                'url': lg.request_url,
                                'params': lg.request_params or {},
                                'status': lg.response_status,
                                'duracion_ms': lg.duracion_ms,
                                'exito': lg.exito,
                                'error': lg.error_mensaje,
                                'response_preview': (lg.response_body or '')[:400],
                            })

                        return JsonResponse({
                            'error': False,
                            'respuesta': resultado.respuesta,
                            'tokens_total': resultado.tokens_total,
                            'traza': traza,
                        })

                    elif action == 'herramienta_simular_reset':
                        from agents_ai.memoria_django import DjangoChatMessageHistory
                        agente_id = int(request.POST.get('agente_id') or 0)
                        agente = AgentesIA.objects.get(pk=agente_id, perfil=perfil)
                        session_id = f"sim-herr-{agente.id}-{request.user.id}"
                        DjangoChatMessageHistory(session_id=session_id).clear()
                        return JsonResponse({'error': False})

                    elif action == 'herramienta_ia_asistida':
                        from crm.herramienta_templates import PROMPT_IA_ASISTIDA
                        agente_id = int(request.POST.get('agente_id') or 0)
                        agente = AgentesIA.objects.get(pk=agente_id, perfil=perfil)
                        frase = (request.POST.get('frase') or '').strip()
                        if not frase:
                            return JsonResponse({'error': True, 'message': 'Describe qué necesita consultar la herramienta.'})
                        apikey_obj = agente.apikey.filter(estado=True).first()
                        if not apikey_obj:
                            return JsonResponse({'error': True, 'message': 'El agente no tiene una API Key activa.'})
                        try:
                            # Usamos el mismo patrón del auditor: forzar JSON nativo en Gemini/OpenAI
                            if apikey_obj.proveedor == 2:
                                from langchain_google_genai import ChatGoogleGenerativeAI
                                llm = ChatGoogleGenerativeAI(
                                    model='gemini-2.5-flash', google_api_key=apikey_obj.descripcion,
                                    max_output_tokens=4000, temperature=0.3,
                                    model_kwargs={'response_mime_type': 'application/json'},
                                )
                            else:
                                from langchain_community.chat_models import ChatOpenAI
                                llm = ChatOpenAI(
                                    model_name='gpt-4o-mini', openai_api_key=apikey_obj.descripcion,
                                    max_tokens=4000, temperature=0.3,
                                    model_kwargs={'response_format': {'type': 'json_object'}},
                                )
                            prompt = PROMPT_IA_ASISTIDA.format(descripcion_usuario=frase)
                            msg = llm.invoke(prompt)
                            texto = (getattr(msg, 'content', '') or '').strip()
                            # Quitar posibles fences
                            if texto.startswith('```'):
                                texto = texto.strip('`')
                                if texto.lower().startswith('json'):
                                    texto = texto[4:].strip()
                            config = json.loads(texto)
                            return JsonResponse({'error': False, 'config': config})
                        except Exception as ex:
                            return JsonResponse({'error': True, 'message': f'No pude generar la configuración: {ex}'})

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
                        data['regla_fin'] = getattr(filtro, 'regla_fin', None)
                        data['acciones_fin'] = data['regla_fin'].acciones.filter(status=True) if data['regla_fin'] else []
                        data['herramientas'] = filtro.herramientas.filter(status=True).order_by('nombre')
                        template = get_template("crm/entrenamiento/agente/form.html")
                        return JsonResponse({"result": True, 'data': template.render(data)})
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})
                elif action == 'auditoria_historial':
                    try:
                        pk = int(request.GET['id'])
                        agente = AgentesIA.objects.get(pk=pk, perfil=perfil)
                        historial = AuditoriaAgenteIA.objects.filter(agente=agente).order_by('-fecha')[:20]
                        data_rows = []
                        for a in historial:
                            data_rows.append({
                                'id': a.id,
                                'fecha': a.fecha.strftime('%d/%m/%Y %H:%M'),
                                'estado': a.get_estado_display(),
                                'estado_raw': a.estado,
                                'modelo': a.modelo_usado or '',
                                'tokens': a.tokens_usados,
                                'usuario': str(a.usuario) if a.usuario else '',
                                'resumen': (a.razonamiento or '')[:150],
                            })
                        return JsonResponse({'result': True, 'historial': data_rows})
                    except Exception as ex:
                        return JsonResponse({'result': False, 'message': str(ex)})
                elif action == 'auditoria_detalle':
                    try:
                        pk = int(request.GET['id'])
                        auditoria = AuditoriaAgenteIA.objects.select_related('agente__perfil').get(pk=pk, agente__perfil=perfil)
                        return JsonResponse({
                            'result': True,
                            'auditoria_id': auditoria.id,
                            'estado': auditoria.estado,
                            'estado_display': auditoria.get_estado_display(),
                            'razonamiento': auditoria.razonamiento or '',
                            'sugerencias': auditoria.sugerencias or {},
                            'metricas': auditoria.metricas or {},
                            'snapshot_prompt': auditoria.snapshot_prompt or '',
                            'snapshot_contexto': auditoria.snapshot_contexto or '',
                            'aplicaciones': auditoria.aplicaciones or {},
                            'fecha': auditoria.fecha.strftime('%d/%m/%Y %H:%M'),
                            'tokens': auditoria.tokens_usados,
                            'modelo': auditoria.modelo_usado or '',
                        })
                    except Exception as ex:
                        return JsonResponse({'result': False, 'message': str(ex)})
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
                if action == 'herramienta_form':
                    try:
                        from crm.forms import HerramientaAgenteForm
                        from crm.models import HerramientaAgente as _HA
                        agente_id = int(request.GET.get('agente_id') or 0)
                        agente = AgentesIA.objects.get(pk=agente_id, perfil=perfil)
                        pk = request.GET.get('id')
                        herramienta = _HA.objects.get(pk=int(pk), agente=agente) if pk else None
                        form = HerramientaAgenteForm(instance=herramienta)
                        data_ctx = dict(data)
                        data_ctx['form'] = form
                        data_ctx['herramienta'] = herramienta
                        data_ctx['agente'] = agente
                        # Pasar el valor Python crudo — json_script en el template se encarga de serializar
                        data_ctx['parametros_init'] = herramienta.parametros if herramienta else []
                        data_ctx['headers_init'] = herramienta.headers if herramienta else {}
                        template = get_template("crm/entrenamiento/herramienta/form.html")
                        return JsonResponse({"result": True, 'data': template.render(data_ctx)})
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})
                if action == 'herramienta_lista':
                    try:
                        agente_id = int(request.GET.get('agente_id') or 0)
                        agente = AgentesIA.objects.get(pk=agente_id, perfil=perfil)
                        data_ctx = dict(data)
                        data_ctx['agente'] = agente
                        data_ctx['herramientas'] = agente.herramientas.filter(status=True).order_by('nombre')
                        template = get_template("crm/entrenamiento/herramienta/lista.html")
                        return JsonResponse({"result": True, 'data': template.render(data_ctx)})
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})
                if action == 'herramienta_templates':
                    try:
                        from crm.herramienta_templates import HERRAMIENTA_TEMPLATES
                        return JsonResponse({'result': True, 'templates': HERRAMIENTA_TEMPLATES})
                    except Exception as ex:
                        return JsonResponse({'result': False, 'message': str(ex)})
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
                elif action == 'consumo_apikey':
                    try:
                        from django.db.models import Sum, Count
                        from django.db.models.functions import TruncDate
                        from django.utils.dateparse import parse_date
                        import datetime

                        pk = int(request.GET['id'])
                        apikey = ApiKeyIA.objects.get(pk=pk, perfil=perfil)

                        # Rango de fechas — default últimos 30 días (usar date.today() sin conversión timezone)
                        hoy = datetime.date.today()
                        fecha_fin   = parse_date(request.GET.get('fecha_fin', ''))   or hoy
                        fecha_inicio = parse_date(request.GET.get('fecha_inicio', '')) or (hoy - datetime.timedelta(days=29))

                        qs = ConsumoTokenIA.objects.filter(
                            apikey=apikey,
                            fecha__date__gte=fecha_inicio,
                            fecha__date__lte=fecha_fin,
                        )
                        totales = qs.aggregate(
                            total_llamadas=Count('id'),
                            total_entrada=Sum('tokens_entrada'),
                            total_salida=Sum('tokens_salida'),
                            total_tokens=Sum('tokens_total'),
                        )
                        # Agrupar por fecha usando __date (sin conversión timezone)
                        por_dia_qs = (
                            qs.values('fecha__date')
                              .annotate(
                                  llamadas=Count('id'),
                                  entrada=Sum('tokens_entrada'),
                                  salida=Sum('tokens_salida'),
                                  total=Sum('tokens_total'),
                              )
                              .order_by('fecha__date')
                        )
                        por_dia = [
                            {'dia': str(r['fecha__date']), 'llamadas': r['llamadas'],
                             'entrada': r['entrada'] or 0, 'salida': r['salida'] or 0,
                             'total': r['total'] or 0}
                            for r in por_dia_qs
                        ]
                        por_agente = list(
                            qs.filter(agente__isnull=False)
                              .values('agente__nombre')
                              .annotate(
                                  llamadas=Count('id'),
                                  total=Sum('tokens_total'),
                              )
                              .order_by('-total')[:10]
                        )
                        return JsonResponse({
                            'result': True,
                            'apikey_alias': str(apikey),
                            'fecha_inicio': str(fecha_inicio),
                            'fecha_fin': str(fecha_fin),
                            'totales': {
                                'llamadas': totales['total_llamadas'] or 0,
                                'entrada': totales['total_entrada'] or 0,
                                'salida': totales['total_salida'] or 0,
                                'total': totales['total_tokens'] or 0,
                            },
                            'por_dia': por_dia,
                            'por_agente': [
                                {'agente': r['agente__nombre'], 'llamadas': r['llamadas'], 'total': r['total'] or 0}
                                for r in por_agente
                            ],
                        })
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})

                elif action == 'alerta_consumo_get':
                    try:
                        pk = int(request.GET['id'])
                        apikey = ApiKeyIA.objects.get(pk=pk, perfil=perfil)
                        try:
                            alerta = apikey.alerta_consumo
                            data_alerta = {
                                'umbral_diario': alerta.umbral_diario,
                                'umbral_mensual': alerta.umbral_mensual,
                                'notificar_a': list(alerta.notificar_a.values_list('id', flat=True)),
                            }
                        except Exception:
                            # DoesNotExist o tabla aún no migrada → devolver defaults
                            data_alerta = {'umbral_diario': 0, 'umbral_mensual': 0, 'notificar_a': []}
                        return JsonResponse(data_alerta)
                    except Exception as ex:
                        return JsonResponse({'umbral_diario': 0, 'umbral_mensual': 0, 'notificar_a': [], 'error': str(ex)})

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
            # Usuarios para modal de alertas
            from autenticacion.models import Usuario as UsuarioModel
            data['usuarios_sistema'] = UsuarioModel.objects.filter(is_active=True).order_by('first_name', 'last_name')
    except Exception as ex:
        error_line = sys.exc_info()[-1].tb_lineno
        messages.error(request, f"Error inesperado: {ex} - Línea {error_line}")
        return redirect('/panel/')

    return render(request, 'crm/entrenamiento/form.html', data)
