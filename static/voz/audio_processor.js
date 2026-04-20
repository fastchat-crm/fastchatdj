/**
 * AudioWorkletProcessor: captura audio del micrófono a 16kHz PCM 16-bit.
 *
 * El AudioContext del browser opera a 44100 o 48000 Hz (varia).
 * Nosotros downsampleamos por simple decimación + low-pass implicito del browser.
 * Resultado: Int16Array enviado al main thread vía port.postMessage.
 */
class MicCaptureProcessor extends AudioWorkletProcessor {
    constructor(options) {
        super();
        this.targetRate = (options.processorOptions && options.processorOptions.targetRate) || 16000;
        this.srcRate = sampleRate;  // del AudioContext
        this.ratio = this.srcRate / this.targetRate;
        this.acc = 0;
        this.buffer = [];
    }

    process(inputs) {
        const input = inputs[0];
        if (!input || input.length === 0) return true;
        const ch0 = input[0];
        if (!ch0) return true;

        for (let i = 0; i < ch0.length; i++) {
            this.acc += 1;
            if (this.acc >= this.ratio) {
                this.acc -= this.ratio;
                // Float32 [-1,1] -> Int16
                let s = Math.max(-1, Math.min(1, ch0[i]));
                this.buffer.push(s < 0 ? s * 0x8000 : s * 0x7FFF);
            }
        }

        // Enviar cada ~20ms de audio target (320 samples a 16kHz)
        if (this.buffer.length >= 320) {
            const out = new Int16Array(this.buffer);
            this.buffer = [];
            this.port.postMessage(out.buffer, [out.buffer]);
        }
        return true;
    }
}

registerProcessor('mic-capture', MicCaptureProcessor);
