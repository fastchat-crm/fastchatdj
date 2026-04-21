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

from core.funciones import addData, secure_module, log
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
                    origen = SesionWhatsApp.objects.get(pk=int(request.POST['origen_id']))
                    destino = SesionWhatsApp.objects.get(pk=int(request.POST['destino_id']))
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

                if action == 'enviar_meta':
                    import requests
                    sesion = SesionWhatsApp.objects.get(pk=int(request.POST['sesion_id']))
                    if not sesion.es_meta:
                        return JsonResponse({'error': True, 'message': 'Solo aplica a sesiones Meta.'})
                    cfg = getattr(sesion, 'config_meta', None)
                    if not cfg or not cfg.phone_number_id or not cfg.access_token:
                        return JsonResponse({'error': True, 'message': 'La sesión Meta no tiene config_meta completo (phone_number_id o access_token faltante).'})

                    horarios_qs = sesion.horarios.filter(status=True, activo=True).order_by('dia_semana', 'hora_inicio')
                    horarios_txt = ', '.join(
                        f"{h.get_dia_semana_display()} {h.hora_inicio:%H:%M}-{h.hora_fin:%H:%M}"
                        for h in horarios_qs
                    ) or 'Horario abierto 24/7'
                    about_text = f'Horarios: {horarios_txt}'[:139]  # WABA about: máx 139

                    api_version = 'v21.0'
                    url = f'https://graph.facebook.com/{api_version}/{cfg.phone_number_id}/whatsapp_business_profile'
                    headers = {
                        'Authorization': f'Bearer {cfg.access_token}',
                        'Content-Type': 'application/json',
                    }
                    payload = {'messaging_product': 'whatsapp', 'about': about_text}
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

                    log(f'Envío horarios a Meta para {sesion}: {horarios_txt} (status={meta_status}, ok={ok})',
                        request, 'change', obj=sesion.id)

                    if ok:
                        return JsonResponse({
                            'error': False,
                            'message': 'Configuración de horarios enviada correctamente a Meta.',
                            'meta': {
                                'endpoint': url,
                                'status': meta_status,
                                'about_sent': about_text,
                                'horarios_txt': horarios_txt,
                                'response': meta_resp,
                            },
                        })
                    # Hints por tipo de error para que el usuario sepa que tocar
                    hint = ''
                    _err = (meta_resp or {}).get('error') or {}
                    _code = _err.get('code')
                    _subc = _err.get('error_subcode')
                    if meta_status == 500 and _code == 1:
                        hint = (
                            ' Hint: tu Access Token probablemente no tiene el scope '
                            '"whatsapp_business_management" (solo lo tiene uno de System User, '
                            'no el temporal de API Setup). Regeneralo desde Business Settings → '
                            'System Users con los 3 permisos y volve a probar.'
                        )
                    elif meta_status == 400 and _subc == 2388072:
                        hint = (
                            ' Hint: Meta rechaza el "about" por formato. Evita emojis, '
                            'negritas, saltos de linea o URLs. Max 139 chars.'
                        )
                    elif meta_status == 401:
                        hint = ' Hint: Access Token invalido o expirado. Regeneralo.'
                    elif meta_status == 403:
                        hint = ' Hint: Access Token sin permiso sobre este phone_number_id.'
                    return JsonResponse({
                        'error': True,
                        'message': (err or f'Meta respondió {meta_status}: {meta_resp}') + hint,
                        'meta': {
                            'endpoint': url,
                            'status': meta_status,
                            'about_sent': about_text,
                            'horarios_txt': horarios_txt,
                            'response': meta_resp,
                            'exception': err,
                        },
                    })

                if action == 'generar_horarios_ia' or action == 'generar_excepciones_ia':
                    sesion = SesionWhatsApp.objects.get(pk=int(request.POST['sesion_id']))
                    descripcion = (request.POST.get('descripcion') or '').strip()
                    if len(descripcion) < 10:
                        return JsonResponse({'error': True, 'message': 'Describe con más detalle (mínimo 10 chars).'})
                    from crm.models import ApiKeyIA, ConsumoTokenIA, PerfilNegocioIA
                    perfil = PerfilNegocioIA.objects.filter(usuario=request.user).first()
                    apikey = ApiKeyIA.objects.filter(
                        perfil=perfil, estado=True, status=True,
                    ).first() if perfil else None
                    if not apikey or not (apikey.descripcion or '').strip():
                        return JsonResponse({'error': True, 'message': 'No tienes una API Key IA activa. Configúrala en Entrenamiento > API Keys.'})
                    try:
                        if apikey.proveedor == 2:
                            from langchain_google_genai import ChatGoogleGenerativeAI
                            llm = ChatGoogleGenerativeAI(
                                model=(apikey.modelo or 'gemini-2.5-flash'),
                                google_api_key=apikey.descripcion,
                                max_output_tokens=4000, temperature=0.3,
                                model_kwargs={'response_mime_type': 'application/json'},
                            )
                        elif apikey.proveedor == 4:
                            from langchain_anthropic import ChatAnthropic
                            llm = ChatAnthropic(
                                model=(apikey.modelo or 'claude-haiku-4-5-20251001'),
                                anthropic_api_key=apikey.descripcion,
                                max_tokens=4000, temperature=0.3,
                            )
                        else:
                            from langchain_community.chat_models import ChatOpenAI
                            llm = ChatOpenAI(
                                model_name=(apikey.modelo or 'gpt-4o-mini'),
                                openai_api_key=apikey.descripcion,
                                max_tokens=4000, temperature=0.3,
                                model_kwargs={'response_format': {'type': 'json_object'}},
                            )
                        import datetime as _dt
                        anio_actual = _dt.date.today().year
                        if action == 'generar_horarios_ia':
                            prompt = (
                                "Convierte la descripción en horarios semanales. Responde con SOLO un objeto JSON "
                                "(sin explicaciones, sin ``` markdown, sin texto fuera del JSON).\n\n"
                                "Esquema:\n"
                                "{\n"
                                "  \"horarios\": [\n"
                                "    {\"dia_semana\": 0-6, \"hora_inicio\": \"HH:MM\", \"hora_fin\": \"HH:MM\"}\n"
                                "  ]\n"
                                "}\n"
                                "Donde dia_semana: 0=Lun, 1=Mar, 2=Mié, 3=Jue, 4=Vie, 5=Sáb, 6=Dom. "
                                "Permite múltiples bloques por día. No inventes días no mencionados.\n\n"
                                f"Descripción:\n{descripcion}"
                            )
                        else:
                            prompt = (
                                "Convierte la descripción en excepciones/feriados. Responde con SOLO un objeto JSON "
                                "(sin explicaciones, sin ``` markdown, sin texto fuera del JSON).\n\n"
                                "Esquema:\n"
                                "{\n"
                                "  \"excepciones\": [\n"
                                "    {\"fecha\": \"YYYY-MM-DD\", \"abierto\": true|false, \"motivo\": \"string corto\"}\n"
                                "  ]\n"
                                "}\n"
                                f"Si no se especifica año, usa {anio_actual}. Para feriados latinoamericanos/ecuatorianos, "
                                "resuelve las fechas exactas cuando se mencionen por nombre (ej. 'Navidad' → "
                                f"{anio_actual}-12-25). 'abierto' = false cuando es feriado cerrado, true cuando "
                                "es horario especial.\n\n"
                                f"Descripción:\n{descripcion}"
                            )
                        msg = llm.invoke(prompt)
                        import json as _json, re as _re
                        texto = (getattr(msg, 'content', '') or '').strip()
                        cfg = _extraer_json_seguro(texto)
                        if cfg is None or not isinstance(cfg, dict):
                            return JsonResponse({
                                'error': True,
                                'message': 'La IA devolvió JSON inválido. Intenta reformular la descripción.',
                                'raw_preview': (texto or '')[:600],
                            })

                        if action == 'generar_horarios_ia':
                            items = cfg.get('horarios') or []
                            horarios_crear = []
                            for it in items:
                                try:
                                    d = int(it.get('dia_semana'))
                                    hi = str(it.get('hora_inicio'))[:5]
                                    hf = str(it.get('hora_fin'))[:5]
                                    if 0 <= d <= 6 and len(hi) == 5 and len(hf) == 5:
                                        horarios_crear.append({'dia_semana': d, 'hora_inicio': hi, 'hora_fin': hf})
                                except (TypeError, ValueError):
                                    continue
                            for it in horarios_crear:
                                HorarioAtencion.objects.create(
                                    sesion=sesion, dia_semana=it['dia_semana'],
                                    hora_inicio=it['hora_inicio'], hora_fin=it['hora_fin'],
                                    activo=True, usuario_creacion=request.user,
                                )
                            resultado_key = 'horarios'
                            resultado_msg = f'{len(horarios_crear)} horario(s) generado(s) por IA.'
                            resultado_items = horarios_crear
                        else:
                            items = cfg.get('excepciones') or []
                            excepciones_crear = []
                            import datetime as _dt
                            for it in items:
                                try:
                                    fecha = str(it.get('fecha') or '')[:10]
                                    _dt.datetime.strptime(fecha, '%Y-%m-%d')
                                    abierto = bool(it.get('abierto'))
                                    motivo = str(it.get('motivo') or '')[:200]
                                    excepciones_crear.append({'fecha': fecha, 'abierto': abierto, 'motivo': motivo})
                                except (TypeError, ValueError):
                                    continue
                            for it in excepciones_crear:
                                ExcepcionHorario.objects.update_or_create(
                                    sesion=sesion, fecha=it['fecha'],
                                    defaults={
                                        'abierto': it['abierto'],
                                        'motivo': it['motivo'],
                                        'usuario_creacion': request.user,
                                    }
                                )
                            resultado_key = 'excepciones'
                            resultado_msg = f'{len(excepciones_crear)} excepción(es) generada(s) por IA.'
                            resultado_items = excepciones_crear

                        # Registrar consumo tokens
                        try:
                            _meta = getattr(msg, 'response_metadata', {}) or {}
                            _usage = (
                                getattr(msg, 'usage_metadata', None)
                                or _meta.get('usage_metadata') or _meta.get('token_usage') or {}
                            )
                            _te = _usage.get('input_tokens') or _usage.get('prompt_token_count') or _usage.get('prompt_tokens') or 0
                            _ts = _usage.get('output_tokens') or _usage.get('candidates_token_count') or _usage.get('completion_tokens') or 0
                            if _te or _ts:
                                ConsumoTokenIA.objects.create(
                                    apikey=apikey,
                                    tokens_entrada=_te, tokens_salida=_ts,
                                    tokens_total=_te + _ts,
                                    modelo=getattr(llm, 'model', 'horarios-builder'),
                                    origen='otro',
                                    prompt_preview=descripcion[:300],
                                )
                                from crm.alertas_consumo import verificar_alerta_consumo
                                verificar_alerta_consumo(apikey, _te + _ts)
                        except Exception:
                            pass

                        log(f'IA generó {resultado_msg.lower()} para {sesion}', request, 'add', obj=sesion.id)
                        return JsonResponse({
                            'error': False,
                            'message': resultado_msg,
                            resultado_key: resultado_items,
                            'reload': True,
                        })
                    except Exception as ex:
                        return JsonResponse({'error': True, 'message': f'Fallo IA: {str(ex)[:400]}'})

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

    sesion_id = request.GET.get('sesion')
    sesion_actual = sesiones.filter(pk=sesion_id).first() if sesion_id else sesiones.first()

    data['q_negocio'] = q_negocio
    data['sesiones'] = sesiones
    data['sesion_actual'] = sesion_actual
    data['todas_sesiones'] = SesionWhatsApp.objects.filter(
        status=True, usuario=request.user
    ).exclude(pk=sesion_actual.pk if sesion_actual else 0)

    if sesion_actual:
        data['horarios'] = sesion_actual.horarios.filter(status=True).order_by('dia_semana', 'hora_inicio')
        data['excepciones'] = sesion_actual.excepciones_horario.filter(status=True).order_by('fecha')
        data['negocio'] = getattr(getattr(sesion_actual.usuario, 'perfil_ia', None), 'nombre_empresa', '')

    return render(request, 'whatsapp/horarios/listado.html', data)
