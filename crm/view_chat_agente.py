import os
import sys
from types import SimpleNamespace

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.conf import settings

from agents_ai.agente_consultor import AgenteConsultor
from agents_ai.memoria_django import DjangoChatMessageHistory
from core.funciones import addData, get_encrypt, get_decrypt, log
from crm.acciones_fin import ejecutar_acciones_fin
from crm.models import AgentesIA, PerfilNegocioIA, ConsumoTokenIA

from langchain_core.messages import HumanMessage, AIMessage


@login_required
def chat_agente_view(request, agente_enc_id):
    data = {
        'titulo': 'Probar Agente IA',
        'descripcion': 'Conversación de prueba con el agente entrenado',
        'ruta': request.path,
    }
    addData(request, data)

    # Desencriptar y verificar que el agente pertenezca al usuario
    try:
        agente_id = int(get_decrypt(agente_enc_id)[1])
        perfil = PerfilNegocioIA.objects.get(usuario=request.user)
        agente = AgentesIA.objects.get(pk=agente_id, perfil=perfil, status=True)
    except Exception:
        return redirect('/crm/entrenamiento/')

    session_id = f"webchat_{agente.id}_{request.user.id}"

    if request.method == 'POST':
        action = request.POST.get('action', 'send')

        # ── Limpiar historial ──────────────────────────────────────────
        if action == 'clear':
            DjangoChatMessageHistory(session_id=session_id).clear()
            log(f"Historial de chat de prueba limpiado para agente {agente}", request, "change", obj=agente.id)
            return JsonResponse({'error': False})

        # ── Enviar mensaje al agente ───────────────────────────────────
        if action == 'send':
            pregunta = request.POST.get('mensaje', '').strip()
            if not pregunta:
                return JsonResponse({'error': True, 'message': 'Escribe un mensaje antes de enviar.'})

            apikey_obj = agente.apikey.filter(estado=True).first()
            if not apikey_obj:
                return JsonResponse({
                    'error': True,
                    'message': 'Este agente no tiene una API Key activa. Configúrala en Entrenamiento IA.'
                })

            vs_path = (
                os.path.join(settings.MEDIA_ROOT, agente.vectorstore_path)
                if agente.vectorstore_path else None
            )
            vectorstore_enlaces_path = None
            try:
                agente.build_enlaces_vectorstore()
                if agente.vectorstore_enlaces_path:
                    vectorstore_enlaces_path = os.path.join(
                        settings.MEDIA_ROOT, agente.vectorstore_enlaces_path
                    )
            except Exception:
                pass

            # ── Configuración de fin de conversación ──────────────────────
            regla_fin = getattr(agente, 'regla_fin', None)
            fin_por_frase = (
                regla_fin is not None
                and regla_fin.activo
                and regla_fin.detectar_por_frase(pregunta)
            )
            detectar_fin_llm = (
                regla_fin is not None
                and regla_fin.activo
                and regla_fin.usar_senal_llm
            )

            # SimpleNamespace provee el .id que AgenteConsultor usa para memoria
            fake_conv = SimpleNamespace(id=session_id, contacto=None)

            try:
                consultor = AgenteConsultor(
                    vectorstore_path=vs_path,
                    vectorstore_enlaces_path=vectorstore_enlaces_path,
                    provider=apikey_obj.proveedor,
                    apikey=apikey_obj.descripcion,
                    conversacion=fake_conv,
                    prompt_template_text=agente.prompt_template,
                    contexto_estatico=agente.contexto_estatico or None,
                    detectar_fin=detectar_fin_llm,
                )
                if agente.anotar_listas:
                    resultado = consultor.consultar_con_listas(pregunta, agente.descripcion)
                else:
                    resultado = consultor.consultar(pregunta, agente.descripcion)
            except Exception as ex:
                line = sys.exc_info()[-1].tb_lineno
                return JsonResponse({
                    'error': True,
                    'message': f'Error al consultar el agente (línea {line}): {ex}'
                })

            fin_detectado = fin_por_frase or resultado.fin_detectado

            # ── Registrar consumo de tokens ───────────────────────────────────
            if resultado.tokens_total > 0:
                try:
                    ConsumoTokenIA.objects.create(
                        apikey=apikey_obj, agente=agente,
                        tokens_entrada=resultado.tokens_entrada,
                        tokens_salida=resultado.tokens_salida,
                        tokens_total=resultado.tokens_total,
                        modelo=consultor.model_name,
                    )
                except Exception:
                    pass

            # ── Ejecutar acciones de fin (sin sesión_id real = chat de prueba) ──
            if fin_detectado and regla_fin:
                try:
                    contexto_fin = {
                        'nombre_contacto': request.user.get_full_name() or request.user.username,
                        'numero': '',
                        'sesion': f'Chat de prueba — {agente.nombre}',
                        'sesion_id': '',   # sin sesión WA real
                        'resumen': '',
                        'agente': agente.nombre,
                    }
                    ejecutar_acciones_fin(regla_fin, contexto_fin)
                except Exception:
                    pass

            return JsonResponse({
                'error': False,
                'respuesta': resultado.respuesta,
                'fin_detectado': fin_detectado,
            })

        return JsonResponse({'error': True, 'message': 'Acción no reconocida.'})

    # ── GET — cargar historial previo ──────────────────────────────────
    raw_messages = DjangoChatMessageHistory(session_id=session_id).messages
    mensajes_previos = []
    for m in raw_messages:
        if isinstance(m, HumanMessage):
            mensajes_previos.append({'tipo': 'humano', 'texto': m.content})
        elif isinstance(m, AIMessage) and not m.content.startswith('LISTA_GUARDADA:'):
            mensajes_previos.append({'tipo': 'ia', 'texto': m.content})

    data['agente'] = agente
    data['agente_enc_id'] = agente_enc_id
    data['mensajes_previos'] = mensajes_previos

    return render(request, 'crm/entrenamiento/chat.html', data)
