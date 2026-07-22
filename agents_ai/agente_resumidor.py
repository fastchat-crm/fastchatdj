import json
import logging
import re
from langchain_core.messages import HumanMessage, AIMessage
from .memoria.historial import DjangoChatMessageHistory
from .providers import get_provider

logger = logging.getLogger(__name__)

_MAX_TOKENS_RESUMEN = 2000


class AgenteResumidor:
    def __init__(self, provider, apikey, model_name=None, conversacion=None,
                 apikey_obj=None, agente_obj=None, base_url=None):
        # Provider: acepta string o int — resuelto por el registry (soporta
        # Gemini, OpenAI, Claude, Ollama, DeepSeek, Huawei MaaS).
        self._provider_obj = get_provider(provider)
        self.provider = self._provider_obj.name
        self.apikey = apikey
        self.apikey_obj = apikey_obj
        self.agente_obj = agente_obj
        self.base_url = (base_url or (getattr(apikey_obj, 'base_url', '') or '')).strip() or None
        modelo_cfg = (getattr(apikey_obj, 'modelo', '') or '').strip() if apikey_obj else ''
        self.model_name = model_name or modelo_cfg or self.default_model()
        self.llm = self._get_llm()
        self.conversacion = conversacion
        self._historia = (
            DjangoChatMessageHistory(session_id=str(conversacion.id))
            if conversacion else None
        )

    def default_model(self) -> str:
        return self._provider_obj.default_model()

    def _resolver_gemini_key(self) -> str:
        """API key Gemini (proveedor 2) activa del perfil, para embeddings cuando
        el provider del agente (Claude/Ollama) no ofrece embeddings propios.
        Replica _resolver_gemini_key de agents_ai/indexador_conocimiento.py."""
        perfil_id = getattr(self.agente_obj, 'perfil_id', None) if self.agente_obj else None
        if not perfil_id:
            return ''
        try:
            from crm.models import ApiKeyIA
            ak = (ApiKeyIA.objects
                  .filter(perfil_id=perfil_id, proveedor=2, estado=True, status=True)
                  .order_by('-id').first())
            return ak.descripcion if ak else ''
        except Exception as exc:
            logger.debug("No se pudo resolver Gemini embed key: %s", exc)
            return ''

    def _get_embeddings(self):
        # Claude/Ollama no proveen embeddings propios (ver providers/claude.py,
        # providers/ollama.py). En ese caso se intenta resolver una API key Gemini
        # activa del perfil del agente; si no hay, degrada devolviendo None sin
        # lanzar (self.embeddings no se usa hoy en resumir()/analizar_sentimiento()).
        try:
            return self._provider_obj.get_embeddings(self.apikey)
        except NotImplementedError:
            gemini_key = self._resolver_gemini_key()
            if not gemini_key:
                return None
            try:
                return get_provider('gemini').get_embeddings(gemini_key)
            except Exception:
                return None

    def _get_llm(self):
        return self._provider_obj.get_llm(
            apikey=self.apikey,
            model_name=self.model_name,
            max_output_tokens=_MAX_TOKENS_RESUMEN,
            temperature=0.2,
            base_url=self.base_url,
        )

    def _get_texto_chat(self) -> str:
        if not self._historia:
            return ""
        messages = self._historia.messages
        lines = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                lines.append(f"Cliente: {msg.content}")
            elif isinstance(msg, AIMessage):
                lines.append(f"Asistente: {msg.content}")
        return "\n".join(lines)

    def resumir(self) -> str:
        texto_chat = self._get_texto_chat()
        if not texto_chat:
            return ""
        prompt = (
            "Resume de forma clara, breve y cronológica la siguiente conversación "
            "entre un cliente y un asistente:\n\n"
            f"{texto_chat}\n\nResumen:"
        )
        resp = self.llm.invoke(prompt)
        self._registrar_consumo(resp, origen='resumidor', prompt_preview='Resumir conversacion')
        return resp.content

    def analizar_sentimiento(self) -> dict:
        """Analiza el tono/sentimiento de la conversación del cliente.

        Returns dict:
            {
              "sentimiento": "positiva" | "neutral" | "tibia" | "pasiva" | "negativa" | "agresiva" | "muy_positiva",
              "puntuacion": 1-10,
              "resumen": "texto extendido incluyendo análisis de tono"
            }
        """
        texto_chat = self._get_texto_chat()
        if not texto_chat:
            return {"sentimiento": "", "puntuacion": None, "resumen": ""}

        prompt = f"""Analiza la siguiente conversación entre un cliente y un asistente de WhatsApp.

CONVERSACIÓN:
{texto_chat}

Responde ÚNICAMENTE con un JSON válido con esta estructura (sin texto adicional antes o después):
{{
  "sentimiento": "<una de: muy_positiva | positiva | neutral | tibia | pasiva | negativa | agresiva>",
  "puntuacion": <número entero del 1 al 10, donde 10=muy positivo, 1=muy agresivo/negativo>,
  "resumen": "<resumen conciso de 2-4 oraciones que incluya: qué consultó el cliente, cómo fue atendido, y cómo fue el tono general de la conversación>"
}}

Criterios de sentimiento:
- muy_positiva: cliente muy satisfecho, agradecido, elogios
- positiva: cliente satisfecho, tono cordial
- neutral: tono informativo, sin carga emocional clara
- tibia: cliente poco comprometido, respuestas monosílabas, poca interacción
- pasiva: cliente que no responde o abandona sin resolver su problema
- negativa: cliente insatisfecho, queja clara pero sin agresividad
- agresiva: cliente frustrado, usa lenguaje fuerte, exige, insulta o presiona"""

        try:
            resp = self.llm.invoke(prompt)
            self._registrar_consumo(resp, origen='sentimiento', prompt_preview='Analisis de sentimiento')
            raw = resp.content.strip()
            # Extraer JSON aunque haya texto envolvente
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                result = json.loads(match.group())
                # Validar claves y tipos
                sentimientos_validos = {'muy_positiva', 'positiva', 'neutral', 'tibia', 'pasiva', 'negativa', 'agresiva'}
                sentimiento = result.get('sentimiento', 'neutral')
                if sentimiento not in sentimientos_validos:
                    sentimiento = 'neutral'
                puntuacion = result.get('puntuacion')
                try:
                    puntuacion = max(1, min(10, int(puntuacion)))
                except (TypeError, ValueError):
                    puntuacion = 5
                return {
                    "sentimiento": sentimiento,
                    "puntuacion": puntuacion,
                    "resumen": result.get('resumen', ''),
                }
        except Exception:
            pass
        return {"sentimiento": "neutral", "puntuacion": 5, "resumen": ""}

    def _registrar_consumo(self, respuesta_llm, origen='resumidor', prompt_preview=''):
        if not self.apikey_obj:
            return
        try:
            from crm.models import ConsumoTokenIA
            from crm.alertas_consumo import verificar_alerta_consumo
            meta = getattr(respuesta_llm, 'response_metadata', {}) or {}
            usage = (
                getattr(respuesta_llm, 'usage_metadata', None)
                or meta.get('usage_metadata')
                or meta.get('token_usage')
                or {}
            )
            tokens_e = usage.get('input_tokens') or usage.get('prompt_token_count') or usage.get('prompt_tokens') or 0
            tokens_s = usage.get('output_tokens') or usage.get('candidates_token_count') or usage.get('completion_tokens') or 0
            if tokens_e or tokens_s:
                ConsumoTokenIA.objects.create(
                    apikey=self.apikey_obj, agente=self.agente_obj,
                    conversacion=self.conversacion,
                    tokens_entrada=tokens_e, tokens_salida=tokens_s,
                    tokens_total=tokens_e + tokens_s,
                    modelo=self.model_name,
                    origen=origen, prompt_preview=(prompt_preview or '')[:300],
                )
                verificar_alerta_consumo(self.apikey_obj, tokens_e + tokens_s)
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Error registrando consumo en AgenteResumidor')
