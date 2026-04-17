"""Modulo CRUD de plantillas de WhatsApp Cloud API (Meta).

Las plantillas son mensajes pre-aprobados por Meta que permiten iniciar
conversaciones fuera de la ventana de 24h o enviar contenido promocional.
Este modulo permite al usuario del CRM:

- Listar plantillas por sesion (filtradas al usuario).
- Crear borradores que luego se envian a Meta para aprobacion.
- Editar plantillas en estado BORRADOR.
- Sincronizar el estado con Meta (pull).
- Eliminar plantillas.
- Disparar el envio a Meta ('someter para aprobacion').

URL: /whatsapp/plantillas/
"""
import logging

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render

from core.custom_forms import FormError
from core.funciones import addData, paginador, secure_module, log, redirectAfterPostGet

from .forms import PlantillaWhatsAppForm
from .models import (
    ConfigMeta, PlantillaWhatsApp, SesionWhatsApp,
    CATEGORIAS_PLANTILLA, ESTADOS_PLANTILLA_META,
)

logger = logging.getLogger(__name__)


def _registrar_consumo_llm(respuesta_llm, apikey, agente=None, modelo='', conversacion=None,
                           origen='plantilla', prompt_preview=''):
    """Extrae tokens de la respuesta LangChain y crea ConsumoTokenIA + alerta."""
    try:
        from crm.models import ConsumoTokenIA
        from crm.alertas_consumo import verificar_alerta_consumo
        meta = getattr(respuesta_llm, 'response_metadata', {}) or {}
        usage = (
            getattr(respuesta_llm, 'usage_metadata', None)
            or meta.get('usage_metadata')
            or meta.get('token_usage')
            or {}
        )
        tokens_e = usage.get('input_tokens') or usage.get('prompt_token_count') or usage.get('prompt_tokens') or 0
        tokens_s = usage.get('output_tokens') or usage.get('candidates_token_count') or usage.get('completion_tokens') or 0
        if tokens_e or tokens_s:
            ConsumoTokenIA.objects.create(
                apikey=apikey, agente=agente, conversacion=conversacion,
                tokens_entrada=tokens_e, tokens_salida=tokens_s,
                tokens_total=tokens_e + tokens_s,
                modelo=modelo or getattr(respuesta_llm, 'model', ''),
                origen=origen, prompt_preview=(prompt_preview or '')[:300],
            )
            verificar_alerta_consumo(apikey, tokens_e + tokens_s)
    except Exception:
        logger.exception('Error registrando consumo de tokens')


def _sesiones_meta_del_usuario(user):
    """Sesiones proveedor=meta del usuario que tienen ConfigMeta creada."""
    return SesionWhatsApp.objects.filter(
        usuario=user, status=True, proveedor='meta',
        config_meta__isnull=False,
    ).select_related('config_meta').order_by('nombre')


@login_required
@secure_module
def plantillasView(request):
    data = {
        'titulo': 'Plantillas WhatsApp (Meta)',
        'descripcion': 'Gestion de plantillas pre-aprobadas para Meta Cloud API',
        'ruta': request.path,
    }
    addData(request, data)

    if request.method == 'POST':
        return _manejar_post(request, data)

    # ===== LISTADO / FORMULARIOS GET =====
    action = request.GET.get('action')
    data['action'] = action

    if action == 'add':
        sesion_id = request.GET.get('sesion_id')
        config_meta = None
        if sesion_id:
            sesion = SesionWhatsApp.objects.filter(
                id=sesion_id, usuario=request.user, proveedor='meta'
            ).first()
            if sesion:
                config_meta = getattr(sesion, 'config_meta', None)
        data['form'] = PlantillaWhatsAppForm()
        data['sesiones_meta'] = _sesiones_meta_del_usuario(request.user)
        data['config_meta_preseleccionada'] = config_meta
        return render(request, 'whatsapp/plantillas/form.html', data)

    if action == 'change':
        pk = request.GET.get('pk')
        plantilla = PlantillaWhatsApp.objects.filter(
            id=pk, config_meta__sesion__usuario=request.user
        ).select_related('config_meta', 'config_meta__sesion').first()
        if not plantilla:
            return render(request, 'whatsapp/plantillas/listado.html', data)
        data['instance'] = plantilla
        data['form'] = PlantillaWhatsAppForm(instance=plantilla)
        data['sesiones_meta'] = _sesiones_meta_del_usuario(request.user)
        data['config_meta_preseleccionada'] = plantilla.config_meta
        return render(request, 'whatsapp/plantillas/form.html', data)

    # ===== LISTADO =====
    sesiones_ids = list(_sesiones_meta_del_usuario(request.user).values_list('id', flat=True))
    filtros = Q(config_meta__sesion_id__in=sesiones_ids)

    criterio = (request.GET.get('criterio') or '').strip()
    sesion_filtro = request.GET.get('sesion') or ''
    estado_filtro = request.GET.get('estado') or ''
    categoria_filtro = request.GET.get('categoria') or ''

    url_vars = ''
    if criterio:
        filtros &= Q(nombre__icontains=criterio) | Q(cuerpo__icontains=criterio)
        data['criterio'] = criterio
        url_vars += f'&criterio={criterio}'
    if sesion_filtro:
        filtros &= Q(config_meta__sesion_id=sesion_filtro)
        data['sesion_sel'] = int(sesion_filtro)
        url_vars += f'&sesion={sesion_filtro}'
    if estado_filtro:
        filtros &= Q(estado_meta=estado_filtro)
        data['estado_sel'] = estado_filtro
        url_vars += f'&estado={estado_filtro}'
    if categoria_filtro:
        filtros &= Q(categoria=categoria_filtro)
        data['categoria_sel'] = categoria_filtro
        url_vars += f'&categoria={categoria_filtro}'

    listado = PlantillaWhatsApp.objects.filter(filtros).select_related(
        'config_meta', 'config_meta__sesion'
    ).order_by('-fecha_modificacion')

    data['url_vars'] = url_vars
    data['list_count'] = listado.count()
    data['sesiones_meta'] = _sesiones_meta_del_usuario(request.user)
    data['estados_meta'] = ESTADOS_PLANTILLA_META
    data['categorias'] = CATEGORIAS_PLANTILLA

    paginador(request, listado, 20, data, url_vars)
    return render(request, 'whatsapp/plantillas/listado.html', data)


def _manejar_post(request, data):
    action = request.POST.get('action')
    res_json = []
    try:
        with transaction.atomic():
            if action == 'add':
                sesion_id = int(request.POST.get('sesion_id') or 0)
                sesion = SesionWhatsApp.objects.filter(
                    id=sesion_id, usuario=request.user, proveedor='meta'
                ).first()
                if not sesion or not hasattr(sesion, 'config_meta'):
                    return JsonResponse({'error': True, 'message': 'Sesion Meta invalida o sin configuracion.'})
                form = PlantillaWhatsAppForm(request.POST)
                if not form.is_valid():
                    raise FormError(form)
                plantilla = form.save(commit=False)
                plantilla.config_meta = sesion.config_meta
                plantilla.estado_meta = 'BORRADOR'
                plantilla.save()
                log(f"Plantilla creada #{plantilla.id} ({plantilla.nombre})", request, "add", obj=plantilla.id)
                res_json.append({'error': False, 'to': redirectAfterPostGet(request)})
                return JsonResponse(res_json, safe=False)

            elif action == 'change':
                pk = int(request.POST.get('pk'))
                plantilla = PlantillaWhatsApp.objects.filter(
                    id=pk, config_meta__sesion__usuario=request.user
                ).first()
                if not plantilla:
                    return JsonResponse({'error': True, 'message': 'Plantilla no encontrada.'})
                if plantilla.estado_meta not in ('BORRADOR', 'REJECTED'):
                    return JsonResponse({
                        'error': True,
                        'message': 'Solo se pueden editar plantillas en BORRADOR o RECHAZADAS.'
                    })
                form = PlantillaWhatsAppForm(request.POST, instance=plantilla)
                if not form.is_valid():
                    raise FormError(form)
                form.save()
                log(f"Plantilla modificada #{plantilla.id}", request, "change", obj=plantilla.id)
                res_json.append({'error': False, 'to': redirectAfterPostGet(request)})
                return JsonResponse(res_json, safe=False)

            elif action == 'delete':
                pk = int(request.POST.get('id'))
                plantilla = PlantillaWhatsApp.objects.filter(
                    id=pk, config_meta__sesion__usuario=request.user
                ).first()
                if not plantilla:
                    return JsonResponse({'error': True, 'message': 'Plantilla no encontrada.'})

                # Si esta aprobada en Meta, intentar eliminar alla tambien
                if plantilla.estado_meta == 'APPROVED' and plantilla.id_meta:
                    try:
                        from .services_meta import MetaWhatsAppService
                        service = MetaWhatsAppService()
                        # (Endpoint de Meta para borrar: requiere nombre como param)
                        import requests
                        config = plantilla.config_meta
                        requests.delete(
                            f'https://graph.facebook.com/v21.0/{config.waba_id}/message_templates',
                            headers={'Authorization': f'Bearer {config.access_token}'},
                            params={'name': plantilla.nombre},
                            timeout=10,
                        )
                    except Exception:
                        logger.exception('Error eliminando plantilla en Meta')
                plantilla.delete()
                log(f"Plantilla eliminada #{pk}", request, "del", obj=pk)
                return JsonResponse({'error': False, 'message': 'Plantilla eliminada.'})

            elif action == 'someter_a_meta':
                pk = int(request.POST.get('id'))
                plantilla = PlantillaWhatsApp.objects.filter(
                    id=pk, config_meta__sesion__usuario=request.user
                ).first()
                if not plantilla:
                    return JsonResponse({'error': True, 'message': 'Plantilla no encontrada.'})
                if plantilla.estado_meta not in ('BORRADOR', 'REJECTED'):
                    return JsonResponse({
                        'error': True,
                        'message': f'No se puede someter en estado {plantilla.get_estado_meta_display()}.'
                    })
                from .services_meta import MetaWhatsAppService
                result = MetaWhatsAppService().crear_plantilla_en_meta(
                    plantilla.config_meta.sesion.session_id, plantilla
                )
                if result.get('success'):
                    log(f"Plantilla {plantilla.nombre} sometida a Meta", request, "change", obj=plantilla.id)
                    return JsonResponse({
                        'error': False,
                        'message': 'Plantilla enviada a Meta. El estado se actualizara cuando Meta apruebe/rechace.',
                        'id_meta': result.get('id_meta'),
                    })
                return JsonResponse({
                    'error': True,
                    'message': f"Meta rechazo el envio: {result.get('error', 'error desconocido')}",
                })

            elif action == 'sincronizar':
                sesion_id = int(request.POST.get('sesion_id') or 0)
                sesion = SesionWhatsApp.objects.filter(
                    id=sesion_id, usuario=request.user, proveedor='meta'
                ).first()
                if not sesion:
                    return JsonResponse({'error': True, 'message': 'Sesion Meta no encontrada.'})
                from .services_meta import MetaWhatsAppService
                result = MetaWhatsAppService().sincronizar_plantillas(sesion.session_id)
                if result.get('success'):
                    log(f"Plantillas sincronizadas desde Meta (sesion {sesion.id})",
                        request, "change", obj=sesion.id)
                    return JsonResponse({
                        'error': False,
                        'actualizadas': result.get('actualizadas', 0),
                        'total_remoto': result.get('total_remoto', 0),
                        'message': f"{result.get('actualizadas', 0)} plantilla(s) sincronizada(s) de {result.get('total_remoto', 0)} remotas.",
                    })
                return JsonResponse({
                    'error': True,
                    'message': f"Error sincronizando: {result.get('error', 'desconocido')}",
                })

            elif action == 'generar_con_ia':
                sesion_id = int(request.POST.get('sesion_id') or 0)
                descripcion_usuario = (request.POST.get('descripcion_ia') or '').strip()
                if not descripcion_usuario:
                    return JsonResponse({'error': True, 'message': 'Escribe una descripcion de la plantilla que quieres generar.'})
                sesion = SesionWhatsApp.objects.filter(
                    id=sesion_id, usuario=request.user
                ).select_related('agente_ia', 'agente_ia__perfil').first()
                if not sesion:
                    return JsonResponse({'error': True, 'message': 'Sesion no encontrada.'})
                agente = sesion.agente_ia
                if not agente:
                    return JsonResponse({'error': True, 'message': 'La sesion no tiene un agente IA asignado.'})
                apikey = agente.apikey.filter(estado=True).first()
                if not apikey:
                    return JsonResponse({'error': True, 'message': 'El agente no tiene API Keys activas.'})

                contexto_negocio = ''
                if agente.perfil:
                    contexto_negocio = agente.perfil.resumen_contexto_ia()
                if agente.contexto_estatico:
                    contexto_negocio += '\n\nInformacion adicional del agente:\n' + agente.contexto_estatico[:2000]

                prompt = f"""Eres un experto en plantillas de WhatsApp Business (Meta Cloud API).
Genera UNA plantilla de mensaje basandote en:

CONTEXTO DEL NEGOCIO:
{contexto_negocio}

SOLICITUD DEL USUARIO:
{descripcion_usuario}

Responde SOLO con un bloque JSON valido (sin markdown, sin texto extra) con esta estructura exacta:
{{
  "nombre": "slug_en_minusculas_con_guiones_bajos",
  "categoria": "UTILITY o MARKETING o AUTHENTICATION",
  "idioma": "es",
  "header_tipo": "NONE o TEXT o IMAGE",
  "header_contenido": "texto del header o vacio si NONE",
  "cuerpo": "texto principal con {{{{1}}}}, {{{{2}}}}, etc para variables",
  "footer": "pie opcional o vacio",
  "variables_json": [
    {{"nombre": "nombre_descriptivo", "ejemplo": "valor de ejemplo"}},
  ]
}}

Reglas:
- Los placeholders deben ser estrictamente {{{{1}}}}, {{{{2}}}}, {{{{3}}}}... en orden consecutivo.
- El nombre debe ser slug valido: solo a-z, 0-9 y guiones bajos, maximo 512 chars.
- El footer tiene maximo 60 caracteres.
- UTILITY es para confirmaciones, recordatorios, seguimiento. MARKETING para promos, ofertas, engagement.
- Usa emojis con moderacion. Escribe en espanol.
- El cuerpo debe ser natural, profesional y conciso.
"""
                try:
                    from agents_ai.agente_resumidor import AgenteResumidor
                    provider_map = {2: 'gemini', 3: 'openai'}
                    provider = provider_map.get(apikey.proveedor, 'gemini')
                    model_name = apikey.modelo or ('gemini-2.0-flash' if provider == 'gemini' else 'gpt-4o-mini')

                    if provider == 'gemini':
                        from langchain_google_genai import ChatGoogleGenerativeAI
                        llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=apikey.descripcion)
                    else:
                        from langchain_community.chat_models import ChatOpenAI
                        llm = ChatOpenAI(model_name=model_name, openai_api_key=apikey.descripcion)

                    respuesta = llm.invoke(prompt)
                    texto = respuesta.content.strip()
                    # Limpiar si viene envuelto en ```json ... ```
                    if texto.startswith('```'):
                        texto = texto.split('\n', 1)[-1].rsplit('```', 1)[0].strip()

                    # Registrar consumo de tokens
                    _registrar_consumo_llm(respuesta, apikey, agente, model_name,
                                           origen='plantilla', prompt_preview=descripcion_usuario)

                    import json as _json
                    plantilla_data = _json.loads(texto)
                    log(f"Plantilla generada con IA para sesion {sesion.id}", request, "add", obj=sesion.id)
                    return JsonResponse({'error': False, 'plantilla': plantilla_data})

                except Exception as e:
                    logger.exception('Error generando plantilla con IA')
                    return JsonResponse({'error': True, 'message': f'Error del LLM: {str(e)[:500]}'})

            else:
                return JsonResponse({'error': True, 'message': f'Accion desconocida: {action}'})

    except FormError as ex:
        res_json.append(ex.dict_error)
    except Exception as ex:
        logger.exception('Error en plantillasView')
        res_json.append({'error': True, 'message': f'Error: {str(ex)}'})
    return JsonResponse(res_json, safe=False)
