"""Consumers WebSocket para voz:
    - VozTwilioConsumer  : protocolo Twilio Media Streams (mu-law 8kHz JSON)
    - VozWebConsumer     : browser directo (PCM 16-bit 16kHz binario)
"""
from __future__ import annotations

import asyncio
import audioop
import base64
import json
import logging

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer, AsyncWebsocketConsumer

from . import services

logger = logging.getLogger(__name__)

SILENCE_THRESHOLD = 500
SILENCE_DURATION_MS = 800
FRAME_SIZE_ULAW = 160  # 20ms @ 8kHz mu-law
FRAME_INTERVAL_SECONDS = 0.02
WEB_SAMPLE_RATE = 16000


class VozTwilioConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.accept()
        self.stream_sid: str | None = None
        self.call_sid: str | None = None
        self.llamada_id: int | None = None
        self.audio_buffer = bytearray()
        self.silence_ms = 0
        self.speaking = False
        self.historial: list[tuple[str, str]] = []
        self.procesando = False
        logger.info('[voz] WS Twilio conectado')

    async def disconnect(self, code):
        logger.info('[voz] WS Twilio cerrado code=%s', code)
        if self.llamada_id:
            await sync_to_async(self._marcar_finalizada)()

    async def receive_json(self, content, **kwargs):
        evento = content.get('event')
        if evento == 'connected':
            return
        if evento == 'start':
            await self._on_start(content)
        elif evento == 'media':
            await self._on_media(content)
        elif evento == 'stop':
            logger.info('[voz] stop recibido')
            await self.close()

    async def _on_start(self, msg: dict):
        start = msg.get('start', {})
        self.stream_sid = start.get('streamSid')
        self.call_sid = start.get('callSid')
        custom = start.get('customParameters') or {}
        numero_origen = custom.get('from') or start.get('from')
        numero_destino = custom.get('to') or start.get('to')

        self.llamada_id = await sync_to_async(self._crear_llamada)(
            self.stream_sid, self.call_sid, numero_origen, numero_destino,
        )
        logger.info('[voz] llamada creada id=%s stream=%s', self.llamada_id, self.stream_sid)

    async def _on_media(self, msg: dict):
        if self.procesando:
            # Ignorar audio entrante mientras hablamos para evitar loop (mejorable con half-duplex real)
            return
        payload = base64.b64decode(msg['media']['payload'])
        pcm = audioop.ulaw2lin(payload, 2)
        self.audio_buffer.extend(pcm)

        amplitud = audioop.rms(pcm, 2)
        if amplitud > SILENCE_THRESHOLD:
            self.silence_ms = 0
            self.speaking = True
        elif self.speaking:
            self.silence_ms += 20
            if self.silence_ms >= SILENCE_DURATION_MS:
                await self._procesar_turno()

    async def _procesar_turno(self):
        if self.procesando:
            return
        self.procesando = True
        audio_chunk = bytes(self.audio_buffer)
        self.audio_buffer.clear()
        self.silence_ms = 0
        self.speaking = False

        try:
            texto = await asyncio.to_thread(services.transcribir_pcm, audio_chunk)
            if not texto.strip():
                return
            logger.info('[voz] cliente: %s', texto)
            self.historial.append(('cliente', texto))
            await sync_to_async(self._guardar_mensaje)('cliente', texto)

            respuesta = await asyncio.to_thread(services.pensar, texto, self.historial)
            logger.info('[voz] ia: %s', respuesta)
            self.historial.append(('ia', respuesta))
            await sync_to_async(self._guardar_mensaje)('ia', respuesta)

            ulaw = await asyncio.to_thread(services.sintetizar_ulaw, respuesta)
            if ulaw:
                await self._enviar_audio(ulaw)
            else:
                logger.warning('[voz] TTS vacio (Piper no cargado)')
        finally:
            self.procesando = False

    async def _enviar_audio(self, ulaw_bytes: bytes):
        total = len(ulaw_bytes) // FRAME_SIZE_ULAW
        logger.info('[voz] enviando %s frames (%sms)', total, total * 20)
        for i in range(0, len(ulaw_bytes), FRAME_SIZE_ULAW):
            chunk = ulaw_bytes[i:i + FRAME_SIZE_ULAW]
            if len(chunk) < FRAME_SIZE_ULAW:
                chunk = chunk + b'\xff' * (FRAME_SIZE_ULAW - len(chunk))
            await self.send_json({
                'event': 'media',
                'streamSid': self.stream_sid,
                'media': {'payload': base64.b64encode(chunk).decode('ascii')},
            })
            await asyncio.sleep(FRAME_INTERVAL_SECONDS)
        await self.send_json({
            'event': 'mark',
            'streamSid': self.stream_sid,
            'mark': {'name': 'fin_respuesta'},
        })

    # --- helpers ORM sincronos ---
    def _crear_llamada(self, stream_sid, call_sid, origen, destino):
        from .models import LlamadaVoz
        ll = LlamadaVoz.objects.create(
            proveedor='twilio',
            stream_sid=stream_sid,
            call_sid=call_sid,
            numero_origen=origen,
            numero_destino=destino,
            estado='en_curso',
        )
        return ll.id

    def _guardar_mensaje(self, rol, texto):
        from .models import MensajeVoz
        MensajeVoz.objects.create(llamada_id=self.llamada_id, rol=rol, texto=texto)

    def _marcar_finalizada(self):
        from django.utils import timezone
        from .models import LlamadaVoz
        LlamadaVoz.objects.filter(id=self.llamada_id).update(
            estado='finalizada', fecha_fin=timezone.now(),
        )


class VozWebConsumer(AsyncWebsocketConsumer):
    """Demo WebRTC browser.

    Protocolo: frames binarios = PCM 16-bit little-endian mono 16kHz crudo.
    Frames texto = JSON control {"event":"start"|"end_utterance"|"stop"}.
    Respuesta: binario PCM 16-bit 16kHz + texto JSON {"event":"transcript"|"reply"|"audio_end"|"vad"}.

    Query string: ?agente_id=<id>  → selecciona AgentesIA; sin esto, cae al
    pipeline generico `services.pensar` (prompt telefonico minimo).
    """

    async def connect(self):
        await self.accept()
        self.llamada_id: int | None = None
        self.audio_buffer = bytearray()
        self.silence_ms = 0
        self.speaking = False
        self.historial: list[tuple[str, str]] = []
        self.procesando = False

        # Leer agente_id de la query string (?agente_id=42).
        self.agente_id: int | None = None
        self.agente_nombre: str = ''
        self._consultor = None  # Lazy: se construye en el primer turno.
        try:
            qs = (self.scope.get('query_string') or b'').decode('utf-8')
            from urllib.parse import parse_qs
            params = parse_qs(qs)
            raw = (params.get('agente_id') or [''])[0].strip()
            if raw.isdigit():
                self.agente_id = int(raw)
                self.agente_nombre = await sync_to_async(self._nombre_agente)(self.agente_id)
        except Exception:
            logger.exception('[voz-web] error parseando agente_id')

        self.llamada_id = await sync_to_async(self._crear_llamada)()
        await self.send(text_data=json.dumps({
            'event': 'ready',
            'sample_rate': WEB_SAMPLE_RATE,
            'llamada_id': self.llamada_id,
            'agente_id': self.agente_id,
            'agente_nombre': self.agente_nombre,
        }))
        logger.info('[voz-web] conectado llamada=%s agente=%s', self.llamada_id, self.agente_id)

    async def disconnect(self, code):
        logger.info('[voz-web] cerrado code=%s', code)
        if self.llamada_id:
            await sync_to_async(self._marcar_finalizada)()

    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data is not None:
            await self._on_pcm(bytes_data)
            return
        if text_data:
            try:
                msg = json.loads(text_data)
            except json.JSONDecodeError:
                return
            evento = msg.get('event')
            if evento == 'end_utterance':
                await self._procesar_turno(forzar=True)
            elif evento == 'stop':
                await self.close()

    async def _on_pcm(self, pcm: bytes):
        if self.procesando:
            return  # half-duplex simple: ignorar mientras hablamos
        self.audio_buffer.extend(pcm)

        amplitud = audioop.rms(pcm, 2) if len(pcm) >= 2 else 0
        # pcm son ~20ms segun AudioWorklet del front (cada 320 samples = 640 bytes @16kHz)
        chunk_ms = (len(pcm) / 2) * 1000 / WEB_SAMPLE_RATE
        if amplitud > SILENCE_THRESHOLD:
            if not self.speaking:
                await self.send(text_data=json.dumps({
                    'event': 'vad', 'speaking': True, 'rms': amplitud,
                }))
            self.silence_ms = 0
            self.speaking = True
        elif self.speaking:
            self.silence_ms += chunk_ms
            if self.silence_ms >= SILENCE_DURATION_MS:
                await self.send(text_data=json.dumps({
                    'event': 'vad', 'speaking': False, 'rms': amplitud,
                }))
                await self._procesar_turno()

    async def _procesar_turno(self, forzar: bool = False):
        if self.procesando:
            return
        if not forzar and not self.speaking:
            return
        self.procesando = True
        audio_chunk = bytes(self.audio_buffer)
        self.audio_buffer.clear()
        self.silence_ms = 0
        self.speaking = False

        try:
            if len(audio_chunk) < WEB_SAMPLE_RATE:  # <0.5s no vale la pena
                return
            texto = await asyncio.to_thread(
                services.transcribir_pcm, audio_chunk, WEB_SAMPLE_RATE,
            )
            if not texto.strip():
                return
            logger.info('[voz-web] cliente: %s', texto)
            self.historial.append(('cliente', texto))
            await sync_to_async(self._guardar_mensaje)('cliente', texto)
            await self.send(text_data=json.dumps({'event': 'transcript', 'texto': texto}))

            if self.agente_id:
                respuesta = await asyncio.to_thread(self._responder_con_agente, texto)
            else:
                respuesta = await asyncio.to_thread(services.pensar, texto, self.historial)
            logger.info('[voz-web] ia: %s', respuesta)
            self.historial.append(('ia', respuesta))
            await sync_to_async(self._guardar_mensaje)('ia', respuesta)
            await self.send(text_data=json.dumps({'event': 'reply', 'texto': respuesta}))

            pcm_tts = await asyncio.to_thread(
                services.sintetizar_pcm, respuesta, WEB_SAMPLE_RATE,
            )
            if pcm_tts:
                # enviar en chunks de ~40ms (1280 bytes) para streaming progresivo
                chunk_bytes = int(WEB_SAMPLE_RATE * 2 * 0.04)
                for i in range(0, len(pcm_tts), chunk_bytes):
                    await self.send(bytes_data=pcm_tts[i:i + chunk_bytes])
            await self.send(text_data=json.dumps({'event': 'audio_end'}))
        finally:
            self.procesando = False

    # --- helpers ORM ---
    def _crear_llamada(self):
        from .models import LlamadaVoz
        return LlamadaVoz.objects.create(proveedor='webrtc', estado='en_curso').id

    def _guardar_mensaje(self, rol, texto):
        from .models import MensajeVoz
        MensajeVoz.objects.create(llamada_id=self.llamada_id, rol=rol, texto=texto)

    def _marcar_finalizada(self):
        from django.utils import timezone
        from .models import LlamadaVoz
        LlamadaVoz.objects.filter(id=self.llamada_id).update(
            estado='finalizada', fecha_fin=timezone.now(),
        )

    def _nombre_agente(self, agente_id: int) -> str:
        from crm.models import AgentesIA
        try:
            return AgentesIA.objects.only('nombre').get(pk=agente_id).nombre
        except AgentesIA.DoesNotExist:
            return ''

    def _responder_con_agente(self, pregunta: str) -> str:
        """Construye AgenteConsultor una sola vez y lo reutiliza entre turnos.
        Si algo falla (sin apikey, sin vectorstore cargable, etc.) cae al
        pipeline generico para no tirar la llamada."""
        try:
            if self._consultor is None:
                self._consultor = self._build_consultor(self.agente_id)
            if self._consultor is None:
                return services.pensar(pregunta, self.historial)
            consultor, agente_descripcion = self._consultor
            resultado = consultor.consultar(pregunta, agente_descripcion)
            return (resultado.respuesta or '').strip() or 'Disculpa, no entendi.'
        except Exception as exc:
            logger.exception('[voz-web] agente fallo, fallback: %s', exc)
            return services.pensar(pregunta, self.historial)

    def _build_consultor(self, agente_id: int):
        """Devuelve (AgenteConsultor, descripcion_agente) o None si no hay apikey."""
        import os
        from types import SimpleNamespace
        from django.conf import settings
        from crm.models import AgentesIA
        from agents_ai.agente_consultor import AgenteConsultor

        agente = (
            AgentesIA.objects
            .select_related('perfil')
            .prefetch_related('apikey')
            .get(pk=agente_id)
        )
        apikey_obj = agente.apikey.filter(status=True, estado=True).order_by('-id').first()
        if not apikey_obj:
            logger.warning('[voz-web] agente %s sin apikey activa', agente_id)
            return None

        vs_path = os.path.join(settings.MEDIA_ROOT, agente.vectorstore_path) if agente.vectorstore_path else None
        vs_enlaces_path = None
        try:
            agente.build_enlaces_vectorstore()
            if agente.vectorstore_enlaces_path:
                vs_enlaces_path = os.path.join(settings.MEDIA_ROOT, agente.vectorstore_enlaces_path)
        except Exception:
            pass

        # Conversacion falsa — la demo no persiste historial estilo WhatsApp,
        # el historial lo llevamos en memoria local a la llamada.
        fake_conv = SimpleNamespace(id=f'voz-{self.llamada_id}', contacto=None)
        consultor = AgenteConsultor(
            vectorstore_path=vs_path,
            vectorstore_enlaces_path=vs_enlaces_path,
            provider=apikey_obj.proveedor,
            apikey=apikey_obj.descripcion,
            model_name=(apikey_obj.modelo or None),
            conversacion=fake_conv,
            prompt_template_text=agente.prompt_template,
            contexto_estatico=agente.contexto_estatico or None,
            perfil=agente.perfil,
            agente=agente,
        )
        return consultor, (agente.descripcion or '')
