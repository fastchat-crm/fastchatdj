import json
import os
import sys
import time
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction, models
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

                            # Procesar los detalles si existen. Tolerar valor
                            # vacío o JSON inválido — un agente sin detalles
                            # cargados es válido (se setean luego).
                            _det_raw = (request.POST.get('detalles_json') or '').strip()
                            if _det_raw:
                                try:
                                    detalles_data = json.loads(_det_raw)
                                except json.JSONDecodeError:
                                    detalles_data = []
                                if detalles_data:
                                    guardar_detalles_agente(agente, detalles_data, request.FILES)

                            log(f"Registro un agente IA {agente.__str__()}", request, "add", obj=agente.id)
                            if request.POST.get('redirect_to'):
                                res_json.append({
                                    'error': False,
                                    'msg_to': True,
                                    'to': request.POST['redirect_to'],
                                    'msg_title': 'Agente creado',
                                    'msg_body': f'{agente.nombre} fue registrado correctamente.',
                                })
                            else:
                                res_json.append({'error': False, "reload": True})
                        else:
                            raise FormError(form)
                    elif action == 'changeagente':
                        filtro = AgentesIA.objects.get(pk=int(request.POST['pk']))
                        form = AgentesIAForm(request.POST, request.FILES, instance=filtro, request=request)
                        if form.is_valid() and filtro:
                            agente = form.save()

                            # Eliminar detalles existentes y crear los nuevos.
                            # Tolerar valor vacío o JSON inválido del front.
                            _det_raw = (request.POST.get('detalles_json') or '').strip()
                            if _det_raw:
                                try:
                                    detalles_data = json.loads(_det_raw)
                                except json.JSONDecodeError:
                                    detalles_data = []
                                if detalles_data:
                                    guardar_detalles_agente(agente, detalles_data, request.FILES)

                            log(f"Edito un agente IA {agente.__str__()}", request, "change", obj=agente.id)
                            if request.POST.get('redirect_to'):
                                res_json.append({
                                    'error': False,
                                    'msg_to': True,
                                    'to': request.POST['redirect_to'],
                                    'msg_title': 'Agente actualizado',
                                    'msg_body': f'{agente.nombre} se guardó correctamente.',
                                })
                            else:
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

                            # Procesar los detalles si existen (tolerar vacío).
                            _det_raw = (request.POST.get('detalles_json') or '').strip()
                            if _det_raw:
                                try:
                                    detalles_data = json.loads(_det_raw)
                                except json.JSONDecodeError:
                                    detalles_data = []
                                if detalles_data:
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
                    elif action == 'preview_procesamiento':
                        # Devuelve el INVENTARIO de lo que va a procesar, sin ejecutarlo,
                        # para que el usuario vea en el modal de confirmacion que tiene cargado.
                        filtro = AgentesIA.objects.get(pk=int(request.POST['id']), perfil=perfil)
                        detalles_archivo = list(filtro.detalleagentesai_set.filter(
                            status=True, tipo=2, archivo__isnull=False
                        ))
                        detalles_texto = list(filtro.detalleagentesai_set.filter(
                            status=True, tipo=3
                        ).exclude(descripcion__isnull=True).exclude(descripcion=''))
                        archivos_info = []
                        total_bytes = 0
                        for det in detalles_archivo:
                            try:
                                nombre = os.path.basename(det.archivo.name)
                                tam = det.archivo.size if det.archivo else 0
                            except Exception:
                                nombre, tam = '(sin nombre)', 0
                            total_bytes += tam
                            archivos_info.append({
                                'nombre': nombre,
                                'size_kb': round(tam / 1024, 1),
                                'detalle_id': det.id,
                            })
                        textos_info = []
                        total_chars_texto = 0
                        for det in detalles_texto:
                            n = len(det.descripcion or '')
                            total_chars_texto += n
                            textos_info.append({
                                'detalle_id': det.id,
                                'chars': n,
                                'preview': (det.descripcion or '')[:120] + ('…' if n > 120 else ''),
                            })
                        res_json = {
                            'error': False,
                            'agente_nombre': filtro.nombre,
                            'archivos': archivos_info,
                            'textos': textos_info,
                            'total_archivos': len(archivos_info),
                            'total_textos': len(textos_info),
                            'total_bytes': total_bytes,
                            'total_kb': round(total_bytes / 1024, 1),
                            'total_chars_texto': total_chars_texto,
                            'contexto_actual_chars': len(filtro.contexto_estatico or ''),
                            'tiene_vectorstore': bool(filtro.vectorstore_path),
                            'se_va_a_construir_faiss': (total_bytes + total_chars_texto) > 40_000,
                        }

                    elif action == 'preview_prompt':
                        # Devuelve el prompt final renderizado con datos de ejemplo,
                        # para que el usuario vea EXACTAMENTE que recibe el LLM en runtime.
                        from langchain_core.prompts import PromptTemplate as _PT
                        from core.constantes import PROMPT_TEMPLATES as _PTS
                        filtro = AgentesIA.objects.get(pk=int(request.POST['id']), perfil=perfil)
                        _tpl_text = filtro.prompt_template or _PTS.get('es', '')
                        try:
                            tpl = _PT.from_template(_tpl_text + '\n')
                            _vars_requeridas = list(tpl.input_variables or [])
                        except Exception as _ex:
                            res_json = {'error': True, 'message': f'Template invalido: {_ex}'}
                        else:
                            # Construir contexto de ejemplo a partir de lo que realmente tiene
                            _ctx_muestra = (filtro.contexto_estatico or '')[:2000]
                            if not _ctx_muestra:
                                _ctx_muestra = '[Sin contexto estatico configurado — se usaria FAISS en runtime]'
                            _pregunta_demo = (request.POST.get('pregunta_demo') or '').strip() or '¿Cuales son sus horarios?'
                            _vars_todas = {
                                'question':           _pregunta_demo,
                                'context':            _ctx_muestra,
                                'descripcion_agente': filtro.descripcion or '',
                                'contexto_extra':     '[Historial previo de la conversacion]',
                                'nombre_bot':         getattr(filtro, 'nombre_bot', '') or 'Asistente',
                                'personalidad':       getattr(filtro, 'personalidad', '') or '(sin personalidad)',
                                'tono':               getattr(filtro, 'tono', '') or 'amigable',
                                'estilo_escritura':   getattr(filtro, 'estilo_escritura', '') or '(estilo natural, mensajes cortos)',
                                'contacto_nombre':    'Juan Perez',
                                'hora_local':         'martes 15:30',
                                'primera_vez_hoy':    'false',
                                'estado_animo':       'neutral',
                                'guia_animo':         'tono natural',
                                'historial_contacto': '[Sin historial previo]',
                            }
                            _kwargs = {k: v for k, v in _vars_todas.items() if k in _vars_requeridas}
                            _faltantes = [v for v in _vars_requeridas if v not in _vars_todas]
                            try:
                                _rendered = tpl.format(**_kwargs)
                            except Exception as _ex:
                                res_json = {'error': True, 'message': f'Error renderizando: {_ex}'}
                            else:
                                # Herramientas activas (no entran al prompt, pero son parte del
                                # contexto del LLM via bind_tools — las listamos para info).
                                _herramientas = list(filtro.herramientas.filter(status=True, activo=True).values('nombre', 'descripcion')) if hasattr(filtro, 'herramientas') else []
                                regla = getattr(filtro, 'regla_fin', None)
                                res_json = {
                                    'error': False,
                                    'prompt_rendered': _rendered,
                                    'vars_usadas': list(_kwargs.keys()),
                                    'vars_no_usadas_en_template': [v for v in _vars_todas.keys() if v not in _vars_requeridas],
                                    'vars_faltantes_template_requiere_pero_no_existe': _faltantes,
                                    'herramientas_activas': _herramientas,
                                    'cierre_activo': bool(regla and regla.activo),
                                    'chars_prompt':  len(_rendered),
                                    'pregunta_demo': _pregunta_demo,
                                }

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
                    elif action == 'limpiar_error_apikey':
                        filtro = ApiKeyIA.objects.get(pk=int(request.POST['id']), perfil=perfil)
                        filtro.msgerror = None
                        filtro.save(update_fields=['msgerror'])
                        log(f"Error limpiado de API Key {filtro}", request, "change", obj=filtro.id)
                        return JsonResponse({'error': False})
                    elif action == 'auditoria_generar':
                        from agents_ai.ai_actions import auditor_crm
                        agente = AgentesIA.objects.get(pk=int(request.POST['agente_id']), perfil=perfil)
                        dias = int(request.POST.get('dias', 30) or 30)
                        auditoria = auditor_crm.generar(agente, usuario=request.user, dias=dias)
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
                        from agents_ai.ai_actions import auditor_crm
                        auditoria = AuditoriaAgenteIA.objects.select_related('agente__perfil').get(
                            pk=int(request.POST['auditoria_id']), agente__perfil=perfil,
                        )
                        campo = request.POST.get('campo')
                        if campo not in ('prompt_template', 'contexto_estatico'):
                            raise ValueError('Campo no soportado')
                        auditor_crm.aplicar(auditoria, campo, usuario=request.user)
                        log(f"Aplicada sugerencia IA ({campo}) del agente {auditoria.agente}", request, "change", obj=auditoria.agente.id)
                        # Recargar agente para devolver el valor recién aplicado
                        auditoria.agente.refresh_from_db(fields=[campo])
                        res_json = {
                            'error': False, 'campo': campo, 'estado': auditoria.estado,
                            'nuevo_valor': getattr(auditoria.agente, campo) or '',
                        }
                    elif action == 'auditoria_revertir':
                        from agents_ai.ai_actions import auditor_crm
                        auditoria = AuditoriaAgenteIA.objects.select_related('agente__perfil').get(
                            pk=int(request.POST['auditoria_id']), agente__perfil=perfil,
                        )
                        auditor_crm.revertir(auditoria, usuario=request.user)
                        log(f"Revertida auditoria IA del agente {auditoria.agente}", request, "change", obj=auditoria.agente.id)
                        auditoria.agente.refresh_from_db(fields=['prompt_template', 'contexto_estatico'])
                        res_json = {
                            'error': False, 'estado': auditoria.estado,
                            'prompt_template': auditoria.agente.prompt_template or '',
                            'contexto_estatico': auditoria.agente.contexto_estatico or '',
                        }
                    elif action == 'auditoria_aplicar_faq':
                        from agents_ai.ai_actions import auditor_crm
                        auditoria = AuditoriaAgenteIA.objects.select_related('agente__perfil').get(
                            pk=int(request.POST['auditoria_id']), agente__perfil=perfil,
                        )
                        creadas = auditor_crm.aplicar_faq(auditoria, usuario=request.user)
                        log(f"Importadas {creadas} FAQ(s) pendientes del auditor — agente {auditoria.agente}",
                            request, "add", obj=auditoria.agente.id)
                        res_json = {'error': False, 'creadas': creadas}
                    elif action == 'regenerar_ws_token':
                        filtro = ApiKeyIA.objects.get(pk=int(request.POST['id']), perfil=perfil)
                        filtro.regenerar_webservice_token()
                        log(f"WebService token regenerado para API Key {filtro.pk}", request, "change", obj=filtro.pk)
                        return JsonResponse({'error': False, 'token': filtro.webservice_token, 'message': 'Token regenerado.'})

                    elif action == 'generar_agente_ia':
                        # Wrapper HTTP: la logica IA vive en
                        # `agents_ai/ai_actions/agentes_crm.py`.
                        from agents_ai.ai_actions import IAActionError
                        from agents_ai.ai_actions import agentes_crm
                        try:
                            apikey_obj = ApiKeyIA.objects.get(pk=int(request.POST['id']), perfil=perfil)
                        except (ApiKeyIA.DoesNotExist, ValueError, KeyError):
                            return JsonResponse({'error': True, 'message': 'API Key no encontrada.'})
                        try:
                            resultado = agentes_crm.generar(
                                descripcion=request.POST.get('descripcion'),
                                tono=request.POST.get('tono') or 'amigable',
                                idioma=request.POST.get('idioma') or 'es',
                                apikey_obj=apikey_obj,
                                perfil=perfil,
                                request=request,
                            )
                        except IAActionError as ex:
                            return JsonResponse({'error': True, 'message': str(ex)})
                        except Exception as ex:
                            return JsonResponse({'error': True, 'message': f'Fallo generando agente: {str(ex)[:400]}'})

                        log(
                            f"Agente IA creado por asistente — {resultado['nombre']} asignado a API Key {apikey_obj}",
                            request, "add", obj=resultado['agente_id'],
                        )
                        return JsonResponse({
                            'error': False,
                            'agente_id': resultado['agente_id'],
                            'nombre': resultado['nombre'],
                            'descripcion': resultado['descripcion'],
                            'prompt_template': resultado['prompt_template'],
                            'contexto_estatico': resultado['contexto_estatico'],
                            'anotar_listas': resultado['anotar_listas'],
                            'message': f'✅ Agente "{resultado["nombre"]}" creado y asignado a {apikey_obj}.',
                            'reload': True,
                        })

                    elif action == 'testapikey':
                        from crm.view_chat_agente import _billing_info_por_proveedor
                        filtro = ApiKeyIA.objects.get(pk=int(request.POST['id']), perfil=perfil)
                        _default_model_by_provider = {
                            2: 'gemini-2.5-flash',
                            3: 'gpt-4o-mini',
                            4: 'claude-haiku-4-5-20251001',
                        }
                        # Usa el modelo real configurado en la ApiKey — así el test refleja
                        # la quota/plan del modelo que realmente se usa en producción.
                        modelo_test = (filtro.modelo or '').strip() or _default_model_by_provider.get(filtro.proveedor, 'gpt-4o-mini')
                        billing_info = _billing_info_por_proveedor(filtro.proveedor)
                        prompt_prueba = 'Responde solo con la palabra: ok'
                        try:
                            if filtro.proveedor == 2:  # Gemini
                                from langchain_google_genai import ChatGoogleGenerativeAI
                                llm = ChatGoogleGenerativeAI(
                                    model=modelo_test, google_api_key=filtro.descripcion,
                                    max_output_tokens=20, temperature=0,
                                )
                            elif filtro.proveedor == 4:  # Claude / Anthropic
                                from langchain_anthropic import ChatAnthropic
                                llm = ChatAnthropic(
                                    model=modelo_test, anthropic_api_key=filtro.descripcion,
                                    max_tokens=20, temperature=0,
                                )
                            else:  # OpenAI
                                from langchain_community.chat_models import ChatOpenAI
                                llm = ChatOpenAI(
                                    model_name=modelo_test, openai_api_key=filtro.descripcion,
                                    max_tokens=20, temperature=0,
                                )
                            _t0 = time.time()
                            _resp = llm.invoke(prompt_prueba)
                            _lat_ms = int((time.time() - _t0) * 1000)
                            _respuesta_txt = (getattr(_resp, 'content', '') or '').strip() or '(respuesta vacía)'
                            # Tokens consumidos en la prueba
                            _meta = getattr(_resp, 'response_metadata', {}) or {}
                            _usage = (
                                getattr(_resp, 'usage_metadata', None)
                                or _meta.get('usage_metadata')
                                or _meta.get('token_usage')
                                or {}
                            )
                            _te = _usage.get('input_tokens') or _usage.get('prompt_token_count') or _usage.get('prompt_tokens') or 0
                            _ts = _usage.get('output_tokens') or _usage.get('candidates_token_count') or _usage.get('completion_tokens') or 0
                            # Éxito real — reactivar si estaba desactivada
                            if not filtro.estado:
                                filtro.estado = True
                                filtro.msgerror = None
                                filtro.save()
                            res_json = {
                                "error": False,
                                "message": f"✅ API Key válida y funcional con el modelo '{modelo_test}'.",
                                "activo": True,
                                "billing": billing_info,
                                "prueba": {
                                    "prompt": prompt_prueba,
                                    "respuesta": _respuesta_txt[:500],
                                    "modelo": modelo_test,
                                    "tokens_entrada": int(_te or 0),
                                    "tokens_salida": int(_ts or 0),
                                    "tokens_total": int((_te or 0) + (_ts or 0)),
                                    "latencia_ms": _lat_ms,
                                },
                            }
                        except Exception as ex:
                            err_str = str(ex)
                            err_lower = err_str.lower()
                            # Clasificación del error
                            is_quota = ('429' in err_str
                                        or 'quota' in err_lower
                                        or 'rate limit' in err_lower
                                        or 'resource has been exhausted' in err_lower
                                        or 'too many requests' in err_lower
                                        or 'credit balance is too low' in err_lower
                                        or 'insufficient_quota' in err_lower)
                            is_auth = ('401' in err_str
                                       or '403' in err_str
                                       or ('api key' in err_lower and ('invalid' in err_lower or 'not valid' in err_lower))
                                       or 'unauthenticated' in err_lower
                                       or 'permission denied' in err_lower
                                       or 'invalid x-api-key' in err_lower)
                            is_model = ('404' in err_str
                                        or ('not found' in err_lower and 'model' in err_lower)
                                        or 'does not exist' in err_lower)

                            if is_quota:
                                # Sin cupo → desactivar para que el pipeline no siga intentando consumir.
                                filtro.estado = False
                                filtro.msgerror = f'Quota/rate limit excedido ({modelo_test}): {err_str[:400]}'
                                filtro.save()
                                res_json = {
                                    "error": False,
                                    "message": (
                                        f"⚠️ Sin cupo en el modelo '{modelo_test}' ({billing_info['proveedor']}). "
                                        f"La API Key se desactivó para evitar seguir consumiendo. "
                                        f"Actualiza tu plan de facturación en {billing_info['proveedor']} o espera a que "
                                        f"el límite se renueve y luego reactívala. "
                                        f"Detalle: {err_str[:300]}"
                                    ),
                                    "activo": False,
                                    "quota_exceeded": True,
                                    "billing": billing_info,
                                }
                            elif is_auth:
                                filtro.estado = False
                                filtro.msgerror = f'Clave inválida/sin permisos: {err_str[:400]}'
                                filtro.save()
                                res_json = {
                                    "error": False,
                                    "message": f"❌ Clave inválida o sin permisos ({billing_info['proveedor']}): {err_str[:300]}",
                                    "activo": False,
                                    "billing": billing_info,
                                }
                            elif is_model:
                                filtro.msgerror = f"Modelo '{modelo_test}' no disponible para esta key: {err_str[:300]}"
                                filtro.save(update_fields=['msgerror'])
                                res_json = {
                                    "error": False,
                                    "message": (
                                        f"⚠️ El modelo '{modelo_test}' no existe o no está disponible para esta key de {billing_info['proveedor']}. "
                                        f"Revisa el campo 'Modelo LLM' de la API Key."
                                    ),
                                    "activo": True,
                                    "modelo_invalido": True,
                                    "billing": billing_info,
                                }
                            else:
                                filtro.estado = False
                                filtro.msgerror = err_str[:500]
                                filtro.save()
                                res_json = {
                                    "error": False,
                                    "message": f"❌ Error ({billing_info['proveedor']}): {err_str[:300]}",
                                    "activo": False,
                                    "billing": billing_info,
                                }

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

                    elif action == 'optimizar_defaults_agentes':
                        # Baja los parametros token-hungry de los agentes que todavia
                        # usan los defaults viejos, sin tocar agentes tuneados a mano.
                        # Filtros por valor viejo exacto → si el usuario subio o bajo
                        # manualmente el valor, lo respetamos.
                        _reglas = [
                            ('cfg_history_turns',    10,   5),
                            ('cfg_user_snippet',     300,  150),
                            ('cfg_ai_snippet',       800,  400),
                            ('cfg_max_static_chars', 2000, 1200),
                            ('faqs_en_prompt',       10,   5),
                        ]
                        qs_base = AgentesIA.objects.filter(perfil=perfil, status=True)
                        resumen = []
                        total_agentes_tocados = set()
                        for campo, viejo, nuevo in _reglas:
                            ids_a_cambiar = list(qs_base.filter(**{campo: viejo}).values_list('id', flat=True))
                            actualizados = qs_base.filter(id__in=ids_a_cambiar).update(**{campo: nuevo})
                            total_agentes_tocados.update(ids_a_cambiar)
                            resumen.append({
                                'campo':        campo,
                                'valor_viejo':  viejo,
                                'valor_nuevo':  nuevo,
                                'actualizados': actualizados,
                            })
                        log(f"Optimizar agentes: {len(total_agentes_tocados)} agentes ajustados a defaults nuevos",
                            request, "change", obj=0)
                        return JsonResponse({
                            'error':           False,
                            'message':         f'{len(total_agentes_tocados)} agente(s) optimizados.',
                            'agentes_tocados': len(total_agentes_tocados),
                            'total_agentes':   qs_base.count(),
                            'detalle':         resumen,
                        })

                    elif action == 'ejecutar_prompt_agente':
                        # Invoca el LLM de verdad con la pregunta del usuario usando
                        # el mismo pipeline que runtime (consultar / consultar_con_listas).
                        # Devuelve: prompt_real, respuesta, tokens, latencia, sin_datos.
                        from django.utils import timezone as _tz
                        from types import SimpleNamespace
                        from agents_ai.agente_consultor import AgenteConsultor
                        from crm.models import ConsumoTokenIA as _CT
                        from core.constantes import PROMPT_TEMPLATES as _PTS_EJ

                        try:
                            agente_id = int(request.POST.get('id') or 0)
                            agente = AgentesIA.objects.get(pk=agente_id, perfil=perfil)
                        except AgentesIA.DoesNotExist:
                            return JsonResponse({'error': True, 'message': 'Agente no encontrado.'})

                        pregunta = (request.POST.get('pregunta') or '').strip()
                        if not pregunta:
                            return JsonResponse({'error': True, 'message': 'Escribe una pregunta.'})

                        apikey_obj = agente.apikey.filter(estado=True).first()
                        if not apikey_obj:
                            return JsonResponse({'error': True, 'message': 'El agente no tiene API Key activa.'})

                        vs_path = os.path.join(settings.MEDIA_ROOT, agente.vectorstore_path) if agente.vectorstore_path else None
                        vs_enlaces_path = (
                            os.path.join(settings.MEDIA_ROOT, agente.vectorstore_enlaces_path)
                            if agente.vectorstore_enlaces_path else None
                        )
                        fake_conv = SimpleNamespace(id=f"sim-ejec-{agente.id}-{request.user.id}", contacto=None)

                        try:
                            consultor = AgenteConsultor(
                                vectorstore_path=vs_path, vectorstore_enlaces_path=vs_enlaces_path,
                                provider=apikey_obj.proveedor, apikey=apikey_obj.descripcion,
                                model_name=(apikey_obj.modelo or None),
                                conversacion=fake_conv,
                                prompt_template_text=(agente.prompt_template or '').strip() or _PTS_EJ.get('es', ''),
                                contexto_estatico=agente.contexto_estatico or None,
                                perfil=agente.perfil, agente=agente,
                            )
                            # Prompt que realmente va al LLM (mismo cálculo que simular_prompt)
                            contexto_real, _sd = consultor._construir_contexto(pregunta, "")
                            prompt_real = consultor._formatear_prompt(pregunta, contexto_real, agente.descripcion or '', "")

                            t0 = _tz.now()
                            if agente.requiere_tools():
                                resultado = consultor.consultar_con_listas(pregunta, agente.descripcion or '')
                            else:
                                resultado = consultor.consultar(pregunta, agente.descripcion or '')
                            latencia_ms = int((_tz.now() - t0).total_seconds() * 1000)
                        except Exception as ex:
                            return JsonResponse({'error': True, 'message': f'Fallo invocando el agente: {ex}'})

                        # Registrar consumo (igual que chat real)
                        if resultado.tokens_total > 0:
                            try:
                                _CT.objects.create(
                                    apikey=apikey_obj, agente=agente,
                                    tokens_entrada=resultado.tokens_entrada,
                                    tokens_salida=resultado.tokens_salida,
                                    tokens_total=resultado.tokens_total,
                                    modelo=consultor.model_name,
                                    origen='simular_prompt',
                                    prompt_preview=(pregunta or '')[:300],
                                )
                            except Exception:
                                pass

                        return JsonResponse({
                            'error':           False,
                            'prompt_real':     prompt_real,
                            'chars_prompt':    len(prompt_real),
                            'contexto':        contexto_real,
                            'chars_contexto':  len(contexto_real),
                            'respuesta':       resultado.respuesta,
                            'sin_datos':       resultado.sin_datos,
                            'fin_detectado':   resultado.fin_detectado,
                            'tokens_entrada':  resultado.tokens_entrada,
                            'tokens_salida':   resultado.tokens_salida,
                            'tokens_total':    resultado.tokens_total,
                            'latencia_ms':     latencia_ms,
                            'faqs_usadas':     list(consultor._faq_ids_usadas or []),
                            'modelo':          consultor.model_name,
                            'provider':        apikey_obj.proveedor,
                            'tiene_faiss':     bool(vs_path),
                        })

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
                        fake_conv = SimpleNamespace(id=session_id, contacto=None, contacto_id=None)

                        before = _tz.now()
                        try:
                            consultor = AgenteConsultor(
                                vectorstore_path=vs_path, vectorstore_enlaces_path=vs_enlaces_path,
                                provider=apikey_obj.proveedor, apikey=apikey_obj.descripcion,
                                model_name=(apikey_obj.modelo or None),
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

                    # ── Preguntas Frecuentes (FaqAgente) ──────────────────────
                    elif action == 'faq_save':
                        from crm.forms import FaqAgenteForm
                        from crm.models import FaqAgente as _FA
                        from django.utils import timezone as _tz
                        agente = AgentesIA.objects.get(pk=int(request.POST['agente_id']), perfil=perfil)
                        pk = request.POST.get('pk')
                        instancia = _FA.objects.get(pk=int(pk), agente=agente) if pk else None
                        form = FaqAgenteForm(request.POST, instance=instancia, request=request)
                        if not form.is_valid():
                            raise FormError(form)
                        obj = form.save(commit=False)
                        obj.agente = agente
                        if not pk:
                            obj.origen = 'manual'
                        # Registrar aprobación
                        if obj.estado == 'aprobada' and (instancia is None or instancia.estado != 'aprobada'):
                            obj.fecha_aprobacion = _tz.now()
                            obj.usuario_aprobacion = request.user
                        obj.save()
                        log(f"{'Edito' if pk else 'Creo'} FAQ del agente {agente.nombre}",
                            request, "change" if pk else "add", obj=obj.id)
                        return JsonResponse({'error': False, 'id': obj.id})

                    elif action == 'faq_delete':
                        from crm.models import FaqAgente as _FA
                        filtro = _FA.objects.get(pk=int(request.POST['id']), agente__perfil=perfil)
                        filtro.status = False
                        filtro.save(request)
                        return JsonResponse({'error': False})

                    elif action == 'faq_aprobar':
                        from crm.models import FaqAgente as _FA
                        from django.utils import timezone as _tz
                        filtro = _FA.objects.get(pk=int(request.POST['id']), agente__perfil=perfil)
                        filtro.estado = 'aprobada'
                        filtro.fecha_aprobacion = _tz.now()
                        filtro.usuario_aprobacion = request.user
                        filtro.save(update_fields=['estado', 'fecha_aprobacion', 'usuario_aprobacion'])
                        return JsonResponse({'error': False})

                    elif action == 'faq_desactivar':
                        from crm.models import FaqAgente as _FA
                        filtro = _FA.objects.get(pk=int(request.POST['id']), agente__perfil=perfil)
                        filtro.estado = 'desactivada'
                        filtro.save(update_fields=['estado'])
                        return JsonResponse({'error': False})

                    elif action == 'faq_bulk_aprobar':
                        from crm.models import FaqAgente as _FA
                        from django.utils import timezone as _tz
                        agente = AgentesIA.objects.get(pk=int(request.POST['agente_id']), perfil=perfil)
                        ids_raw = request.POST.get('ids', '')
                        ids = [int(i) for i in ids_raw.split(',') if i.strip().isdigit()]
                        qs = _FA.objects.filter(id__in=ids, agente=agente, estado='pendiente')
                        count = qs.update(
                            estado='aprobada',
                            fecha_aprobacion=_tz.now(),
                            usuario_aprobacion=request.user,
                        )
                        log(f"Aprobadas {count} FAQ(s) en bulk — agente {agente.nombre}",
                            request, "change", obj=agente.id)
                        return JsonResponse({'error': False, 'count': count})

                    elif action == 'reconstruir_enlaces':
                        # Invalida el cache de fetch_contexto_apis y ejecuta una
                        # consulta real a cada URL para mostrar diagnóstico al usuario.
                        from django.core.cache import cache
                        agente = AgentesIA.objects.get(pk=int(request.POST['id']), perfil=perfil)
                        detalles_enlace = agente.detalleagentesai_set.filter(status=True, tipo=1, enlace__isnull=False)
                        if not detalles_enlace.exists():
                            return JsonResponse({'error': True, 'message': 'Este agente no tiene enlaces API configurados.'})

                        # Invalidar cache de cada fuente
                        for d in detalles_enlace:
                            cache.delete(f'agente_api_{agente.id}_detalle_{d.id}')

                        # Diagnóstico por URL
                        enlaces_info = []
                        for d in detalles_enlace:
                            info = {'id': d.id, 'url': d.enlace, 'tipo_dato': d.get_tipo_dato_enlace_display(),
                                    'observacion': d.descripcion or ''}
                            try:
                                import requests as _r
                                headers = {'Accept': 'application/json, text/plain, */*'}
                                if d.requiere_token and d.token_autorizacion:
                                    headers['Authorization'] = f'Bearer {d.token_autorizacion}'
                                resp = _r.get(d.enlace, headers=headers, timeout=30)
                                info['status_http'] = resp.status_code
                                info['bytes'] = len(resp.content)
                                if resp.status_code == 200 and d.tipo_dato_enlace == 3:
                                    try:
                                        j = resp.json()
                                        if isinstance(j, dict):
                                            if 'listCatalogo' in j:
                                                info['items_detectados'] = len(j['listCatalogo'])
                                                info['estructura'] = 'listCatalogo'
                                            elif 'data' in j and isinstance(j['data'], list):
                                                info['items_detectados'] = len(j['data'])
                                                info['estructura'] = 'data[]'
                                            else:
                                                info['estructura'] = 'json_generico'
                                        elif isinstance(j, list):
                                            info['items_detectados'] = len(j)
                                            info['estructura'] = 'lista_raiz'
                                    except Exception as je:
                                        info['error_parse'] = str(je)[:200]
                            except Exception as e:
                                info['error'] = str(e)[:300]
                            enlaces_info.append(info)

                        # Generar el bloque de contexto (para mostrar preview)
                        try:
                            contexto_apis = agente.fetch_contexto_apis(forzar_refresco=True)
                        except Exception as e:
                            return JsonResponse({
                                'error': True,
                                'message': f'❌ Error obteniendo datos: {str(e)[:400]}',
                                'enlaces': enlaces_info,
                            })

                        log(f"Refrescó conocimiento API del agente {agente.nombre}", request, "change", obj=agente.id)
                        return JsonResponse({
                            'error': False,
                            'chars_contexto_apis': len(contexto_apis or ''),
                            'preview': (contexto_apis or '')[:3000],
                            'enlaces': enlaces_info,
                        })

                    elif action == 'faq_aprender_ahora':
                        # Ejecuta aprender_conversaciones.py manualmente para este agente
                        from cron_jobs.aprender_conversaciones import procesar_conversaciones
                        agente = AgentesIA.objects.get(pk=int(request.POST['agente_id']), perfil=perfil)
                        try:
                            resultado = procesar_conversaciones(agente=agente, limite=500)
                            log(f"Ejecutó aprendizaje manual — agente {agente.nombre}: {resultado}",
                                request, "add", obj=agente.id)
                            return JsonResponse({'error': False, **resultado})
                        except Exception as ex:
                            return JsonResponse({'error': True, 'message': str(ex)})

                    elif action == 'faq_prioridad':
                        from crm.models import FaqAgente as _FA
                        filtro = _FA.objects.get(pk=int(request.POST['id']), agente__perfil=perfil)
                        filtro.prioridad = max(0, min(100, int(request.POST.get('prioridad') or 0)))
                        filtro.save(update_fields=['prioridad'])
                        return JsonResponse({'error': False, 'prioridad': filtro.prioridad})

                    elif action == 'herramienta_ia_asistida':
                        # Wrapper HTTP: la logica IA vive en
                        # `agents_ai/ai_actions/herramientas_crm.py`.
                        from agents_ai.ai_actions import IAActionError
                        from agents_ai.ai_actions import herramientas_crm
                        try:
                            agente_id = int(request.POST.get('agente_id') or 0)
                            agente = AgentesIA.objects.get(pk=agente_id, perfil=perfil)
                            resultado = herramientas_crm.generar(
                                frase=request.POST.get('frase'),
                                agente=agente,
                                request=request,
                            )
                        except IAActionError as ex:
                            return JsonResponse({'error': True, 'message': str(ex)})
                        except Exception as ex:
                            return JsonResponse({'error': True, 'message': f'No pude generar la configuración: {ex}'})
                        return JsonResponse({'error': False, 'config': resultado['config']})

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
                if action == 'procedimiento':
                    # Pagina dedicada para crear/editar agente IA (8 tabs, un solo POST).
                    # Reemplaza el viejo modal `?action=changeagente` y `?action=addagente`.
                    try:
                        from core.constantes import PERSONALIDAD_PRESETS
                        pk = request.GET.get('id')
                        filtro = None
                        if pk:
                            filtro = AgentesIA.objects.get(pk=int(pk), perfil=perfil)
                        data['filtro'] = filtro
                        data['form'] = form = AgentesIAForm(instance=filtro)
                        form.fields['apikey'].queryset = ApiKeyIA.objects.filter(perfil=perfil, status=True)
                        data['personalidad_presets'] = PERSONALIDAD_PRESETS
                        data['action'] = 'changeagente' if filtro else 'addagente'
                        if filtro:
                            data['detalles_existentes'] = filtro.obtener_detalles_agente()
                            data['regla_fin'] = getattr(filtro, 'regla_fin', None)
                            data['acciones_fin'] = data['regla_fin'].acciones.filter(status=True) if data['regla_fin'] else []
                            data['herramientas'] = filtro.herramientas.filter(status=True).order_by('nombre')
                            # Catálogo de departamentos para el botón
                            # "Regenerar desde depto" en el tab Herramientas.
                            from crm.models import DepartamentoChatBot
                            data['deptos_disponibles_regen'] = DepartamentoChatBot.objects.filter(
                                status=True,
                            ).order_by('nombre')
                            _faqs_qs = filtro.faqs.filter(status=True)
                            data['faqs_contadores'] = {
                                'pendiente':   _faqs_qs.filter(estado='pendiente').count(),
                                'aprobada':    _faqs_qs.filter(estado='aprobada').count(),
                                'desactivada': _faqs_qs.filter(estado='desactivada').count(),
                            }
                        data['titulo_pagina'] = f'Editar agente IA — {filtro}' if filtro else 'Nuevo agente IA'
                        data['ruta_post'] = request.path
                        return render(request, 'crm/entrenamiento/agente/form_pagina.html', data)
                    except AgentesIA.DoesNotExist:
                        messages.error(request, "Agente no encontrado")
                        return redirect(request.path)
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

                        # ── FAQs aprobadas (top-N se inyectan al prompt) ──
                        top_n = int(filtro.faqs_en_prompt or 0)
                        faqs_aprob_qs = filtro.faqs.filter(status=True, estado='aprobada').order_by('-prioridad', '-fecha_registro')
                        faqs_aprob_total = faqs_aprob_qs.count()
                        faqs_top = list(faqs_aprob_qs[:top_n].values(
                            'id', 'pregunta', 'respuesta', 'prioridad', 'hits', 'origen'
                        ))
                        faqs_pend = filtro.faqs.filter(status=True, estado='pendiente').count()

                        # Construir el bloque FAQ tal como se inyecta en el prompt
                        bloque_faq = ''
                        if faqs_top:
                            lineas = ['## Preguntas frecuentes ##']
                            for f in faqs_top:
                                p = (f['pregunta'] or '').strip().replace('\n', ' ')[:300]
                                r = (f['respuesta'] or '').strip().replace('\n', ' ')[:500]
                                if p and r:
                                    lineas.append(f"Q: {p}\nA: {r}")
                            lineas.append('## fin FAQ ##')
                            bloque_faq = '\n'.join(lineas)

                        # ── Herramientas (tool-calling) ───────────────────
                        herramientas_data = list(
                            filtro.herramientas.filter(status=True).order_by('-activo', 'nombre')
                            .values('id', 'nombre', 'nombre_amigable', 'descripcion',
                                    'metodo', 'url', 'ubicacion_params', 'parametros',
                                    'activo', 'timeout')
                        )
                        herramientas_activas = sum(1 for h in herramientas_data if h['activo'])

                        # ── Prompt preview: muestra el prompt exacto que recibe el LLM
                        # (con FAQ anteponido al contexto, igual que en _construir_contexto)
                        contexto_con_faq = contexto
                        if bloque_faq:
                            contexto_con_faq = f"{bloque_faq}\n\n{contexto}" if contexto else bloque_faq
                        prompt_preview = ''
                        try:
                            _ctx_for_preview = contexto_con_faq[:5000] + ('\n…[truncado]…' if len(contexto_con_faq) > 5000 else '')
                            # Sustituimos TODAS las variables que inyecta `_formatear_prompt` del consultor,
                            # asi el preview refleja exactamente lo que el LLM recibira en runtime —
                            # incluyendo persona (nombre_bot, personalidad, tono, estilo) que antes quedaban
                            # como placeholder crudo en el preview.
                            _substituciones = {
                                '{context}':            _ctx_for_preview,
                                '{descripcion_agente}': filtro.descripcion or '',
                                '{contexto_extra}':     '[Historial de la conversación irá aquí]',
                                '{question}':           '[Pregunta del usuario irá aquí]',
                                '{nombre_bot}':         getattr(filtro, 'nombre_bot', '') or 'Asistente',
                                '{personalidad}':       getattr(filtro, 'personalidad', '') or '(sin personalidad definida)',
                                '{tono}':               getattr(filtro, 'tono', '') or 'amigable',
                                '{estilo_escritura}':   getattr(filtro, 'estilo_escritura', '') or '(estilo natural, mensajes cortos)',
                                '{contacto_nombre}':    'Juan Perez',
                                '{hora_local}':         'martes 15:30',
                                '{primera_vez_hoy}':    'false',
                                '{estado_animo}':       'neutral',
                                '{guia_animo}':         'tono natural',
                                '{historial_contacto}': '[Sin historial persistente]',
                            }
                            prompt_preview = prompt_tpl
                            for placeholder, valor in _substituciones.items():
                                prompt_preview = prompt_preview.replace(placeholder, valor)
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
                            # ── Nuevo: FAQs activas en el agente ───────────
                            "faqs_top_n": top_n,
                            "faqs_top": faqs_top,
                            "faqs_aprobadas_total": faqs_aprob_total,
                            "faqs_pendientes": faqs_pend,
                            "faqs_bloque_preview": bloque_faq,
                            # ── Nuevo: Herramientas tool-calling ───────────
                            "herramientas": herramientas_data,
                            "herramientas_activas": herramientas_activas,
                            "herramientas_total": len(herramientas_data),
                            # ── Enlaces API externas ─────────────────────
                            "num_enlaces_api": filtro.detalleagentesai_set.filter(status=True, tipo=1, enlace__isnull=False).count(),
                            # ── Config del agente (para el flujo de lectura) ──
                            "cfg_history_turns": filtro.cfg_history_turns,
                            "cfg_max_context_chars": filtro.cfg_max_context_chars,
                            "cfg_faiss_k": filtro.cfg_faiss_k,
                        })
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})
                if action == 'preview_optimizar_agentes':
                    # Preview: muestra agente por agente qué cambiaría al ejecutar
                    # la optimizacion de defaults. No modifica nada en DB.
                    _reglas = [
                        ('cfg_history_turns',    10,   5),
                        ('cfg_user_snippet',     300,  150),
                        ('cfg_ai_snippet',       800,  400),
                        ('cfg_max_static_chars', 2000, 1200),
                        ('faqs_en_prompt',       10,   5),
                    ]
                    qs_base = AgentesIA.objects.filter(perfil=perfil, status=True).order_by('nombre')
                    filas = []
                    total_cambios = 0
                    for ag in qs_base:
                        cambios_ag = []
                        for campo, viejo, nuevo in _reglas:
                            actual = getattr(ag, campo, None)
                            cambiara = (actual == viejo)
                            if cambiara:
                                total_cambios += 1
                            cambios_ag.append({
                                'campo':    campo,
                                'antes':    actual,
                                'despues':  nuevo if cambiara else actual,
                                'cambia':   cambiara,
                            })
                        filas.append({
                            'id':       ag.id,
                            'nombre':   ag.nombre or '(sin nombre)',
                            'cambios':  cambios_ag,
                            'n_cambios': sum(1 for c in cambios_ag if c['cambia']),
                        })
                    agentes_con_cambios = sum(1 for f in filas if f['n_cambios'] > 0)
                    return JsonResponse({
                        'result':               True,
                        'filas':                filas,
                        'total_agentes':        len(filas),
                        'agentes_con_cambios':  agentes_con_cambios,
                        'total_cambios':        total_cambios,
                        'reglas':               [
                            {'campo': c, 'viejo': v, 'nuevo': n} for c, v, n in _reglas
                        ],
                    })
                if action == 'simular_prompt':
                    # Construye el prompt REAL que se enviaría al LLM para la
                    # pregunta dada, usando el mismo pipeline que runtime
                    # (_construir_contexto + _formatear_prompt de AgenteConsultor).
                    # NO invoca al LLM — solo arma el payload y lo devuelve.
                    try:
                        from types import SimpleNamespace
                        from agents_ai.agente_consultor import AgenteConsultor
                        from core.constantes import PROMPT_TEMPLATES as _PTS_SIM

                        pk = int(request.GET['id'])
                        pregunta = (request.GET.get('pregunta') or '').strip()
                        if not pregunta:
                            return JsonResponse({'result': False, 'message': 'Ingresa una pregunta de ejemplo.'})

                        agente = AgentesIA.objects.get(pk=pk, perfil=perfil)
                        apikey_obj = agente.apikey.filter(estado=True).first()
                        if not apikey_obj:
                            return JsonResponse({'result': False, 'message': 'El agente no tiene API Key activa — necesaria para cargar el vectorstore.'})

                        vs_path = os.path.join(settings.MEDIA_ROOT, agente.vectorstore_path) if agente.vectorstore_path else None
                        vs_enlaces_path = (
                            os.path.join(settings.MEDIA_ROOT, agente.vectorstore_enlaces_path)
                            if agente.vectorstore_enlaces_path else None
                        )
                        prompt_tpl = (agente.prompt_template or '').strip() or _PTS_SIM.get('es', '')

                        fake_conv = SimpleNamespace(id=f"sim-prompt-{agente.id}-{request.user.id}", contacto=None)
                        consultor = AgenteConsultor(
                            vectorstore_path=vs_path, vectorstore_enlaces_path=vs_enlaces_path,
                            provider=apikey_obj.proveedor, apikey=apikey_obj.descripcion,
                            model_name=(apikey_obj.modelo or None),
                            conversacion=fake_conv,
                            prompt_template_text=prompt_tpl,
                            contexto_estatico=agente.contexto_estatico or None,
                            perfil=agente.perfil, agente=agente,
                        )

                        contexto, sin_datos = consultor._construir_contexto(pregunta, "")
                        prompt_final = consultor._formatear_prompt(pregunta, contexto, agente.descripcion or '', "")

                        return JsonResponse({
                            'result':         True,
                            'prompt_real':    prompt_final,
                            'contexto':       contexto,
                            'chars_prompt':   len(prompt_final),
                            'chars_contexto': len(contexto),
                            'sin_datos':      sin_datos,
                            'faqs_usadas':    list(consultor._faq_ids_usadas or []),
                            'modelo':         apikey_obj.modelo or consultor.model_name,
                            'provider':       apikey_obj.proveedor,
                            'tiene_faiss':    bool(vs_path),
                        })
                    except Exception as ex:
                        return JsonResponse({'result': False, 'message': f'Error al simular: {ex}'})
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
                        # Catálogo de departamentos del usuario para el modal
                        # "Regenerar desde depto" del editor de herramientas.
                        from crm.models import DepartamentoChatBot
                        data_ctx['deptos_disponibles_regen'] = DepartamentoChatBot.objects.filter(
                            status=True,
                        ).order_by('nombre')
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
                if action == 'herramienta_logs_lista':
                    try:
                        from crm.models import HerramientaAgente as _HA, LogHerramientaAgente as _HL
                        from django.utils.dateparse import parse_date
                        from django.db.models import Count, Avg, Sum
                        import datetime
                        agente_id = int(request.GET.get('agente_id') or 0)
                        agente = AgentesIA.objects.get(pk=agente_id, perfil=perfil)
                        herramienta_id = request.GET.get('herramienta_id') or ''
                        estado = (request.GET.get('estado') or '').strip()
                        hoy = datetime.date.today()
                        fi = parse_date(request.GET.get('fecha_inicio') or '') or (hoy - datetime.timedelta(days=6))
                        ff = parse_date(request.GET.get('fecha_fin') or '') or hoy
                        qs = _HL.objects.filter(
                            herramienta__agente=agente,
                            fecha__date__gte=fi, fecha__date__lte=ff,
                        ).select_related('herramienta', 'conversacion__contacto')
                        if herramienta_id and str(herramienta_id).isdigit():
                            qs = qs.filter(herramienta_id=int(herramienta_id))
                        if estado == 'ok':
                            qs = qs.filter(exito=True)
                        elif estado == 'error':
                            qs = qs.filter(exito=False)
                        total = qs.count()
                        qs = qs.order_by('-fecha')[:200]
                        resumen = _HL.objects.filter(
                            herramienta__agente=agente,
                            fecha__date__gte=fi, fecha__date__lte=ff,
                        ).aggregate(
                            total=Count('id'),
                            exitos=Count('id', filter=models.Q(exito=True)),
                            errores=Count('id', filter=models.Q(exito=False)),
                            duracion_prom=Avg('duracion_ms'),
                        )
                        data_ctx = dict(data)
                        data_ctx['agente'] = agente
                        data_ctx['logs'] = qs
                        data_ctx['total_matches'] = total
                        data_ctx['resumen'] = resumen
                        data_ctx['herramientas'] = agente.herramientas.filter(status=True).order_by('nombre')
                        data_ctx['f_herramienta_id'] = str(herramienta_id)
                        data_ctx['f_estado'] = estado
                        data_ctx['f_fecha_inicio'] = str(fi)
                        data_ctx['f_fecha_fin'] = str(ff)
                        template = get_template("crm/entrenamiento/herramienta/logs.html")
                        return JsonResponse({"result": True, 'data': template.render(data_ctx)})
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})
                if action == 'herramienta_log_detalle':
                    try:
                        from crm.models import LogHerramientaAgente as _HL
                        log_id = int(request.GET.get('id') or 0)
                        lg = _HL.objects.select_related(
                            'herramienta__agente__perfil', 'conversacion__contacto'
                        ).get(pk=log_id, herramienta__agente__perfil=perfil)
                        contacto = ''
                        if lg.conversacion and lg.conversacion.contacto:
                            c = lg.conversacion.contacto
                            contacto = f"{c} ({getattr(c, 'numero_telefono', '') or ''})"
                        return JsonResponse({
                            'result': True,
                            'id': lg.id,
                            'fecha': lg.fecha.strftime('%d/%m/%Y %H:%M:%S') if lg.fecha else '',
                            'herramienta': lg.herramienta.nombre_amigable,
                            'slug': lg.herramienta.nombre,
                            'metodo': lg.herramienta.metodo,
                            'url': lg.request_url,
                            'params': lg.request_params or {},
                            'status': lg.response_status,
                            'exito': lg.exito,
                            'duracion_ms': lg.duracion_ms,
                            'response_body': lg.response_body or '',
                            'error_mensaje': lg.error_mensaje or '',
                            'contacto': contacto,
                            'conversacion_id': lg.conversacion_id or None,
                        })
                    except Exception as ex:
                        return JsonResponse({'result': False, 'message': str(ex)})
                if action == 'faq_lista':
                    try:
                        agente_id = int(request.GET.get('agente_id') or 0)
                        agente = AgentesIA.objects.get(pk=agente_id, perfil=perfil)
                        estado_filtro = (request.GET.get('estado') or '').strip()
                        qs = agente.faqs.filter(status=True)
                        if estado_filtro in ('pendiente', 'aprobada', 'desactivada'):
                            qs = qs.filter(estado=estado_filtro)
                        qs = qs.select_related('conversacion_origen', 'mensaje_origen', 'auditoria_origen').order_by('-prioridad', '-fecha_registro')
                        contadores = {
                            'pendiente':   agente.faqs.filter(status=True, estado='pendiente').count(),
                            'aprobada':    agente.faqs.filter(status=True, estado='aprobada').count(),
                            'desactivada': agente.faqs.filter(status=True, estado='desactivada').count(),
                        }
                        data_ctx = dict(data)
                        data_ctx['agente'] = agente
                        data_ctx['faqs'] = qs
                        data_ctx['estado_filtro'] = estado_filtro
                        data_ctx['contadores'] = contadores
                        template = get_template("crm/entrenamiento/faq/lista.html")
                        return JsonResponse({"result": True, 'data': template.render(data_ctx)})
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})
                if action == 'faq_form':
                    try:
                        from crm.forms import FaqAgenteForm
                        from crm.models import FaqAgente as _FA
                        agente_id = int(request.GET.get('agente_id') or 0)
                        agente = AgentesIA.objects.get(pk=agente_id, perfil=perfil)
                        pk = request.GET.get('id')
                        faq = _FA.objects.get(pk=int(pk), agente=agente) if pk else None
                        form = FaqAgenteForm(instance=faq)
                        data_ctx = dict(data)
                        data_ctx['form'] = form
                        data_ctx['faq'] = faq
                        data_ctx['agente'] = agente
                        template = get_template("crm/entrenamiento/faq/form.html")
                        return JsonResponse({"result": True, 'data': template.render(data_ctx)})
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
                        por_origen_qs = (
                            qs.exclude(origen='').exclude(origen__isnull=True)
                              .values('origen')
                              .annotate(llamadas=Count('id'), total=Sum('tokens_total'))
                              .order_by('-total')
                        )
                        ORIGEN_LABELS = dict(ConsumoTokenIA._meta.get_field('origen').choices)
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
                            'por_origen': [
                                {'origen': r['origen'], 'label': str(ORIGEN_LABELS.get(r['origen'], r['origen'])),
                                 'llamadas': r['llamadas'], 'total': r['total'] or 0}
                                for r in por_origen_qs
                            ],
                        })
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})

                elif action == 'consumo_detalle':
                    try:
                        from django.utils.dateparse import parse_date
                        import datetime
                        pk = int(request.GET['id'])
                        apikey = ApiKeyIA.objects.get(pk=pk, perfil=perfil)
                        qs = ConsumoTokenIA.objects.filter(apikey=apikey)
                        dia = request.GET.get('dia')
                        origen = request.GET.get('origen')
                        fecha_inicio = request.GET.get('fecha_inicio')
                        fecha_fin = request.GET.get('fecha_fin')
                        if dia:
                            d = parse_date(dia)
                            if d:
                                qs = qs.filter(fecha__date=d)
                        else:
                            hoy = datetime.date.today()
                            fi = parse_date(fecha_inicio or '') or (hoy - datetime.timedelta(days=29))
                            ff = parse_date(fecha_fin or '') or hoy
                            qs = qs.filter(fecha__date__gte=fi, fecha__date__lte=ff)
                        if origen:
                            qs = qs.filter(origen=origen)
                        registros = qs.order_by('-fecha')[:100].values(
                            'id', 'fecha', 'tokens_entrada', 'tokens_salida', 'tokens_total',
                            'modelo', 'origen', 'prompt_preview', 'agente__nombre',
                        )
                        ORIGEN_LABELS = dict(ConsumoTokenIA._meta.get_field('origen').choices)
                        return JsonResponse({
                            'result': True,
                            'registros': [
                                {
                                    'id': r['id'],
                                    'fecha': r['fecha'].strftime('%d/%m/%Y %H:%M:%S') if r['fecha'] else '',
                                    'tokens_entrada': r['tokens_entrada'] or 0,
                                    'tokens_salida': r['tokens_salida'] or 0,
                                    'tokens_total': r['tokens_total'] or 0,
                                    'modelo': r['modelo'] or '',
                                    'origen': r['origen'] or '',
                                    'origen_label': str(ORIGEN_LABELS.get(r['origen'], r['origen'] or '')),
                                    'prompt_preview': r['prompt_preview'] or '',
                                    'agente': r['agente__nombre'] or '',
                                }
                                for r in registros
                            ],
                            'total': qs.count(),
                        })
                    except Exception as ex:
                        return JsonResponse({"result": False, 'message': str(ex)})

                elif action == 'uso_webservice':
                    try:
                        from django.db.models import Sum, Count
                        from django.utils.dateparse import parse_date
                        from whatsapp.models import TrazaMensajeIA
                        import datetime, json as _json

                        pk = int(request.GET['id'])
                        apikey = ApiKeyIA.objects.get(pk=pk, perfil=perfil)
                        hoy = datetime.date.today()
                        fecha_fin = parse_date(request.GET.get('fecha_fin', '')) or hoy
                        fecha_inicio = parse_date(request.GET.get('fecha_inicio', '')) or (hoy - datetime.timedelta(days=29))

                        WS_ETAPAS = ('ws_request', 'ws_respuesta', 'ws_sin_agente', 'ws_error')
                        base_qs = TrazaMensajeIA.objects.filter(
                            apikey=apikey,
                            etapa__in=WS_ETAPAS,
                            fecha__date__gte=fecha_inicio,
                            fecha__date__lte=fecha_fin,
                        )

                        totales = {
                            'llamadas': base_qs.filter(etapa='ws_request').count(),
                            'exitosas': base_qs.filter(etapa='ws_respuesta').count(),
                            'errores':  base_qs.filter(etapa='ws_error').count(),
                            'sin_agente': base_qs.filter(etapa='ws_sin_agente').count(),
                        }

                        # Top IPs (desde ws_request, parseando detalle JSON)
                        ip_counter = {}
                        for t in base_qs.filter(etapa='ws_request').only('detalle'):
                            try:
                                d = _json.loads(t.detalle) if t.detalle else {}
                            except Exception:
                                continue
                            ip = (d.get('ip') or '').strip() or 'desconocida'
                            rec = ip_counter.setdefault(ip, {'ip': ip, 'llamadas': 0, 'ua': ''})
                            rec['llamadas'] += 1
                            if not rec['ua'] and d.get('user_agent'):
                                rec['ua'] = (d.get('user_agent') or '')[:80]
                        top_ips = sorted(ip_counter.values(), key=lambda r: -r['llamadas'])[:10]

                        # Últimas interacciones: emparejar ws_request ↔ ws_respuesta/ws_error por proximidad
                        eventos = list(
                            base_qs.order_by('-fecha', '-id').values(
                                'id', 'fecha', 'etapa', 'nivel', 'detalle', 'latencia_ms',
                            )[:80]
                        )
                        # Pares: cada respuesta/error se empareja con el request más cercano anterior (misma ip+session si posible)
                        requests_map = {}  # (ip, session_id) → último request no consumido
                        interacciones = []
                        for ev in sorted(eventos, key=lambda e: e['fecha']):
                            try:
                                det = _json.loads(ev['detalle']) if ev['detalle'] else {}
                            except Exception:
                                det = {}
                            key = (det.get('ip') or '', det.get('session_id') or '')
                            if ev['etapa'] == 'ws_request':
                                requests_map[key] = {'ev': ev, 'det': det}
                            else:
                                par = requests_map.pop(key, None)
                                if par is None:
                                    req_det = {}
                                    req_ev = None
                                else:
                                    req_det = par['det']
                                    req_ev = par['ev']
                                interacciones.append({
                                    '_ts': ev['fecha'],
                                    'fecha': ev['fecha'].strftime('%d/%m/%Y %H:%M:%S') if ev['fecha'] else '',
                                    'ip': det.get('ip') or req_det.get('ip') or '',
                                    'user_agent': (det.get('user_agent') or req_det.get('user_agent') or '')[:120],
                                    'session_id': det.get('session_id') or req_det.get('session_id') or '',
                                    'agente': det.get('agente_nombre') or req_det.get('agente_nombre') or '',
                                    'tipo': det.get('tipo') or req_det.get('tipo') or '',
                                    'modelo': det.get('modelo') or req_det.get('modelo') or '',
                                    'mensaje': (det.get('mensaje_preview') or req_det.get('mensaje_preview') or '')[:300],
                                    'respuesta': (det.get('respuesta_preview') or '')[:500],
                                    'tokens_total': (det.get('tokens') or {}).get('total') if isinstance(det.get('tokens'), dict) else 0,
                                    'tokens_entrada': (det.get('tokens') or {}).get('entrada') if isinstance(det.get('tokens'), dict) else 0,
                                    'tokens_salida': (det.get('tokens') or {}).get('salida') if isinstance(det.get('tokens'), dict) else 0,
                                    'latencia_ms': ev['latencia_ms'] or 0,
                                    'estado': ev['etapa'],  # ws_respuesta | ws_error | ws_sin_agente
                                    'error': det.get('exc') or det.get('code') or '',
                                })
                        interacciones.sort(key=lambda r: r['_ts'] or datetime.datetime.min, reverse=True)
                        interacciones = interacciones[:15]
                        for r in interacciones:
                            r.pop('_ts', None)

                        return JsonResponse({
                            'result': True,
                            'apikey_alias': str(apikey),
                            'fecha_inicio': str(fecha_inicio),
                            'fecha_fin': str(fecha_fin),
                            'totales': totales,
                            'top_ips': top_ips,
                            'interacciones': interacciones,
                            'trazabilidad_url': f'/whatsapp/trazas/?solo_webservice=1&apikey={apikey.pk}',
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
                # ── Checks de configuración para el card ───────────────
                a.prompt_configurado = bool((a.prompt_template or '').strip())
                a.num_faqs_aprobadas = a.faqs.filter(status=True, estado='aprobada').count()
                a.num_faqs_pendientes = a.faqs.filter(status=True, estado='pendiente').count()
                a.num_herramientas_activas = a.herramientas.filter(status=True, activo=True).count()
                a.num_enlaces_api = a.detalleagentesai_set.filter(status=True, tipo=1, enlace__isnull=False).count()
                a.num_archivos = a.detalleagentesai_set.filter(status=True, tipo=2, archivo__isnull=False).count()
                a.num_textos = a.detalleagentesai_set.filter(status=True, tipo=3).exclude(descripcion__isnull=True).exclude(descripcion='').count()
                # ── Modelos en uso (del apikey, no del agente) ─────────
                modelos_en_uso = []
                for k in keys:
                    if not k.estado:
                        continue
                    mod = (getattr(k, 'modelo', '') or '').strip()
                    prov_lbl = k.get_proveedor_display() if hasattr(k, 'get_proveedor_display') else ''
                    if mod:
                        modelos_en_uso.append({'provider': prov_lbl, 'modelo': mod, 'alias': k.alias or prov_lbl})
                    else:
                        modelos_en_uso.append({'provider': prov_lbl, 'modelo': '(default)', 'alias': k.alias or prov_lbl})
                a.modelos_en_uso = modelos_en_uso
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
