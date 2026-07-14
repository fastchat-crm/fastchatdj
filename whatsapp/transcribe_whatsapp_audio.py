import os
import sys
import subprocess
import whisper
import webrtcvad
from pydub import AudioSegment

def convert_audio(input_file, output_file="converted.wav"):
    """Convierte archivo .ogg/.opus a .wav mono 16000Hz"""
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", input_file,
            "-ar", "16000", "-ac", "1",
            "-c:a", "pcm_s16le", output_file
        ], check=True)
        return output_file
    except subprocess.CalledProcessError as ex:
        # OJO: nunca sys.exit() acá — esto corre dentro del worker de Daphne,
        # no como script CLI. Un exit mataba el proceso del servidor.
        raise RuntimeError(f'ffmpeg no pudo convertir el audio: {ex}')

def extract_voiced_audio(input_wav, output_wav="voiced.wav", aggressiveness=1):
    """Usa WebRTC VAD para conservar solo voz"""
    audio = AudioSegment.from_wav(input_wav)
    audio = audio.set_channels(1).set_frame_rate(16000)
    vad = webrtcvad.Vad(aggressiveness)  # 0 = conservador, 3 = agresivo

    frame_duration_ms = 30
    frame_size = int(audio.frame_rate * frame_duration_ms / 1000) * 2
    raw = audio.raw_data
    frames = [raw[i:i + frame_size] for i in range(0, len(raw), frame_size)]

    voiced_audio = b"".join(f for f in frames if len(f) == frame_size and vad.is_speech(f, 16000))

    clean = AudioSegment(
        voiced_audio,
        frame_rate=16000,
        sample_width=2,
        channels=1
    )
    clean.export(output_wav, format="wav")
    return output_wav

_MODELOS_WHISPER = {}


def transcribe_audio(wav_file, model_size="base", lang='es'):
    """Transcribe el audio WAV a texto usando Whisper.

    El modelo se cachea en memoria por tamaño: cargarlo (10-60s según tamaño
    y disco) dominaba la latencia de CADA transcripción — con el cache solo
    la primera del proceso paga la carga."""
    model = _MODELOS_WHISPER.get(model_size)
    if model is None:
        model = whisper.load_model(model_size)  # tiny, base, small, medium, large
        _MODELOS_WHISPER[model_size] = model
    result = model.transcribe(wav_file, language=lang)
    return result['text']

def main():
    if len(sys.argv) < 2:
        print("Uso: python transcribe_whatsapp_audio.py archivo.ogg")
        sys.exit(1)

    input_audio = sys.argv[1]
    if not os.path.isfile(input_audio):
        print(f"Archivo no encontrado: {input_audio}")
        sys.exit(1)

    wav_file = convert_audio(input_audio)
    text = transcribe_audio(wav_file)
    print("\nTexto transcrito:")
    print(text)

if __name__ == "__main__":
    main()
