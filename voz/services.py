"""Pipeline voz: STT (Whisper) -> LLM (Gemini via ApiKeyIA) -> TTS (Piper).

Se carga lazy en la primera llamada para no pegarle al arranque de Django.
Mantiene modelos en memoria (singletons modulares) porque Whisper y Piper
tardan ~2-5s en cargar. Compartirlos entre llamadas es la victoria facil.
"""
from __future__ import annotations

import audioop
import io
import logging
import os
import wave
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SAMPLE_RATE_TELEFONICO = 8000
PROVEEDOR_GEMINI = 2

_whisper = None
_piper = None
_llm = None
_llm_modelo = ''


def _cargar_whisper():
    global _whisper
    if _whisper is not None:
        return _whisper
    from faster_whisper import WhisperModel
    size = os.getenv('VOZ_WHISPER_SIZE', 'small')
    device = os.getenv('VOZ_WHISPER_DEVICE', 'cpu')
    compute = os.getenv('VOZ_WHISPER_COMPUTE', 'int8')
    logger.info('[voz] cargando Whisper %s (%s/%s)', size, device, compute)
    _whisper = WhisperModel(size, device=device, compute_type=compute)
    return _whisper


def _cargar_piper():
    global _piper
    if _piper is not None:
        return _piper
    try:
        from piper import PiperVoice
    except ImportError:
        logger.warning('[voz] piper-tts no instalado')
        return None
    model_path = os.getenv('VOZ_PIPER_MODEL', 'media/piper/es_MX-ald-medium.onnx')
    if not Path(model_path).exists():
        logger.warning('[voz] modelo Piper no existe en %s', model_path)
        return None
    logger.info('[voz] cargando Piper %s', model_path)
    _piper = PiperVoice.load(model_path)
    return _piper


def _cargar_llm():
    global _llm, _llm_modelo
    if _llm is not None:
        return _llm, _llm_modelo
    from crm.models import ApiKeyIA
    import google.generativeai as genai

    alias = os.getenv('VOZ_APIKEY_ALIAS', '').strip()
    qs = ApiKeyIA.objects.filter(proveedor=PROVEEDOR_GEMINI, estado=True, status=True)
    if alias:
        qs = qs.filter(alias=alias)
    obj = qs.order_by('-id').first()
    if obj is None:
        raise RuntimeError('No hay ApiKeyIA Gemini activa (proveedor=2).')

    genai.configure(api_key=obj.descripcion)
    _llm_modelo = obj.modelo or 'gemini-1.5-flash'
    _llm = genai.GenerativeModel(_llm_modelo)
    logger.info('[voz] LLM listo alias=%s modelo=%s', obj.alias, _llm_modelo)
    return _llm, _llm_modelo


def transcribir_pcm(pcm_bytes: bytes, sample_rate: int = SAMPLE_RATE_TELEFONICO) -> str:
    whisper = _cargar_whisper()
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    buf.seek(0)
    segments, _ = whisper.transcribe(buf, language='es', beam_size=1)
    return ' '.join(s.text for s in segments).strip()


def pensar(texto_usuario: str, historial: Optional[list[tuple[str, str]]] = None) -> str:
    """Prompt minimo para llamada telefonica. Historial = lista (rol, texto)."""
    historial = historial or []
    try:
        llm, _ = _cargar_llm()
    except Exception as exc:
        logger.exception('[voz] LLM no disponible: %s', exc)
        return 'Disculpa, no puedo procesar tu consulta ahora. Gracias por llamar.'

    contexto = '\n'.join(
        f"{'Cliente' if rol == 'cliente' else 'Asistente'}: {t}"
        for rol, t in historial[-6:]
    )
    prompt = (
        'Eres asistente telefonico de una empresa. Responde en espanol, '
        'maximo 2 oraciones, natural para ser escuchado por telefono.\n\n'
        f'{contexto}\nCliente: {texto_usuario}\nAsistente:'
    )
    try:
        resp = llm.generate_content(prompt)
        return resp.text.strip()
    except Exception as exc:
        logger.exception('[voz] LLM fallo: %s', exc)
        return 'Disculpa, tuve un problema. Puedes repetir?'


def _piper_a_pcm(texto: str, target_rate: int) -> tuple[bytes, int]:
    """Piper -> PCM 16-bit mono al sample_rate pedido. Retorna (bytes, rate)."""
    piper = _cargar_piper()
    if piper is None:
        return b'', target_rate

    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        piper.synthesize(texto, wf)
    buf.seek(0)

    with wave.open(buf, 'rb') as wf_in:
        src_rate = wf_in.getframerate()
        src_width = wf_in.getsampwidth()
        pcm = wf_in.readframes(wf_in.getnframes())

    if src_width != 2:
        pcm = audioop.lin2lin(pcm, src_width, 2)
    if src_rate != target_rate:
        pcm, _ = audioop.ratecv(pcm, 2, 1, src_rate, target_rate, None)
    return pcm, target_rate


def sintetizar_ulaw(texto: str) -> bytes:
    """Sintetiza texto a mu-law 8kHz (formato Twilio)."""
    pcm, _ = _piper_a_pcm(texto, SAMPLE_RATE_TELEFONICO)
    if not pcm:
        return b''
    return audioop.lin2ulaw(pcm, 2)


def sintetizar_pcm(texto: str, sample_rate: int = 16000) -> bytes:
    """Sintetiza texto a PCM 16-bit mono al sample_rate pedido (para browser)."""
    pcm, _ = _piper_a_pcm(texto, sample_rate)
    return pcm
