import os
import sys
import subprocess
import whisper

def convert_audio(input_file, output_file="converted.wav"):
    """Convierte archivo .ogg/.opus a .wav mono 16000Hz"""
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", input_file,
            "-ar", "16000", "-ac", "1",
            "-c:a", "pcm_s16le", output_file
        ], check=True)
        return output_file
    except subprocess.CalledProcessError:
        print("Error al convertir el audio.")
        sys.exit(1)

def transcribe_audio(wav_file, model_size="base", lang='es'):
    """Transcribe el audio WAV a texto usando Whisper"""
    print("Cargando modelo Whisper...")
    model = whisper.load_model(model_size)  # tiny, base, small, medium, large
    print("Transcribiendo...")
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
