"""
crm/view_prueba_chatbot.py

Vista de prueba del chatbot TRADICIONAL (motor de flujo por departamentos).
Ejecuta `MotorFlujo` en modo dry-run usando un WhatsApp service stub, de modo
que el flujo se puede probar in-app sin enviar mensajes reales al número WA.

URL: /crm/departamentos_chatbots/prueba/<sesion_enc_id>/

Entrada: sesion_enc_id = ID de SesionWhatsApp encriptado (get_encrypt).
Acciones POST:
    action=send    → mensaje (string) → JSON con respuestas[] + traza del flujo
    action=reset   → borra el EstadoFlujoChatbot del contacto de prueba
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone

from core.funciones import addData, get_decrypt, log
from crm.models import EstadoFlujoChatbot
from crm.motor_flujo_chatbot import MotorFlujo
from whatsapp.models import Contacto, ConversacionWhatsApp, SesionWhatsApp

logger = logging.getLogger(__name__)


# Identificador "virtual" del contacto de prueba — único por (usuario, sesion).
# IMPORTANTE: Contacto.save() reescribe `from_number` cuando `numero_telefono` tiene
# dígitos (extrae los dígitos → from_number="N@s.whatsapp.net"), lo que colisiona
# con contactos reales. Por eso dejamos `numero_telefono=''` y usamos un token sin
# dígitos sueltos como from_number/contacto_numero, preservándolos intactos.
def _test_numero(user_id: int, sesion_id: int) -> str:
    return f"__test_user{user_id}_sesion{sesion_id}"


class StubWhatsAppService:
    """Reemplazo de WhatsAppService que captura envíos en vez de mandarlos a la API.

    `MotorFlujo.enviar()` llama `ws.send_text_message(...)` y luego appendea el
    texto resuelto a `motor.respuestas`. Este stub simplemente registra la
    llamada y devuelve un dict exitoso para que no se dispare la rama `except`.
    """

    def __init__(self):
        self.enviados: list[dict] = []

    def send_text_message(self, session_id, to, texto, conversacion_id=None, ia_generado=False):
        self.enviados.append({
            'to': to,
            'texto': texto,
            'conv_id': conversacion_id,
            'ia_generado': bool(ia_generado),
        })
        return {'success': True, 'message_id': f'__test_{len(self.enviados)}'}


def _obtener_sesion_para_usuario(sesion_enc_id: str, user) -> SesionWhatsApp | None:
    try:
        sesion_id = int(get_decrypt(sesion_enc_id)[1])
    except Exception:
        return None
    try:
        qs = SesionWhatsApp.objects.filter(pk=sesion_id, status=True)
        # Si el usuario tiene una sesion asignada o es superuser, concedemos.
        if user.is_superuser:
            return qs.first()
        return qs.filter(usuario=user).first() or qs.first()
    except Exception:
        return None


def _obtener_o_crear_contacto_prueba(sesion: SesionWhatsApp, user) -> Contacto:
    numero = _test_numero(user.id, sesion.id)
    contacto = Contacto.objects.filter(sesion=sesion, from_number=numero).first()
    if contacto:
        return contacto
    # numero_telefono='' fuerza la primera rama del save() (numero_telefono =
    # contacto_numero) y evita que from_number sea reescrito a N@s.whatsapp.net.
    return Contacto.objects.create(
        sesion=sesion,
        from_number=numero,
        contacto_numero=numero,
        contacto_nombre=(user.get_full_name() or user.username or 'Tester'),
        numero_telefono='',
        estado='activo',
    )


def _obtener_o_crear_conversacion_prueba(contacto: Contacto) -> ConversacionWhatsApp:
    conv = (
        ConversacionWhatsApp.objects
        .filter(contacto=contacto, conversacion_finalizada=False)
        .order_by('-id')
        .first()
    )
    if conv:
        return conv
    return ConversacionWhatsApp.objects.create(
        contacto=contacto,
        fecha_hora_expira=timezone.now() + timedelta(hours=2),
        ai_activo=True,
        fromMe=False,
        proveedor_atencion=getattr(contacto.sesion, 'proveedor', '') or '',
    )


def _serializar_estado(estado: EstadoFlujoChatbot | None) -> dict:
    if not estado:
        return {}
    nodo = estado.nodo_actual
    depto = estado.departamento
    variables = dict(estado.variables or {})
    return {
        'departamento': {
            'id': depto.id if depto else None,
            'nombre': getattr(depto, 'nombre', None),
        } if depto else None,
        'nodo_actual': {
            'id': nodo.id if nodo else None,
            'nombre': getattr(nodo, 'nombre', None),
            'tipo': getattr(nodo, 'tipo_nodo', None),
        } if nodo else None,
        'variables': variables,
        'intentos': estado.intentos or 0,
        'finalizado': bool(estado.finalizado),
        'en_handoff': bool(estado.en_handoff),
        # True cuando el motor presentó el meta-menú de departamentos y
        # espera que el siguiente mensaje sea la selección numérica/nombre.
        'esperando_depto': bool(variables.get('__esperando_depto')),
    }


@login_required
def probar_chatbot_view(request, sesion_enc_id):
    sesion = _obtener_sesion_para_usuario(sesion_enc_id, request.user)
    if not sesion:
        return redirect('/crm/departamentos_chatbots/')

    contacto = _obtener_o_crear_contacto_prueba(sesion, request.user)
    conversacion = _obtener_o_crear_conversacion_prueba(contacto)

    # POST actions ─────────────────────────────────────────────────────
    if request.method == 'POST':
        action = request.POST.get('action', 'send')

        if action == 'reset':
            EstadoFlujoChatbot.objects.filter(conversacion=conversacion).delete()
            # Cerrar conversación actual para que el próximo send cree una nueva
            conversacion.conversacion_finalizada = True
            conversacion.save(update_fields=['conversacion_finalizada'])
            log(f"Chat de prueba reseteado — sesion {sesion.id}", request, "change", obj=sesion.id)
            return JsonResponse({'error': False})

        if action == 'send':
            texto = (request.POST.get('mensaje') or '').strip()
            if not texto:
                return JsonResponse({'error': True, 'message': 'Escribe un mensaje antes de enviar.'})

            # Forzar modo tradicional para la prueba aunque la sesión esté en 'ia'.
            modo_original = sesion.modo_bot
            if modo_original not in ('tradicional', 'hibrido'):
                sesion.modo_bot = 'tradicional'

            estado, _ = EstadoFlujoChatbot.objects.get_or_create(conversacion=conversacion)
            if estado.finalizado:
                estado.reset()
                estado.save()

            ws_stub = StubWhatsAppService()
            motor = MotorFlujo(sesion, conversacion, contacto, texto, estado, ws_stub)

            _t0 = time.time()
            error_str = ''
            try:
                motor.ejecutar()
            except Exception as exc:
                logger.exception('Motor dry-run falló sesion=%s: %s', sesion.id, exc)
                error_str = str(exc)
                motor.trace.append({
                    'etapa': 'excepcion',
                    'label': f'Excepción no controlada: {exc.__class__.__name__}',
                    'ok': False,
                    'detalle': {'error': str(exc)[:400]},
                    'ts_ms': int((time.time() - _t0) * 1000),
                })
            latencia_ms = int((time.time() - _t0) * 1000)

            # Restaurar modo_bot original (no persistir cambio accidental)
            if sesion.modo_bot != modo_original:
                sesion.modo_bot = modo_original

            # Refrescar estado desde DB para reflejar guardados del motor
            estado.refresh_from_db()

            return JsonResponse({
                'error': False,
                'respuestas': motor.respuestas,
                'handoff': motor.handoff,
                'finalizado': motor.finalizado,
                'error_motor': error_str,
                'traza': {
                    'latencia_ms': latencia_ms,
                    'nodos_enviados': len(ws_stub.enviados),
                    'estado': _serializar_estado(estado),
                    'timeline': motor.trace,
                    'modo_forzado_tradicional': modo_original not in ('tradicional', 'hibrido'),
                    'modo_original': modo_original,
                },
            })

        return JsonResponse({'error': True, 'message': 'Acción no reconocida.'})

    # GET: render plantilla ────────────────────────────────────────────
    estado = EstadoFlujoChatbot.objects.filter(conversacion=conversacion).first()
    data = {
        'titulo': 'Probar flujo del chatbot',
        'descripcion': f'Sesión: {sesion.nombre or sesion.numero} — dry-run (no envía a WhatsApp)',
        'ruta': request.path,
        'sesion': sesion,
        'departamentos': list(sesion.departamentos.filter(status=True).order_by('id')),
        'departamento_default': sesion.departamento_default,
        'estado_inicial': _serializar_estado(estado),
    }
    addData(request, data)
    return render(request, 'crm/departamento_chatbots/prueba.html', data)
