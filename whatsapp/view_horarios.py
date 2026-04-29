"""Vista de horarios de atención (business hours).

Funcionalidad:
- CRUD de horarios semanales y excepciones.
- Búsqueda de sesiones por nombre de negocio (PerfilNegocioIA).
- "Plantilla": duplica horarios de una sesión a otra.
- Enviar configuración a Meta (si la sesión es proveedor='meta').
"""
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, secure_module, log, leer_sesion_id
from .models import (
    SesionWhatsApp, HorarioAtencion, ExcepcionHorario, DIAS_SEMANA,
)


def _extraer_json_seguro(texto: str):
    """Intenta extraer un dict JSON de una respuesta LLM tolerando prosa/fences.

    Estrategias en cascada:
    1. Parse directo.
    2. Si empieza con fence ``` (opcionalmente "json"), quitar fences y reintentar.
    3. Buscar el primer bloque { ... } balanceado y parsearlo.
    Devuelve dict o None si ninguna estrategia funciona.
    """
    import json as _json
    import re as _re
    if not texto:
        return None
    t = texto.strip()
    # 1) Parse directo
    try:
        return _json.loads(t)
    except Exception:
        pass
    # 2) Quitar fences ```json ... ``` o ``` ... ```
    if '```' in t:
        m = _re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', t, _re.IGNORECASE)
        if m:
            try:
                return _json.loads(m.group(1))
            except Exception:
                pass
    # 3) Buscar { ... } balanceado (primer objeto completo)
    start = t.find('{')
    if start != -1:
        depth = 0
        for i in range(start, len(t)):
            ch = t[i]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidato = t[start:i + 1]
                    try:
                        return _json.loads(candidato)
                    except Exception:
                        break
    # 4) Salvage de JSON truncado: si la respuesta se cortó por max_tokens,
    #    intentamos cerrar arrays/objetos descartando el último item inconcluso.
    if start != -1:
        # Remover posible fence de apertura sobrante
        t2 = t[start:]
        if '```' in t2:
            t2 = t2.split('```', 1)[0]
        # Buscar la última coma con un objeto cerrado antes para truncar limpio
        # Ej: ...{"a":1},{"b":2  → cortamos hasta la última "},"
        last_complete = t2.rfind('},')
        if last_complete != -1:
            fragmento = t2[:last_complete + 1]  # incluye el "}"
            # Cerrar arrays y objetos abiertos balanceando
            abiertos_llaves = fragmento.count('{') - fragmento.count('}')
            abiertos_corchs = fragmento.count('[') - fragmento.count(']')
            cierre = (']' * abiertos_corchs) + ('}' * abiertos_llaves)
            candidato2 = fragmento + cierre
            try:
                return _json.loads(candidato2)
            except Exception:
                pass
    return None


@login_required
@secure_module
def horariosView(request):
    data = {
        'titulo': 'Horarios de atención',
        'descripcion': 'Configura horarios, feriados y aplica plantillas por negocio',
        'ruta': request.path,
        'dias_semana': DIAS_SEMANA,
    }
    addData(request, data)

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            with transaction.atomic():
                if action == 'add_horario':
                    sesion = SesionWhatsApp.objects.get(pk=int(request.POST['sesion_id']))
                    HorarioAtencion.objects.create(
                        sesion=sesion,
                        dia_semana=int(request.POST['dia_semana']),
                        hora_inicio=request.POST['hora_inicio'],
                        hora_fin=request.POST['hora_fin'],
                        activo=True,
                        usuario_creacion=request.user,
                    )
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'delete_horario':
                    HorarioAtencion.objects.filter(pk=int(request.POST['id'])).delete()
                    return JsonResponse({'error': False})

                if action == 'add_excepcion':
                    sesion = SesionWhatsApp.objects.get(pk=int(request.POST['sesion_id']))
                    ExcepcionHorario.objects.update_or_create(
                        sesion=sesion,
                        fecha=request.POST['fecha'],
                        defaults={
                            'abierto': request.POST.get('abierto') == 'true',
                            'hora_inicio': request.POST.get('hora_inicio') or None,
                            'hora_fin': request.POST.get('hora_fin') or None,
                            'motivo': request.POST.get('motivo', ''),
                            'usuario_creacion': request.user,
                        }
                    )
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'delete_excepcion':
                    ExcepcionHorario.objects.filter(pk=int(request.POST['id'])).delete()
                    return JsonResponse({'error': False})

                if action == 'guardar_mensaje_fuera_horario':
                    sesion = SesionWhatsApp.objects.get(pk=int(request.POST['sesion_id']))
                    sesion.mensaje_fuera_horario = request.POST.get('mensaje', '')
                    sesion.zona_horaria = request.POST.get('zona_horaria') or sesion.zona_horaria
                    sesion.save(update_fields=['mensaje_fuera_horario', 'zona_horaria'])
                    return JsonResponse({'error': False})

                if action == 'duplicar':
                    from core.funciones import decrypt_sesion_id
                    origen = SesionWhatsApp.objects.get(pk=int(request.POST['origen_id']))
                    destino_pk = decrypt_sesion_id(request.POST['destino_id'])
                    destino = SesionWhatsApp.objects.get(pk=destino_pk)
                    if origen.pk == destino.pk:
                        return JsonResponse({'error': True, 'message': 'Origen y destino son la misma sesión.'})
                    HorarioAtencion.objects.filter(sesion=destino).delete()
                    copiados = 0
                    for h in origen.horarios.filter(status=True, activo=True):
                        HorarioAtencion.objects.create(
                            sesion=destino,
                            dia_semana=h.dia_semana,
                            hora_inicio=h.hora_inicio,
                            hora_fin=h.hora_fin,
                            activo=True,
                            usuario_creacion=request.user,
                        )
                        copiados += 1
                    destino.mensaje_fuera_horario = origen.mensaje_fuera_horario
                    destino.zona_horaria = origen.zona_horaria or destino.zona_horaria
                    destino.save(update_fields=['mensaje_fuera_horario', 'zona_horaria'])
                    log(f'Duplicó horarios de {origen} → {destino} ({copiados})',
                        request, 'add', obj=destino.id)
                    return JsonResponse({
                        'error': False,
                        'message': f'{copiados} horario(s) duplicado(s) a {destino}.',
                    })

                if action == 'consultar_meta_profile':
                    """Lee el whatsapp_business_profile actual desde Graph API
                    para que la UI lo muestre antes de proponer cambios."""
                    import requests
                    sesion = SesionWhatsApp.objects.get(pk=int(request.POST['sesion_id']))
                    if not sesion.es_meta:
                        return JsonResponse({'error': True, 'message': 'Solo aplica a sesiones Meta.'})
                    cfg = getattr(sesion, 'config_meta', None)
                    if not cfg or not cfg.phone_number_id or not cfg.access_token:
                        return JsonResponse({'error': True, 'message': 'La sesión Meta no tiene config_meta completo.'})

                    api_version = 'v21.0'
                    fields = 'about,description,address,email,vertical,websites,profile_picture_url,messaging_product'
                    url = f'https://graph.facebook.com/{api_version}/{cfg.phone_number_id}/whatsapp_business_profile?fields={fields}'
                    try:
                        resp = requests.get(url, headers={'Authorization': f'Bearer {cfg.access_token}'}, timeout=15)
                        data = resp.json() if resp.status_code == 200 else {}
                        # Meta envuelve los campos en data[0]
                        perfil = (data.get('data') or [{}])[0] if data.get('data') else data
                    except Exception as ex:
                        return JsonResponse({'error': True, 'message': f'Graph API: {ex}'})
                    if resp.status_code != 200:
                        return JsonResponse({
                            'error': True,
                            'message': f'Meta devolvió {resp.status_code}',
                            'response': data,
                        })
                    # Adicional: deep-link Meta para que el operador edite directo
                    business_id = cfg.business_account_id or ''
                    deep_link = f'https://business.facebook.com/latest/whatsapp_manager/phone_numbers'
                    if business_id:
                        deep_link += f'?business_id={business_id}&waba_id={cfg.waba_id}'

                    # Generar el texto de horarios sugerido (no enviado todavía)
                    horarios_qs = sesion.horarios.filter(status=True, activo=True).order_by('dia_semana', 'hora_inicio')
                    horarios_txt = ', '.join(
                        f"{h.get_dia_semana_display()} {h.hora_inicio:%H:%M}-{h.hora_fin:%H:%M}"
                        for h in horarios_qs
                    ) or ''
                    sugerido_description = (
                        f"Horarios de atención: {horarios_txt}." if horarios_txt else ''
                    )[:512]  # Meta description: máx 512

                    return JsonResponse({
                        'error': False,
                        'profile': {
                            'about':               perfil.get('about') or '',
                            'description':         perfil.get('description') or '',
                            'address':             perfil.get('address') or '',
                            'email':               perfil.get('email') or '',
                            'vertical':            perfil.get('vertical') or '',
                            'websites':            perfil.get('websites') or [],
                            'profile_picture_url': perfil.get('profile_picture_url') or '',
                        },
                        'horarios_txt': horarios_txt,
                        'sugerido_description': sugerido_description,
                        'deep_link_meta': deep_link,
                    })

                if action == 'actualizar_meta_profile':
                    """Acepta cualquier combinación de campos editables y los manda
                    a Graph API. NO pisa lo que no se mandó (Meta hace patch).
                    """
                    import requests
                    sesion = SesionWhatsApp.objects.get(pk=int(request.POST['sesion_id']))
                    if not sesion.es_meta:
                        return JsonResponse({'error': True, 'message': 'Solo aplica a sesiones Meta.'})
                    cfg = getattr(sesion, 'config_meta', None)
                    if not cfg or not cfg.phone_number_id or not cfg.access_token:
                        return JsonResponse({'error': True, 'message': 'La sesión Meta no tiene config_meta completo.'})

                    payload = {'messaging_product': 'whatsapp'}
                    for campo in ('about', 'description', 'address', 'email', 'vertical'):
                        valor = (request.POST.get(campo) or '').strip()
                        if valor:
                            payload[campo] = valor
                    # Websites: hasta 2 URLs separadas por coma
                    websites_raw = (request.POST.get('websites') or '').strip()
                    if websites_raw:
                        payload['websites'] = [w.strip() for w in websites_raw.split(',') if w.strip()][:2]

                    if len(payload) == 1:  # solo messaging_product
                        return JsonResponse({'error': True, 'message': 'No hay nada para actualizar.'})

                    api_version = 'v21.0'
                    url = f'https://graph.facebook.com/{api_version}/{cfg.phone_number_id}/whatsapp_business_profile'
                    headers = {
                        'Authorization': f'Bearer {cfg.access_token}',
                        'Content-Type': 'application/json',
                    }
                    fields_sent = {k: v for k, v in payload.items() if k != 'messaging_product'}
                    meta_status, meta_resp, err = None, {}, None
                    try:
                        resp = requests.post(url, headers=headers, json=payload, timeout=15)
                        meta_status = resp.status_code
                        try:
                            meta_resp = resp.json()
                        except Exception:
                            meta_resp = {'raw': resp.text[:500]}
                        ok = 200 <= resp.status_code < 300
                    except Exception as ex:
                        ok = False
                        err = str(ex)[:400]

                    log(f'Update perfil Meta para {sesion}: {list(fields_sent.keys())} (status={meta_status}, ok={ok})',
                        request, 'change', obj=sesion.id)

                    if ok:
                        return JsonResponse({
                            'error': False,
                            'message': 'Perfil de WhatsApp actualizado correctamente en Meta.',
                            'meta': {
                                'endpoint': url,
                                'status': meta_status,
                                'fields_sent': fields_sent,
                                'response': meta_resp,
                            },
                        })
                    # Hints por tipo de error para que el operador sepa que tocar
                    hint = ''
                    _err = (meta_resp or {}).get('error') or {}
                    _code = _err.get('code')
                    _subc = _err.get('error_subcode')
                    if meta_status == 500 and _code == 1:
                        hint = (
                            ' Hint: tu Access Token probablemente no tiene el scope '
                            '"whatsapp_business_management". Regenerá desde Business Settings → '
                            'System Users con los 3 permisos y volvé a probar.'
                        )
                    elif meta_status == 400 and _subc == 2388072:
                        hint = (
                            ' Hint: Meta rechaza el formato. Evitá emojis, negritas, '
                            'saltos de linea o URLs en about (máx 139 chars).'
                        )
                    elif meta_status == 401:
                        hint = ' Hint: Access Token invalido o expirado.'
                    elif meta_status == 403:
                        hint = ' Hint: Access Token sin permiso sobre este phone_number_id.'
                    return JsonResponse({
                        'error': True,
                        'message': (err or f'Meta respondió {meta_status}') + hint,
                        'meta': {
                            'endpoint': url,
                            'status': meta_status,
                            'fields_sent': fields_sent,
                            'response': meta_resp,
                            'exception': err,
                        },
                    })

                if action == 'generar_horarios_ia' or action == 'generar_excepciones_ia':
                    # Wrapper HTTP: la logica IA vive en
                    # `agents_ai/ai_actions/horarios_wa.py`.
                    from agents_ai.ai_actions import IAActionError
                    from agents_ai.ai_actions import horarios_wa
                    from crm.models import ApiKeyIA, PerfilNegocioIA
                    sesion = SesionWhatsApp.objects.get(pk=int(request.POST['sesion_id']))
                    perfil = PerfilNegocioIA.objects.filter(usuario=request.user).first()
                    apikey = ApiKeyIA.objects.filter(
                        perfil=perfil, estado=True, status=True,
                    ).first() if perfil else None
                    if not apikey or not (apikey.descripcion or '').strip():
                        return JsonResponse({'error': True, 'message': 'No tienes una API Key IA activa. Configúrala en Entrenamiento > API Keys.'})

                    try:
                        if action == 'generar_horarios_ia':
                            resultado = horarios_wa.generar_semanales(
                                descripcion=request.POST.get('descripcion'),
                                sesion=sesion, apikey_obj=apikey, request=request,
                            )
                            resultado_key = 'horarios'
                        else:
                            resultado = horarios_wa.generar_excepciones(
                                descripcion=request.POST.get('descripcion'),
                                sesion=sesion, apikey_obj=apikey, request=request,
                            )
                            resultado_key = 'excepciones'
                    except IAActionError as ex:
                        return JsonResponse({'error': True, 'message': str(ex)})
                    except Exception as ex:
                        return JsonResponse({'error': True, 'message': f'Fallo IA: {str(ex)[:400]}'})

                    log(f"IA generó {resultado['message'].lower()} para {sesion}", request, 'add', obj=sesion.id)
                    return JsonResponse({
                        'error': False,
                        'message': resultado['message'],
                        resultado_key: resultado['items'],
                        'reload': True,
                    })

        except SesionWhatsApp.DoesNotExist:
            return JsonResponse({'error': True, 'message': 'Sesión no encontrada.'})
        except Exception as ex:
            return JsonResponse({'error': True, 'message': str(ex)})

    sesiones = SesionWhatsApp.objects.filter(status=True, usuario=request.user).select_related(
        'usuario__perfil_ia'
    )

    q_negocio = (request.GET.get('q') or '').strip()
    if q_negocio:
        sesiones = sesiones.filter(
            Q(usuario__perfil_ia__nombre_empresa__icontains=q_negocio) |
            Q(nombre__icontains=q_negocio) |
            Q(numero__icontains=q_negocio)
        )

    sesion_id = leer_sesion_id(request)
    sesion_actual = sesiones.filter(pk=sesion_id).first() if sesion_id else sesiones.first()

    data['q_negocio'] = q_negocio
    data['sesiones'] = sesiones
    data['sesion_actual'] = sesion_actual
    data['todas_sesiones'] = sesiones.exclude(pk=sesion_actual.pk if sesion_actual else 0)

    if sesion_actual:
        data['horarios'] = sesion_actual.horarios.filter(status=True).order_by('dia_semana', 'hora_inicio')
        data['excepciones'] = sesion_actual.excepciones_horario.filter(status=True).order_by('fecha')
        data['negocio'] = getattr(getattr(sesion_actual.usuario, 'perfil_ia', None), 'nombre_empresa', '')

    return render(request, 'whatsapp/horarios/listado.html', data)
