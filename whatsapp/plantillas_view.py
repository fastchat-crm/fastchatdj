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

Incluye generador IA con preview en 2 pasos:
1. preview_plantillas_ia → llama LLM, devuelve N plantillas SIN guardar.
2. confirmar_plantillas_ia → recibe seleccion del usuario, persiste solo esas.
Ambas registran ConsumoTokenIA para trazabilidad.

URL: /whatsapp/plantillas/
"""
import json
import logging

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render

from core.custom_forms import FormError
from core.funciones import addData, paginador, secure_module, log, redirectAfterPostGet, leer_sesion_id, encrypt_sesion_id

from .forms import PlantillaWhatsAppForm
from .models import (
    ConfigMeta, PlantillaWhatsApp, SesionWhatsApp,
    CATEGORIAS_PLANTILLA, ESTADOS_PLANTILLA_META,
)

logger = logging.getLogger(__name__)


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
        sesion_id = leer_sesion_id(request)
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
    sesion_filtro = leer_sesion_id(request)
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
        url_vars += f'&sesion={encrypt_sesion_id(sesion_filtro)}'
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

            elif action == 'preview_plantillas_ia':
                return _preview_plantillas_ia(request)

            elif action == 'confirmar_plantillas_ia':
                return _confirmar_plantillas_ia(request)

            elif action == 'generar_con_ia':
                # Wrapper HTTP: la logica IA vive en
                # `agents_ai/ai_actions/plantillas_wa.py:generar_uno`.
                from agents_ai.ai_actions import IAActionError
                from agents_ai.ai_actions import plantillas_wa
                sesion_id = int(request.POST.get('sesion_id') or 0)
                sesion = SesionWhatsApp.objects.filter(
                    id=sesion_id, usuario=request.user
                ).select_related('agente_ia', 'agente_ia__perfil').first()
                try:
                    resultado = plantillas_wa.generar_uno(
                        descripcion_usuario=request.POST.get('descripcion_ia'),
                        sesion=sesion,
                    )
                except IAActionError as ex:
                    return JsonResponse({'error': True, 'message': str(ex)})
                except Exception as ex:
                    logger.exception('Error generando plantilla con IA')
                    return JsonResponse({'error': True, 'message': f'Error del LLM: {str(ex)[:500]}'})
                log(f"Plantilla generada con IA para sesion {sesion.id}", request, "add", obj=sesion.id)
                return JsonResponse({'error': False, 'plantilla': resultado['plantilla']})

            else:
                return JsonResponse({'error': True, 'message': f'Accion desconocida: {action}'})

    except FormError as ex:
        res_json.append(ex.dict_error)
    except Exception as ex:
        logger.exception('Error en plantillasView')
        res_json.append({'error': True, 'message': f'Error: {str(ex)}'})
    return JsonResponse(res_json, safe=False)


# ===========================================================================
# Generador IA — preview + confirmar (2 pasos). La logica LLM vive en
# `agents_ai/ai_actions/plantillas_wa.py`; aca solo el wrapper HTTP y la
# resolucion de apikey con fallback al perfil del usuario.
# ===========================================================================


def _get_apikey_para_ia(request, sesion):
    """Devuelve la mejor API Key activa para llamar al LLM."""
    from crm.models import ApiKeyIA, PerfilNegocioIA
    # Preferimos la del agente IA de la sesion si existe
    if sesion.agente_ia:
        ak = sesion.agente_ia.apikey.filter(estado=True).first()
        if ak and (ak.descripcion or '').strip():
            return ak
    # Fallback: cualquier ApiKeyIA activa del usuario
    perfil = PerfilNegocioIA.objects.filter(usuario=request.user).first()
    if perfil:
        return ApiKeyIA.objects.filter(perfil=perfil, estado=True).exclude(descripcion='').first()
    return None


def _preview_plantillas_ia(request):
    """Wrapper HTTP: la logica IA vive en
    `agents_ai/ai_actions/plantillas_wa.py:generar_lote`."""
    from agents_ai.ai_actions import IAActionError
    from agents_ai.ai_actions import plantillas_wa
    sesion_id = int(request.POST.get('sesion_id') or 0)
    sesion = SesionWhatsApp.objects.filter(
        id=sesion_id, usuario=request.user, proveedor='meta'
    ).select_related('agente_ia', 'config_meta').first()
    apikey = _get_apikey_para_ia(request, sesion) if sesion else None
    try:
        resultado = plantillas_wa.generar_lote(
            descripcion=request.POST.get('descripcion'),
            n=request.POST.get('n_plantillas') or 3,
            sesion=sesion,
            apikey_obj=apikey,
        )
    except IAActionError as ex:
        return JsonResponse({'error': True, 'message': str(ex)})
    except Exception as ex:
        logger.exception('Error en preview_plantillas_ia')
        return JsonResponse({'error': True, 'message': f'El LLM fallo: {str(ex)[:500]}'})
    return JsonResponse({
        'error': False,
        'plantillas': resultado['plantillas'],
        'count': resultado['count'],
    })


def _confirmar_plantillas_ia(request):
    sesion_id = int(request.POST.get('sesion_id') or 0)
    sesion = SesionWhatsApp.objects.filter(
        id=sesion_id, usuario=request.user, proveedor='meta'
    ).select_related('config_meta').first()
    if not sesion:
        return JsonResponse({'error': True, 'message': 'Sesion Meta no encontrada.'})
    config = getattr(sesion, 'config_meta', None)
    if not config:
        return JsonResponse({'error': True, 'message': 'La sesion no tiene ConfigMeta.'})

    raw = request.POST.get('plantillas_json') or '[]'
    try:
        plantillas = json.loads(raw)
    except Exception:
        return JsonResponse({'error': True, 'message': 'JSON de plantillas invalido.'})
    if not isinstance(plantillas, list) or not plantillas:
        return JsonResponse({'error': True, 'message': 'No hay plantillas para crear.'})

    creadas, dups = 0, 0
    for p in plantillas:
        if not isinstance(p, dict): continue
        nombre = (p.get('nombre') or '').strip()
        if not nombre: continue
        # Evitar duplicado en la misma WABA
        if PlantillaWhatsApp.objects.filter(
            config_meta=config, nombre=nombre, idioma=p.get('idioma') or 'es'
        ).exists():
            dups += 1
            continue
        PlantillaWhatsApp.objects.create(
            config_meta=config,
            nombre=nombre,
            idioma=(p.get('idioma') or 'es')[:8],
            categoria=p.get('categoria') or 'UTILITY',
            header_tipo=p.get('header_tipo') or 'NONE',
            header_contenido=p.get('header_contenido') or '',
            cuerpo=p.get('cuerpo') or '',
            footer=p.get('footer') or '',
            estado_meta='BORRADOR',
            usuario_creacion=request.user,
        )
        creadas += 1

    log(f"IA creo {creadas} plantillas (dups omitidas: {dups}) para sesion {sesion.id}",
        request, "add", obj=sesion.id)
    msg = f'Se crearon {creadas} plantilla(s) en estado BORRADOR.'
    if dups:
        msg += f' ({dups} omitidas por duplicado de nombre).'
    return JsonResponse({'error': False, 'message': msg, 'creadas': creadas, 'duplicadas': dups})
