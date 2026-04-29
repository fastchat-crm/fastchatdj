"""
Demo: llamada telefonica -> IA conversacional.

Flujo:
    Twilio numero -> webhook /voice -> <Stream> WebSocket /ws
    WS recibe audio mu-law 8kHz -> Whisper STT -> Gemini LLM -> TTS -> WS devuelve audio

Requisitos:
    pip install fastapi uvicorn[standard] websockets twilio \
                faster-whisper google-generativeai numpy audioop-lts \
                piper-tts

    Modelo Piper voz espanol (descargar una vez):
        python scripts/descargar_piper_voz.py
        (baja es_MX-ald-medium en media/piper/)

        Ruta modelo via env: PIPER_MODEL=media/piper/es_MX-ald-medium.onnx

    Cuenta Twilio (trial gratis con ~$15 credito):
        - Compra numero en console.twilio.com
        - Configura "A call comes in" -> Webhook -> https://TU_DOMINIO/voice

    Expon tu servidor al publico con ngrok:
        ngrok http 8000
        (pega URL https en Twilio)

    Variables entorno:
        PUBLIC_HOST=xxx.ngrok-free.app  (sin https://)
        IA_APIKEY_ALIAS=<alias de ApiKeyIA a usar>  (opcional, default primero activo Gemini)

    Key LLM: se lee del modelo crm.ApiKeyIA del proyecto (no de env).
             Filtra por proveedor=2 (GEMINI) y estado=True.

Correr desde raiz del proyecto:
    python scripts/demo_voz_ia.py

    (usa DJANGO_SETTINGS_MODULE=fastchatdj.settings automatico)

Integrar al proyecto real:
    Portar VoiceBridge a un AsyncJsonWebsocketConsumer en nueva app voz/
    y reemplazar _pensar() por AgenteConsultor.responder().
"""

import asyncio
import audioop
import base64
import io
import json
import os
import sys
import wave
from pathlib import Path

# --- Bootstrap Django para acceder a ApiKeyIA ---
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fastchatdj.settings")

import django  # noqa: E402

django.setup()

from crm.models import ApiKeyIA  # noqa: E402

import google.generativeai as genai  # noqa: E402
from fastapi import FastAPI, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.responses import Response  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402

try:
    from piper import PiperVoice  # noqa: E402
except ImportError:
    PiperVoice = None
    print("[warn] piper-tts no instalado. TTS caera a Twilio <Say>.")

PROVEEDOR_GEMINI = 2
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "your-ngrok-subdomain.ngrok-free.app")
APIKEY_ALIAS = os.getenv("IA_APIKEY_ALIAS", "").strip()
PIPER_MODEL_PATH = os.getenv("PIPER_MODEL", "media/piper/es_MX-ald-medium.onnx")


def cargar_apikey_gemini() -> tuple[str, str]:
    """Lee key y modelo desde crm.ApiKeyIA. Retorna (key, modelo)."""
    qs = ApiKeyIA.objects.filter(proveedor=PROVEEDOR_GEMINI, estado=True, status=True)
    if APIKEY_ALIAS:
        qs = qs.filter(alias=APIKEY_ALIAS)
    obj = qs.order_by("-id").first()
    if not obj:
        raise RuntimeError(
            "No hay ApiKeyIA Gemini activa. Crea una en /crm/... (proveedor=GEMINI, estado=True)."
        )
    modelo = obj.modelo or "gemini-1.5-flash"
    print(f"[boot] ApiKeyIA cargada alias='{obj.alias}' modelo='{modelo}'")
    return obj.descripcion, modelo

SAMPLE_RATE_TWILIO = 8000
SILENCE_THRESHOLD = 500
SILENCE_DURATION_MS = 800

app = FastAPI()

print("[boot] cargando Whisper modelo small...")
whisper = WhisperModel("small", device="cpu", compute_type="int8")
print("[boot] Whisper listo")

try:
    _key, _modelo = cargar_apikey_gemini()
    genai.configure(api_key=_key)
    llm = genai.GenerativeModel(_modelo)
except Exception as _exc:
    llm = None
    print(f"[warn] No se pudo cargar ApiKeyIA: {_exc} -> IA usara respuesta fija")

piper_voice = None
if PiperVoice is not None and Path(PIPER_MODEL_PATH).exists():
    print(f"[boot] cargando Piper modelo {PIPER_MODEL_PATH}...")
    piper_voice = PiperVoice.load(PIPER_MODEL_PATH)
    print(f"[boot] Piper listo (sample_rate={piper_voice.config.sample_rate}Hz)")
else:
    print(f"[warn] Piper no disponible (modelo '{PIPER_MODEL_PATH}' no existe)")


@app.post("/voice")
async def voice_webhook():
    """Twilio pega aqui cuando llega una llamada. Devolvemos TwiML."""
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="es-MX" voice="Polly.Lupe">Hola, soy tu asistente de inteligencia artificial. En que te puedo ayudar?</Say>
    <Connect>
        <Stream url="wss://{PUBLIC_HOST}/ws" />
    </Connect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


class VoiceBridge:
    """Mantiene estado de una llamada: buffer audio, turnos, stream_sid."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.stream_sid: str | None = None
        self.audio_buffer = bytearray()
        self.silence_ms = 0
        self.speaking = False
        self.historial: list[tuple[str, str]] = []

    async def on_start(self, msg: dict):
        self.stream_sid = msg["start"]["streamSid"]
        print(f"[call] stream iniciado sid={self.stream_sid}")

    async def on_media(self, msg: dict):
        """Twilio envia audio mu-law 8kHz base64 cada 20ms."""
        payload = base64.b64decode(msg["media"]["payload"])
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
                self.audio_buffer.clear()
                self.silence_ms = 0
                self.speaking = False

    async def _procesar_turno(self):
        print(f"[turn] procesando {len(self.audio_buffer)} bytes audio")
        texto = await asyncio.to_thread(self._transcribir, bytes(self.audio_buffer))
        if not texto.strip():
            return
        print(f"[user] {texto}")

        respuesta = await asyncio.to_thread(self._pensar, texto)
        print(f"[ia]   {respuesta}")
        self.historial.append(("user", texto))
        self.historial.append(("ia", respuesta))

        await self._hablar(respuesta)

    def _transcribir(self, pcm_bytes: bytes) -> str:
        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE_TWILIO)
            wf.writeframes(pcm_bytes)
        wav_buf.seek(0)

        segments, _ = whisper.transcribe(wav_buf, language="es", beam_size=1)
        return " ".join(s.text for s in segments).strip()

    def _pensar(self, texto_usuario: str) -> str:
        if llm is None:
            return "Demo sin LLM configurado. Gracias por llamar."

        contexto = "\n".join(
            f"{'Cliente' if rol == 'user' else 'Asistente'}: {t}"
            for rol, t in self.historial[-6:]
        )
        prompt = (
            "Eres asistente telefonico de una empresa. Responde en espanol, "
            "maximo 2 oraciones, natural para ser escuchado por telefono.\n\n"
            f"{contexto}\nCliente: {texto_usuario}\nAsistente:"
        )
        try:
            resp = llm.generate_content(prompt)
            return resp.text.strip()
        except Exception as exc:  # noqa: BLE001
            print(f"[err] LLM fallo: {exc}")
            return "Disculpa, tuve un problema. Puedes repetir?"

    async def _hablar(self, texto: str):
        """Sintetiza con Piper y envia frames mu-law 8kHz al stream Twilio."""
        if piper_voice is None:
            print(f"[tts] Piper no disponible -> diria: {texto}")
            return

        pcm_ulaw = await asyncio.to_thread(self._sintetizar_ulaw, texto)
        if not pcm_ulaw:
            return

        # Twilio espera frames de 20ms = 160 bytes mu-law @ 8kHz
        frame_size = 160
        frame_ms = 0.02
        total_frames = len(pcm_ulaw) // frame_size
        print(f"[tts] enviando {total_frames} frames ({total_frames * 20}ms) ...")

        for i in range(0, len(pcm_ulaw), frame_size):
            chunk = pcm_ulaw[i:i + frame_size]
            if len(chunk) < frame_size:
                chunk = chunk + b"\xff" * (frame_size - len(chunk))  # padding silencio mu-law
            await self.ws.send_json({
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {"payload": base64.b64encode(chunk).decode("ascii")},
            })
            await asyncio.sleep(frame_ms)  # pace al ritmo real de reproduccion

        # mark al final para saber cuando termino en Twilio
        await self.ws.send_json({
            "event": "mark",
            "streamSid": self.stream_sid,
            "mark": {"name": f"fin_respuesta"}
        })

    def _sintetizar_ulaw(self, texto: str) -> bytes:
        """Piper -> PCM int16 -> resample 8kHz -> mu-law."""
        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wf:
            # Piper configura channels/rate/width dentro del wav
            piper_voice.synthesize(texto, wf)
        wav_buf.seek(0)

        with wave.open(wav_buf, "rb") as wf_in:
            src_rate = wf_in.getframerate()
            src_width = wf_in.getsampwidth()
            pcm = wf_in.readframes(wf_in.getnframes())

        if src_width != 2:
            pcm = audioop.lin2lin(pcm, src_width, 2)

        if src_rate != SAMPLE_RATE_TWILIO:
            pcm, _ = audioop.ratecv(pcm, 2, 1, src_rate, SAMPLE_RATE_TWILIO, None)

        return audioop.lin2ulaw(pcm, 2)


@app.websocket("/ws")
async def media_stream(ws: WebSocket):
    await ws.accept()
    bridge = VoiceBridge(ws)
    print("[ws] conexion aceptada")

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            evento = msg.get("event")

            if evento == "connected":
                print("[ws] connected")
            elif evento == "start":
                await bridge.on_start(msg)
            elif evento == "media":
                await bridge.on_media(msg)
            elif evento == "stop":
                print("[ws] stop")
                break
    except WebSocketDisconnect:
        print("[ws] desconectado")


@app.get("/")
def health():
    return {"status": "ok", "public_host": PUBLIC_HOST}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
