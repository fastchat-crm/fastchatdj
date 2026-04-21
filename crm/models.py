import json
import os
from datetime import timedelta
from decimal import Decimal

import requests
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

from core.constantes import PROMPT_TEMPLATES
from core.custom_models import ModeloBase
from autenticacion.models import Usuario
from core.validadores import FileMaxSizeInMbValidator
from whatsapp.models import ConversacionWhatsApp
from fastchatdj import settings
from agents_ai.vectorstore_manager import VectorStoreManager
from agents_ai.providers import MODELOS_DISPONIBLES

# Representa las industrias generales a las que puede pertenecer un negocio
class Industria(ModeloBase):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nombre

    class Meta:
        verbose_name = 'Industria'
        verbose_name_plural = 'Industrias'


# Permite especificar con más detalle a qué se dedica una empresa dentro de una industria
class ActividadEconomica(ModeloBase):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = 'Actividad Económica'
        verbose_name_plural = 'Actividades Económicas'

    def __str__(self):
        return f"{self.nombre}"


# Etapas de venta configurables por industria (embudo personalizado)
class EtapaVenta(ModeloBase):
    nombre = models.CharField(max_length=100)
    orden = models.PositiveSmallIntegerField(default=0)
    industria = models.ForeignKey(Industria, on_delete=models.CASCADE, related_name='etapas')
    duracion_estimada = models.PositiveIntegerField(help_text="Duración estimada en días", default=1)
    descripcion = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['orden']
        verbose_name = 'Etapa de venta'
        verbose_name_plural = 'Etapas de venta'

    def __str__(self):
        return f"{self.nombre} - {self.industria}"


# Perfil de IA para el usuario autenticado (asesor/cliente)
class PerfilNegocioIA(ModeloBase):
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='perfil_ia')
    industria = models.ForeignKey(Industria, on_delete=models.SET_NULL, null=True, blank=True)
    actividad = models.ForeignKey(ActividadEconomica, on_delete=models.SET_NULL, null=True, blank=True)
    nombre_empresa = models.CharField(max_length=200, blank=True, null=True)
    descripcion_empresa = models.TextField(blank=True, null=True)
    sitio_web = models.URLField(blank=True, null=True)
    localidad = models.CharField(max_length=100, blank=True, null=True)
    publico_objetivo = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Perfil de Negocio IA"
        verbose_name_plural = "Perfiles de Negocio IA"

    def __str__(self):
        return f"{self.usuario.get_full_name()} - {self.industria.nombre if self.industria else 'Sin industria'}"

    # MÉTODOS ÚTILES

    def tiene_datos_basicos(self):
        if self.get_agentes():
            return True
        else:
            return False
        # return all([self.nombre_empresa, self.descripcion_empresa, self.industria, self.actividad])

    def resumen_contexto_ia(self):
        productos = self.productos.all()
        servicios = self.servicios.all()
        lista_productos = ", ".join([f"{p.nombre} (${p.precio})" for p in productos]) or "N/A"
        lista_servicios = ", ".join([f"{s.nombre}" for s in servicios]) or "N/A"

        return f"""Empresa: {self.nombre_empresa or 'No definido'}
            Industria: {self.industria.nombre if self.industria else 'No definida'}
            Actividad económica: {self.actividad.nombre if self.actividad else 'No definida'}
            Ubicación: {self.localidad or 'No definida'}
            Descripción: {self.descripcion_empresa or 'No definida'}
            Público objetivo: {self.publico_objetivo or 'No definido'}
            Productos ofrecidos: {lista_productos}
            Servicios ofrecidos: {lista_servicios}
            """.strip()

    def total_productos(self):
        return self.productos.count()

    def total_servicios(self):
        return self.servicios.count()

    def get_productos(self):
        return self.productos.filter(status=True).order_by('-id')

    def get_servicios(self):
        return self.servicios.filter(status=True).order_by('-id')

    def get_respuestas(self):
        return self.respuestas_ia.filter(status=True).order_by('-id')

    def get_agentes(self):
        return self.agentesia_set.filter(status=True).order_by('nombre')

    def get_apis(self):
        return self.apikeyia_set.filter(status=True).order_by('-id')

# Productos personalizados del perfil IA
class ProductoIA(ModeloBase):
    perfil = models.ForeignKey(PerfilNegocioIA, on_delete=models.CASCADE, related_name='productos')
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True, null=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "Producto IA"
        verbose_name_plural = "Productos IA"

    def __str__(self):
        return f"{self.nombre} - ${self.precio}"


# Servicios personalizados del perfil IA
class ServicioIA(ModeloBase):
    perfil = models.ForeignKey(PerfilNegocioIA, on_delete=models.CASCADE, related_name='servicios')
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True, null=True)
    precio_referencial = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "Servicio IA"
        verbose_name_plural = "Servicios IA"

    def __str__(self):
        return f"{self.nombre} - ${self.precio_referencial or 0}"


# Preguntas y respuestas predefinidas para que la IA sepa cómo responder ante ciertos temas o comportamientos definidos por el usuario
class RespuestaEntrenadaIA(ModeloBase):
    perfil = models.ForeignKey(PerfilNegocioIA, on_delete=models.CASCADE, related_name='respuestas_ia')
    pregunta_clave = models.CharField(max_length=255, help_text="Palabra o frase que activa esta respuesta")
    respuesta_configurada = models.TextField(help_text="Respuesta sugerida por el usuario")
    tono = models.CharField(max_length=100, choices=[
        ('formal', 'Formal'),
        ('informal', 'Informal'),
        ('empatico', 'Empático'),
        ('directo', 'Directo'),
        ('humilde', 'Humilde'),
        ('seguro', 'Seguro'),
    ], default='formal', help_text="Tono sugerido para esta respuesta")

    class Meta:
        verbose_name = 'Respuesta Entrenada IA'
        verbose_name_plural = 'Respuestas Entrenadas IA'

    def __str__(self):
        return f"{self.pregunta_clave} → {self.tono}"


class AgentesIA(ModeloBase):
    perfil = models.ForeignKey(PerfilNegocioIA, on_delete=models.CASCADE, blank=True, null=True, verbose_name='Perfil Negocio IA')
    apikey = models.ManyToManyField('ApiKeyIA', blank=True, verbose_name='Api Keys IA')
    nombre = models.CharField(max_length=255, verbose_name="Nombre de agente")
    descripcion = models.TextField(verbose_name="Descripcion del agente")
    vectorstore_path = models.CharField(
        max_length=1000, blank=True, null=True, verbose_name="Ruta del vector store generado"
    )
    prompt_template = models.TextField(verbose_name="Promp Template", default=PROMPT_TEMPLATES.get('es') or '')
    anotar_listas = models.BooleanField(
        default=False, verbose_name="Anotar listas de productos/servicios en memoria",
        help_text="Si se activa, el agente guardará las listas de productos/servicios en la memoria"
    )
    faqs_en_prompt = models.PositiveSmallIntegerField(
        default=5, verbose_name='Cantidad de FAQs en prompt',
        help_text='Top N FAQs aprobadas (por prioridad) inyectadas literal en el prompt. '
                  'Las demás quedan disponibles vía RAG.'
    )
    vectorstore_enlaces_path = models.CharField(
        max_length=1000, blank=True, null=True, verbose_name="Ruta del vector store de Apis y Enlaces"
    )
    vectorstore_enlaces_expira = models.DateTimeField(blank=True, null=True, verbose_name="Fecha de expiración del vector store")
    # Texto completo extraído de archivos/textos — se inyecta directamente en el prompt
    # sin llamadas de embedding. Ideal para documentos pequeños (menús, FAQ, etc.)
    contexto_estatico = models.TextField(
        blank=True, null=True,
        verbose_name="Contexto estático (texto completo para inyección directa en prompt)"
    )

    # ── Configuración avanzada de comportamiento IA (override por agente) ────
    cfg_faiss_k = models.PositiveSmallIntegerField(
        default=5, verbose_name='Fragmentos relevantes por respuesta',
        help_text='Cuántos pedacitos del entrenamiento (PDF/CSV/etc.) le pasamos al bot por cada pregunta. '
                  'Más = más contexto pero respuestas más lentas y caras. Rango: 3–10. Default: 5.'
    )
    cfg_faiss_fetch_k = models.PositiveSmallIntegerField(
        default=20, verbose_name='Candidatos antes de elegir',
        help_text='Cuántos fragmentos consideramos antes de quedarnos con los mejores. '
                  'Mayor = selección de mejor calidad pero un poco más lenta. Rango: 10–40. Default: 20.'
    )
    cfg_max_context_chars = models.PositiveIntegerField(
        default=4000, verbose_name='Máx caracteres de contexto del entrenamiento',
        help_text='Tope total de información del entrenamiento que cabe en una respuesta. '
                  'Si el bot da respuestas cortadas/incompletas, subilo. Rango: 2000–8000. Default: 4000.'
    )
    cfg_max_static_chars = models.PositiveIntegerField(
        default=1200, verbose_name='Máx caracteres del texto fijo (cuando complementa)',
        help_text='Cuando hay entrenamiento Y texto fijo (FAQ/menú), cuánto texto fijo se incluye. '
                  'Rango: 800–5000. Default: 1200.'
    )
    cfg_history_turns = models.PositiveSmallIntegerField(
        default=5, verbose_name='Mensajes previos que recuerda',
        help_text='Cuántos turnos de conversación recuerda el bot (1 turno = 1 mensaje del cliente + 1 respuesta). '
                  'Subilo si el bot olvida pedidos en conversaciones largas. Rango: 3–20. Default: 5.'
    )
    cfg_user_snippet = models.PositiveSmallIntegerField(
        default=150, verbose_name='Máx caracteres por mensaje del cliente recordado',
        help_text='Si el cliente escribe un mensaje muy largo, lo truncamos a esta cantidad para no gastar tokens. '
                  'Rango: 100–600. Default: 150.'
    )
    cfg_ai_snippet = models.PositiveSmallIntegerField(
        default=400, verbose_name='Máx caracteres por respuesta del bot recordada',
        help_text='Crítico cuando el bot envía menús/listas largas. Si está muy bajo, el bot olvida lo que ya mostró '
                  'y se contradice. Rango: 300–2000. Default: 400.'
    )
    cfg_max_output_tokens = models.PositiveIntegerField(
        default=3000, verbose_name='Máx longitud de la respuesta del bot',
        help_text='Límite de tokens (≈palabras) que el bot puede generar en una sola respuesta. '
                  'Si las respuestas se cortan a la mitad, subilo. Rango: 500–4000. Default: 3000.'
    )
    cfg_topic_anchor_chars = models.PositiveSmallIntegerField(
        default=180, verbose_name='Chars del tema inicial conservado',
        help_text='Cuando la conversación se hace larga, se conserva el primer mensaje sustantivo del cliente '
                  'como "ancla" para mantener el bot enfocado en el tema original. Rango: 100–400. Default: 180.'
    )

    # ── Persona del bot (humanización) ─────────────────────────────────────
    nombre_bot = models.CharField(
        max_length=80, default='Asistente', verbose_name='Nombre del bot',
        help_text='Nombre con el que se presenta el bot. Ej: "Cami", "Mateo", "Sofía".'
    )
    personalidad = models.TextField(
        blank=True, default='', verbose_name='Personalidad',
        help_text='Rasgos humanos del bot. Ej: "Soy Cami, 28 años, extrovertida, uso emojis con mesura, '
                  'soy paciente con clientes nuevos".'
    )
    TONO_CHOICES = (
        ('cercano', 'Cercano'),
        ('formal', 'Formal'),
        ('amigable', 'Amigable'),
        ('vendedor', 'Vendedor'),
        ('profesional', 'Profesional'),
    )
    tono = models.CharField(
        max_length=20, choices=TONO_CHOICES, default='amigable', verbose_name='Tono',
        help_text='Registro general del bot al escribir.'
    )
    estilo_escritura = models.TextField(
        blank=True, default='', verbose_name='Estilo de escritura',
        help_text='Indicaciones de forma. Ej: "mensajes cortos, 2-3 líneas, admite muletillas (dale, mm), '
                  'no abrir signos de interrogación, emojis 0-2 por mensaje".'
    )
    temperature = models.DecimalField(
        max_digits=3, decimal_places=2, default=Decimal('0.60'),
        verbose_name='Temperatura (creatividad)',
        help_text='0.0 = literal/robótico, 1.0 = creativo/variado. 0.6 da variación natural sin inventar datos.'
    )
    humanizar_timing = models.BooleanField(
        default=True, verbose_name='Humanizar timing y burbujas',
        help_text='Si está activo, la respuesta se divide en varias burbujas con delays de lectura y escritura '
                  'proporcionales (típeo humano). Desactivalo para un envío único e instantáneo.'
    )
    # ── Parámetros finos de humanización (solo aplican si humanizar_timing=True) ──
    humaniz_chars_burbuja_ideal = models.PositiveSmallIntegerField(
        default=180, verbose_name='Chars ideales por burbuja',
        help_text='Tamaño objetivo de cada burbuja. Al superar este valor, el splitter intenta cerrar burbuja. '
                  'Rango recomendado: 120–240. Default: 180.'
    )
    humaniz_chars_burbuja_max = models.PositiveSmallIntegerField(
        default=320, verbose_name='Chars máximos por burbuja',
        help_text='Tope duro por burbuja. Si agregar una oración excede esto, se cierra burbuja obligado. '
                  'Rango recomendado: 240–500. Default: 320.'
    )
    humaniz_max_burbujas = models.PositiveSmallIntegerField(
        default=4, verbose_name='Máximo de burbujas',
        help_text='Cuántas burbujas como mucho puede mandar el bot por respuesta. '
                  'Rango recomendado: 2–6. Default: 4.'
    )
    humaniz_lectura_cps = models.PositiveSmallIntegerField(
        default=70, verbose_name='Chars/seg al leer',
        help_text='Velocidad de lectura simulada antes de responder. Más alto = pausa más corta antes de escribir. '
                  'Rango recomendado: 50–120. Default: 70.'
    )
    humaniz_escritura_cps = models.PositiveSmallIntegerField(
        default=25, verbose_name='Chars/seg al escribir',
        help_text='Velocidad de tipeo simulada. Más bajo = se siente más humano/lento. '
                  'Rango recomendado: 15–40. Default: 25.'
    )
    humaniz_lectura_max_seg = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal('2.50'),
        verbose_name='Máx segundos de lectura',
        help_text='Tope de pausa de "lectura" entre burbujas. Evita esperas eternas con textos largos. '
                  'Rango recomendado: 1.5–5.0. Default: 2.5.'
    )
    humaniz_escritura_min_seg = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal('0.60'),
        verbose_name='Mín segundos de escritura',
        help_text='Piso de "tipeo" por burbuja. Evita envíos instantáneos en burbujas muy cortas. '
                  'Rango recomendado: 0.3–1.5. Default: 0.6.'
    )
    humaniz_escritura_max_seg = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal('6.00'),
        verbose_name='Máx segundos de escritura',
        help_text='Tope de "tipeo" por burbuja para que ningún mensaje tarde eternidades. '
                  'Rango recomendado: 4–12. Default: 6.0.'
    )

    class Meta:
        verbose_name = 'Respuesta Entrenada IA'
        verbose_name_plural = 'Respuestas Entrenadas IA'

    def requiere_tools(self) -> bool:
        """True si el agente necesita el loop tool-calling del consultor.

        Se activa cuando tiene `anotar_listas=True` (pedidos en memoria) o
        tiene al menos una HerramientaAgente activa configurada.
        """
        if self.anotar_listas:
            return True
        try:
            return self.herramientas.filter(activo=True, status=True).exists()
        except Exception:
            return False

    def obtener_detalles_agente(self):
        """
        Función para obtener los detalles existentes de un agente
        """
        detalles = self.detalleagentesai_set.filter(status=True).order_by('id')
        detalles_json = []

        # Debug: imprimir cuántos detalles se encontraron
        print(f"DEBUG: Agente {self.id} tiene {detalles.count()} detalles activos")

        for detalle in detalles:
            detalle_data = {
                'id': detalle.id,
                'tipo': detalle.tipo,
                'enlace': detalle.enlace or '',
                'tipo_dato_enlace': detalle.tipo_dato_enlace,
                'archivo_url': detalle.archivo.url if detalle.archivo else '',
                'descripcion': detalle.descripcion if detalle.descripcion else '',
                'requiere_token': detalle.requiere_token,
                'token_autorizacion': detalle.token_autorizacion or '',
                'usar_cache': detalle.usar_cache,
                'tiempo_cache_horas': detalle.tiempo_cache_horas
            }
            detalles_json.append(detalle_data)

        print(f"DEBUG: JSON generado con {len(detalles_json)} detalles")
        return json.dumps(detalles_json)

    def fetch_contexto_apis(self, forzar_refresco: bool = False) -> str:
        """
        Descarga todas las fuentes tipo=1 (enlaces API) y devuelve su
        contenido formateado como texto plano listo para inyectar al prompt.

        Sin embeddings, sin FAISS — solo HTTP + cache en memoria Django.
        Respeta `usar_cache` y `tiempo_cache_horas` de cada fuente.

        El texto incluye la "observación" de cada fuente como prefijo
        [FUENTE ... — CUÁNDO USAR: ...], para que el LLM sepa en qué
        momento le conviene mirar esa data.
        """
        from django.core.cache import cache

        detalles = self.detalleagentesai_set.filter(status=True, tipo=1, enlace__isnull=False)
        if not detalles.exists():
            return ''

        def _money_map_to_str(m):
            if not m:
                return ''
            try:
                items = sorted(m.items(), key=lambda kv: int(kv[0]))
            except Exception:
                items = list(m.items())
            return ', '.join(f'{k}: {v}' for k, v in items if v is not None and str(v).strip() != '')

        def _json_to_text(obj, nivel=0) -> str:
            indent = '  ' * nivel
            if isinstance(obj, list):
                return '\n\n'.join(f'{indent}[{i + 1}]\n{_json_to_text(it, nivel + 1)}'
                                   for i, it in enumerate(obj))
            if isinstance(obj, dict):
                out = []
                for k, v in obj.items():
                    if v is None or str(v).strip() == '':
                        continue
                    if isinstance(v, (dict, list)):
                        sub = _json_to_text(v, nivel + 1)
                        if sub.strip():
                            out.append(f'{indent}{k}:\n{sub}')
                    else:
                        out.append(f'{indent}{k}: {v}')
                return '\n'.join(out)
            return f'{indent}{obj}'

        bloques = []
        for d in detalles:
            cache_key = f'agente_api_{self.id}_detalle_{d.id}'
            texto = None
            if d.usar_cache and not forzar_refresco:
                texto = cache.get(cache_key)

            if texto is None:
                try:
                    headers = {'Accept': 'application/json, text/plain, */*'}
                    if d.requiere_token and d.token_autorizacion:
                        headers['Authorization'] = f'Bearer {d.token_autorizacion}'
                    resp = requests.get(d.enlace, headers=headers, timeout=30)
                    if resp.status_code != 200:
                        texto = f'[ERROR HTTP {resp.status_code} al consultar {d.enlace}]'
                    else:
                        tipo_dato = d.tipo_dato_enlace  # 1=TEXT, 2=HTML, 3=JSON, 4=EXCEL, 5=CSV
                        if tipo_dato == 2:
                            try:
                                from bs4 import BeautifulSoup
                                texto = BeautifulSoup(resp.text, 'html.parser').get_text(separator='\n', strip=True)
                            except Exception:
                                texto = resp.text
                        elif tipo_dato == 3:
                            try:
                                data = resp.json()
                            except Exception as je:
                                texto = f'[JSON inválido: {je}]\n{resp.text[:2000]}'
                                data = None
                            if data is not None:
                                if isinstance(data, dict) and data.get('listCatalogo'):
                                    lineas = []
                                    for c in data['listCatalogo']:
                                        precio = (c.get('precio') or {}).get('real') or ''
                                        carnada = (c.get('precio') or {}).get('carnada') or ''
                                        horas = (c.get('horas') or {}).get('total') or ''
                                        lineas.append(
                                            f"— {c.get('nombre') or '(sin nombre)'} "
                                            f"| Categoría: {(c.get('categoria') or {}).get('descripcion') or '—'} "
                                            f"| Unidad: {c.get('unidad_negocio') or '—'} "
                                            f"| Precio: ${precio or '—'}"
                                            + (f" (antes ${carnada})" if carnada and carnada != precio else '')
                                            + (f" | {horas}h" if horas else '')
                                            + (f" | Activo: {c.get('activo')}" if c.get('activo') is not None else '')
                                            + (f" | Fechas: {c.get('fechainicio') or '—'} a {c.get('fechafin') or '—'}"
                                               if c.get('fechainicio') or c.get('fechafin') else '')
                                            + (f"\n   Descripción: {(c.get('descripcion') or '')[:500]}"
                                               if c.get('descripcion') else '')
                                        )
                                    texto = f"Total: {len(data['listCatalogo'])} items.\n" + '\n'.join(lineas)
                                elif isinstance(data, dict) and data.get('data'):
                                    lineas = []
                                    for it in data['data']:
                                        costos = it.get('costos', {}) or {}
                                        lineas.append(
                                            f"— {it.get('nombre') or '(sin nombre)'} "
                                            f"| Periodo: {it.get('periodo') or '—'} "
                                            f"| Cupo: {it.get('tiene_cupo')} "
                                            f"| Fechas: {it.get('fechainicio') or '—'} a {it.get('fechafin') or '—'}"
                                            + (f"\n   Inscripción: {_money_map_to_str(costos.get('inscripcion')) or 'N/D'}"
                                               f"; Matrícula: {_money_map_to_str(costos.get('matricula')) or 'N/D'}")
                                            + (f"\n   Requisitos: {(it.get('requisitos') or '')[:300]}"
                                               if it.get('requisitos') else '')
                                        )
                                    texto = f"Total: {len(data['data'])} items.\n" + '\n'.join(lineas)
                                else:
                                    texto = _json_to_text(data)
                        else:
                            texto = resp.text

                    if d.usar_cache and d.tiempo_cache_horas:
                        cache.set(cache_key, texto, timeout=d.tiempo_cache_horas * 3600)
                    elif d.usar_cache:
                        cache.set(cache_key, texto, timeout=600)  # 10 min por default

                except requests.Timeout:
                    texto = f'[Timeout (30s) consultando {d.enlace}]'
                except Exception as e:
                    texto = f'[Error consultando {d.enlace}: {e}]'

            observacion = (d.descripcion or '').strip()
            tipo_nombre = d.get_tipo_dato_enlace_display() if hasattr(d, 'get_tipo_dato_enlace_display') else 'datos'
            encabezado = f'## FUENTE API: {tipo_nombre}'
            if observacion:
                encabezado += f'\n## CUÁNDO USARLA: {observacion}'
            bloques.append(f'{encabezado}\n{texto or "(sin contenido)"}\n## fin fuente ##')

        return '\n\n'.join(bloques)

    def build_enlaces_vectorstore(self):
        detalles = self.detalleagentesai_set.filter(status=True, tipo=1, enlace__isnull=False)
        if not detalles.exists():
            return
        tiempo_cache_horas = detalles.filter(usar_cache=True).order_by('-tiempo_cache_horas').first()
        tiempo_cache_horas = tiempo_cache_horas and tiempo_cache_horas.tiempo_cache_horas or 0
        base_dir = os.path.join(settings.MEDIA_ROOT, 'vectorstores')
        nombre_vs = f"agente_api_{self.id}"
        apikeys = self.apikey.all()
        if not apikeys.exists():
            return
        if self.vectorstore_enlaces_expira and self.vectorstore_enlaces_expira > timezone.now():
            return

        agente = self
        agente.vectorstore_enlaces_path = None

        def _money_map_to_str(m):
            if not m:
                return ""
            try:
                items = sorted(m.items(), key=lambda kv: int(kv[0]))
            except Exception:
                items = list(m.items())
            return ", ".join(f"{k}: {v}" for k, v in items if v is not None and str(v).strip() != "")

        def _json_to_text(obj, nivel=0) -> str:
            """Convierte recursivamente cualquier JSON en texto legible para FAISS."""
            indent = "  " * nivel
            if isinstance(obj, list):
                partes = []
                for i, item in enumerate(obj):
                    partes.append(f"{indent}[{i + 1}]\n{_json_to_text(item, nivel + 1)}")
                return "\n\n".join(partes)
            elif isinstance(obj, dict):
                lineas = []
                for k, v in obj.items():
                    if v is None or str(v).strip() == "":
                        continue
                    if isinstance(v, (dict, list)):
                        sub = _json_to_text(v, nivel + 1)
                        if sub.strip():
                            lineas.append(f"{indent}{k}:\n{sub}")
                    else:
                        lineas.append(f"{indent}{k}: {v}")
                return "\n".join(lineas)
            else:
                return f"{indent}{obj}"

        last_error = None
        for apikeyobj in apikeys:
            if not apikeyobj.descripcion:
                continue
            vs_manager = VectorStoreManager(
                storage_dir=base_dir,
                provider=apikeyobj.proveedor,  # int — el provider registry lo resuelve
                apikey=apikeyobj.descripcion
            )
            documentos = []
            for detalle in detalles:
                try:
                    headers = {}
                    if detalle.requiere_token and detalle.token_autorizacion:
                        headers['Authorization'] = f'Bearer {detalle.token_autorizacion}'

                    resp = requests.get(detalle.enlace, headers=headers, timeout=30)
                    if resp.status_code != 200:
                        print(f"[build_enlaces] {detalle.enlace} → HTTP {resp.status_code}: {resp.text[:200]}")
                        continue

                    descripcion_detalle = (detalle.descripcion or '').strip()
                    # Prefijo "cuándo usar" — lo ve el LLM en cada chunk recuperado
                    # Así el agente sabe en qué contexto disparar esta fuente.
                    def _prefix(tipo_registro: str) -> str:
                        if not descripcion_detalle:
                            return ''
                        return f"[FUENTE: {tipo_registro} — CUÁNDO USAR: {descripcion_detalle}]\n"

                    tipo_dato = detalle.tipo_dato_enlace  # 1=TEXT, 2=HTML, 3=JSON, 4=EXCEL, 5=CSV

                    # ── TEXT o HTML ──────────────────────────────────────────
                    if tipo_dato in (1, 2):
                        texto = resp.text
                        if tipo_dato == 2:
                            try:
                                from bs4 import BeautifulSoup
                                soup = BeautifulSoup(texto, 'html.parser')
                                texto = soup.get_text(separator='\n', strip=True)
                            except Exception:
                                pass
                        texto = _prefix('texto') + texto
                        docs = vs_manager.build_from_string(texto, metadata={"tipo": "texto", "detalle_id": detalle.id, "observacion": descripcion_detalle})
                        documentos.extend(docs)
                        continue

                    # ── JSON ─────────────────────────────────────────────────
                    data = resp.json()

                    # Estructura conocida: listCatalogo
                    if isinstance(data, dict) and data.get("listCatalogo"):
                        for c in data["listCatalogo"]:
                            page_content = (
                                f"{_prefix('catálogo de cursos')}"
                                f"Curso: {c.get('nombre') or ''}\n"
                                f"Categoría: {(c.get('categoria') or {}).get('descripcion') or ''}\n"
                                f"Unidad de negocio: {c.get('unidad_negocio') or ''}\n"
                                f"Descripción: {c.get('descripcion') or ''}\n"
                                f"Precio total (USD): {(c.get('precio') or {}).get('real') or ''}\n"
                                f"Fechas: {c.get('fechainicio') or ''} a {c.get('fechafin') or ''}\n"
                                f"Horas: {(c.get('horas') or {}).get('total') or ''}\n"
                                f"Activo: {c.get('activo')}\n"
                            )
                            metadata = {
                                "tipo": "listCatalogo", "detalle_id": detalle.id,
                                "id": c.get("id"), "slug": c.get("slug"),
                                "observacion": descripcion_detalle,
                            }
                            docs = vs_manager.build_from_string(page_content, metadata=metadata)
                            documentos.extend(docs)

                    # Estructura conocida: data (oferta por periodo)
                    elif isinstance(data, dict) and data.get("data"):
                        for item in data["data"]:
                            costos = item.get("costos", {}) or {}
                            page_content = (
                                f"{_prefix('oferta por periodo')}"
                                f"Curso: {item.get('nombre') or ''}\n"
                                f"Periodo: {item.get('periodo') or ''}\n"
                                f"Centro de costo: {item.get('centro_costo') or ''}\n"
                                f"Fechas: {item.get('fechainicio') or ''} a {item.get('fechafin') or ''}\n"
                                f"Cupos disponibles: {item.get('tiene_cupo')}\n"
                                f"Requisitos: {(item.get('requisitos') or '').strip()}\n"
                                f"Descripción: {(item.get('descripcion') or '').strip()}\n"
                                f"Costos - Inscripción: {_money_map_to_str(costos.get('inscripcion')) or 'N/D'}\n"
                                f"Costos - Matrícula: {_money_map_to_str(costos.get('matricula')) or 'N/D'}\n"
                                f"Contexto: {(item.get('contexto') or '').strip()}\n"
                            )
                            metadata = {
                                "tipo": "oferta_periodo", "detalle_id": detalle.id,
                                "id": item.get("id"), "nombre": item.get("nombre"),
                                "observacion": descripcion_detalle,
                            }
                            docs = vs_manager.build_from_string(page_content, metadata=metadata)
                            documentos.extend(docs)

                    # ── GENÉRICO: cualquier otra estructura JSON ──────────────
                    else:
                        texto = _json_to_text(data)
                        texto = _prefix('json') + texto
                        docs = vs_manager.build_from_string(texto, metadata={"tipo": "json_generico", "detalle_id": detalle.id, "observacion": descripcion_detalle})
                        documentos.extend(docs)

                except Exception as e:
                    import traceback
                    print(f"[build_enlaces] Error procesando {detalle.enlace}: {e}\n{traceback.format_exc()}")
                    continue

            if documentos:
                try:
                    vs_path = vs_manager.build_and_save(documentos, nombre_vs)
                except Exception as emb_err:
                    # Error típico: embedding con API key inválida.
                    last_error = emb_err
                    err_msg = str(emb_err)
                    if 'API key not valid' in err_msg or 'API_KEY_INVALID' in err_msg or 'invalid_api_key' in err_msg.lower():
                        # Marcar esta key como inactiva para no reintentarla
                        try:
                            apikeyobj.estado = False
                            apikeyobj.msgerror = f'Inválida al generar embeddings: {err_msg[:400]}'
                            apikeyobj.save(update_fields=['estado', 'msgerror'])
                            print(f"[build_enlaces] API Key #{apikeyobj.id} marcada inactiva por embedding inválido")
                        except Exception:
                            pass
                        continue  # intentar con la siguiente apikey
                    # Otro error inesperado — propagar
                    raise
                agente.vectorstore_enlaces_path = os.path.relpath(vs_path, settings.MEDIA_ROOT)
                agente.vectorstore_enlaces_expira = timezone.now() + timedelta(
                    hours=tiempo_cache_horas if tiempo_cache_horas else 0,
                    minutes=0 if tiempo_cache_horas else 10,
                )
                agente.save()
                AgentesIA.objects.bulk_update([agente], ['vectorstore_enlaces_path', 'vectorstore_enlaces_expira'])
                return  # éxito — salir
            # Si no hay documentos y no hay apikeys más, no hay nada que indexar
        # Ninguna apikey funcionó (o ningún doc se pudo crear)
        if last_error is not None:
            raise last_error

    def __str__(self):
        return f"{self.nombre}"


TIPO_DETALLE_AGENTE_AI = (
    (1, 'ENLACE'),
    (2, 'ARCHIVO'),
    (3, 'TEXTO'),
)

TIPO_DATO_ENLACE = (
    (1, 'TEXT'),
    (2, 'HTML'),
    (3, 'JSON'),
    (4, 'EXCEL'),
    (5, 'CSV'),
)

class DetalleAgentesAI(ModeloBase):
    agente = models.ForeignKey(AgentesIA, on_delete=models.CASCADE, blank=True, null=True, verbose_name='Agente')
    tipo = models.PositiveSmallIntegerField(choices=TIPO_DETALLE_AGENTE_AI, default=1, verbose_name='Tipo de detalle')
    enlace = models.URLField(blank=True, null=True, verbose_name='Enlace')
    tipo_dato_enlace = models.PositiveSmallIntegerField(choices=TIPO_DATO_ENLACE, default=1, verbose_name='Tipo de dato retorna')
    archivo = models.FileField(
        upload_to='detalles_agentes/', blank=True, null=True, verbose_name='Archivo adjunto',
        validators=[FileExtensionValidator(["pdf", 'csv', 'json', 'xlsx']), FileMaxSizeInMbValidator(10)]
    )
    descripcion = models.TextField(blank=True, null=True, verbose_name='Descripción del detalle')

    # Campos específicos para tipo ENLACE
    requiere_token = models.BooleanField(default=False, verbose_name='Requiere token de autorización')
    token_autorizacion = models.CharField(max_length=500, blank=True, null=True, verbose_name='Token de autorización')
    usar_cache = models.BooleanField(default=False, verbose_name='Usar caché para consultas')
    tiempo_cache_horas = models.PositiveIntegerField(default=1, verbose_name='Tiempo de caché en horas')

    class Meta:
        verbose_name = 'Respuesta Entrenada IA'
        verbose_name_plural = 'Respuestas Entrenadas IA'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.tipo not in (2, 3):
            return  # ENLACE → no afecta vectorstore de archivos

        agente = self.agente
        if not agente:
            return

        # ── Recopilar todo el texto de los detalles activos ──────────────
        base_dir = os.path.join(settings.MEDIA_ROOT, 'vectorstores')
        nombre_vs = f"agente_{agente.id}"

        # Extraer texto raw de archivos (tipo 2) y textos directos (tipo 3)
        textos_raw = []
        detalles_archivo = agente.detalleagentesai_set.filter(
            status=True, tipo=2, archivo__isnull=False
        )
        detalles_texto = agente.detalleagentesai_set.filter(
            status=True, tipo=3
        ).exclude(descripcion__isnull=True).exclude(descripcion='')

        for detalle in detalles_archivo:
            try:
                from agents_ai.vectorstore_manager import VectorStoreManager as _VM
                raw_docs = _VM._extract_raw_text(detalle.archivo.path)
                if raw_docs:
                    textos_raw.append(raw_docs)
            except Exception as e:
                print(f"Error extrayendo texto de {detalle.archivo}: {e}")

        for detalle in detalles_texto:
            if detalle.descripcion:
                textos_raw.append(detalle.descripcion.strip())

        if not textos_raw:
            return

        texto_completo = "\n\n".join(textos_raw)

        # ── Decisión: contexto estático vs FAISS ─────────────────────────
        # Si el texto cabe en un prompt (≤ 40 000 chars), lo inyectamos
        # directamente → cero llamadas de embedding por mensaje.
        # Para documentos grandes usamos FAISS como antes.
        _UMBRAL_ESTATICO = 40_000

        agente.contexto_estatico = texto_completo[:_UMBRAL_ESTATICO]

        if len(texto_completo) <= _UMBRAL_ESTATICO:
            # Documento pequeño → solo contexto estático, limpiar FAISS
            agente.vectorstore_path = None
            agente.save()
            return

        # Documento grande → construir FAISS (y también guardar contexto estático
        # con los primeros 40k chars como respaldo)
        apikeys = agente.apikey.all()
        if not apikeys.exists():
            agente.save()
            return

        for apikeyobj in apikeys:
            if not apikeyobj.descripcion:
                continue
            try:
                vs_manager = VectorStoreManager(
                    storage_dir=base_dir,
                    provider=apikeyobj.proveedor,  # int — el provider registry lo resuelve
                    apikey=apikeyobj.descripcion
                )
                documentos = []
                for detalle in detalles_archivo:
                    docs = vs_manager.load_and_split(
                        detalle.archivo.path,
                        metadata={"detalle_id": detalle.id}
                    )
                    documentos.extend(docs)
                for detalle in detalles_texto:
                    if detalle.descripcion:
                        docs = vs_manager.build_from_string(
                            detalle.descripcion,
                            metadata={"detalle_id": detalle.id}
                        )
                        documentos.extend(docs)

                if documentos:
                    vs_path = vs_manager.build_and_save(documentos, nombre_vs)
                    agente.vectorstore_path = os.path.relpath(vs_path, settings.MEDIA_ROOT)
            except Exception as e:
                print(f"Error construyendo FAISS: {e}")
            break

        agente.save()


PROVEEDOR_CHOICES = (
    (2, 'GEMINI'),
    (3, 'OPEN IA'),
    (4, 'CLAUDE'),
)

class ApiKeyIA(ModeloBase):
    perfil = models.ForeignKey(PerfilNegocioIA, on_delete=models.CASCADE, blank=True, null=True, verbose_name='Perfil Negocio IA')
    descripcion = models.CharField(max_length=255, verbose_name="Api Key")
    proveedor = models.IntegerField(choices=PROVEEDOR_CHOICES, default=1, verbose_name='Proveedor')
    modelo = models.CharField(
        max_length=100, blank=True, default='', choices=MODELOS_DISPONIBLES,
        verbose_name='Modelo LLM',
        help_text='Modelo concreto a usar con esta API Key. Debe ser compatible con el proveedor '
                  '(Gemini con keys Gemini, GPT con OpenAI, Claude con Anthropic). Vacío = usa el default del provider.'
    )
    usuario = models.CharField(max_length=100, blank=True, null=True, verbose_name='Usuario')
    contrasena = models.CharField(max_length=100, blank=True, null=True, verbose_name='Contraseña')
    msgerror = models.TextField(blank=True, null=True, verbose_name='Mensaje de error', editable=False)
    estado = models.BooleanField(default=True, verbose_name='Estado')
    alias = models.CharField(max_length=100, blank=True, null=True, verbose_name='Alias')
    webservice_token = models.CharField(
        max_length=64, blank=True, null=True, unique=True,
        verbose_name='Token WebService',
        help_text='Token para autenticar llamadas al endpoint /api/ia/consultar/. Se genera automaticamente.',
    )

    class Meta:
        verbose_name = 'Api Keys IA'
        verbose_name_plural = 'Apis Keys IA'

    def __str__(self):
        base = f"[{self.get_proveedor_display()}]: {self.alias}"
        return f"{base} ({self.modelo})" if self.modelo else base

    def save(self, *args, **kwargs):
        if not self.webservice_token:
            import secrets
            self.webservice_token = secrets.token_urlsafe(48)
        super().save(*args, **kwargs)

    def regenerar_webservice_token(self):
        import secrets
        self.webservice_token = secrets.token_urlsafe(48)
        self.save(update_fields=['webservice_token'])


class ConsumoTokenIA(models.Model):
    """Registro de consumo de tokens por llamada al LLM."""
    apikey = models.ForeignKey(
        'ApiKeyIA', on_delete=models.CASCADE,
        related_name='consumos', verbose_name='API Key',
    )
    agente = models.ForeignKey(
        'AgentesIA', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='consumos', verbose_name='Agente',
    )
    conversacion = models.ForeignKey(
        'whatsapp.ConversacionWhatsApp', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='consumos_token', verbose_name='Conversación',
    )
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    tokens_entrada = models.IntegerField(default=0, verbose_name='Tokens entrada (prompt)')
    tokens_salida = models.IntegerField(default=0, verbose_name='Tokens salida (respuesta)')
    tokens_total = models.IntegerField(default=0, verbose_name='Tokens total')
    modelo = models.CharField(max_length=100, blank=True, default='', verbose_name='Modelo')
    origen = models.CharField(
        max_length=30, blank=True, default='', db_index=True,
        verbose_name='Origen',
        choices=[
            ('whatsapp',    'WhatsApp (mensaje entrante)'),
            ('chat_crm',    'Chat de prueba CRM'),
            ('webservice',  'WebService API externa'),
            ('resumidor',   'Resumen de conversacion'),
            ('sentimiento', 'Analisis de sentimiento'),
            ('auditor',     'Auditoria de agente'),
            ('plantilla',   'Generacion de plantilla'),
            ('herramienta', 'Generacion de herramienta'),
            ('imagen',      'Analisis de imagen'),
            ('otro',        'Otro'),
        ],
    )
    prompt_preview = models.CharField(
        max_length=300, blank=True, default='',
        verbose_name='Preview del prompt',
        help_text='Primeros 300 chars del mensaje/pregunta enviada al LLM.',
    )

    class Meta:
        verbose_name = 'Consumo de Tokens IA'
        verbose_name_plural = 'Consumos de Tokens IA'
        indexes = [models.Index(fields=['apikey', 'fecha'])]
        ordering = ['-fecha']

    def __str__(self):
        return f"{self.apikey} — {self.tokens_total} tokens ({self.fecha:%Y-%m-%d})"


class AlertaConsumoIA(models.Model):
    """Umbrales de alerta de consumo de tokens por API key."""
    apikey = models.OneToOneField(
        'ApiKeyIA', on_delete=models.CASCADE,
        related_name='alerta_consumo', verbose_name='API Key'
    )
    umbral_diario = models.IntegerField(
        'Umbral diario (tokens)', default=0,
        help_text='Notificar cuando el consumo diario supere este valor. 0 = sin límite'
    )
    umbral_mensual = models.IntegerField(
        'Umbral mensual (tokens)', default=0,
        help_text='Notificar cuando el consumo mensual supere este valor. 0 = sin límite'
    )
    notificar_a = models.ManyToManyField(
        'autenticacion.Usuario', blank=True,
        related_name='alertas_consumo_ia', verbose_name='Notificar a'
    )
    ultimo_aviso_diario = models.DateField('Último aviso diario', null=True, blank=True)
    ultimo_aviso_mensual = models.DateField('Último aviso mensual', null=True, blank=True)

    class Meta:
        verbose_name = 'Alerta de consumo IA'
        verbose_name_plural = 'Alertas de consumo IA'

    def __str__(self):
        return f"Alerta [{self.apikey}] — D:{self.umbral_diario} M:{self.umbral_mensual}"


class FeedbackMensajeBot(models.Model):
    """Feedback del agente humano sobre una respuesta generada por el bot."""
    mensaje = models.OneToOneField(
        'whatsapp.MensajeWhatsApp', on_delete=models.CASCADE,
        related_name='feedback', verbose_name='Mensaje'
    )
    es_correcto = models.BooleanField('¿Es correcto?')
    correccion = models.TextField('Respuesta correcta', blank=True, default='')
    pregunta_original = models.TextField('Pregunta que originó la respuesta', blank=True, default='')
    agente = models.ForeignKey(
        'AgentesIA', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='feedbacks', verbose_name='Agente'
    )
    usuario = models.ForeignKey(
        'autenticacion.Usuario', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='feedbacks_bot', verbose_name='Usuario que evaluó'
    )
    procesado_vectorstore = models.BooleanField('Agregado al vectorstore', default=False)
    fecha = models.DateTimeField('Fecha', auto_now_add=True)

    class Meta:
        verbose_name = 'Feedback mensaje bot'
        verbose_name_plural = 'Feedback mensajes bot'
        ordering = ['-fecha']

    def __str__(self):
        estado = '✓' if self.es_correcto else '✗'
        return f"{estado} Feedback msg#{self.mensaje_id}"


class DepartamentoChatBot(ModeloBase):
    nombre = models.CharField(max_length=100, verbose_name="Nombre")
    color = models.CharField(max_length=100, verbose_name="Color", default='')
    mensaje_saludo = models.TextField(verbose_name="Mensaje de saludo", default='')
    palabras_clave = models.TextField(
        blank=True, default='',
        verbose_name='Palabras clave de entrada',
        help_text='Una por línea. Si el mensaje entrante contiene alguna, se enruta aquí. Vacío = sólo por elección explícita.'
    )
    es_default = models.BooleanField(
        default=False, verbose_name='Departamento por defecto',
        help_text='Se usa cuando no hay match de palabras clave ni selección previa.'
    )
    activo_tradicional = models.BooleanField(
        default=True, verbose_name='Flujo tradicional activo',
        help_text='Si está desactivado, el departamento no responde con flujo (sirve sólo para handoff humano).'
    )

    class Meta:
        verbose_name = 'Departamento ChatBot'
        verbose_name_plural = 'Departamentos ChatBot'

    def __str__(self):
        return self.nombre

    def obtener_arbol_opciones(self):
        def construir_arbol(opciones):
            resultado = []
            for opcion in opciones:
                resultado.append({
                    'id': opcion.id,
                    'nombre': opcion.nombre,
                    'respuesta': opcion.respuesta,
                    'orden': opcion.orden,
                    'tipo_nodo': opcion.tipo_nodo,
                    'config': opcion.config or {},
                    'endpoint_id': opcion.endpoint_id,
                    'variable_destino': opcion.variable_destino or '',
                    'validacion_tipo': opcion.validacion_tipo or 'none',
                    'validacion_expresion': opcion.validacion_expresion or '',
                    'mensaje_error': opcion.mensaje_error or '',
                    'reintentos_max': opcion.reintentos_max or 3,
                    'es_inicio': bool(opcion.es_inicio),
                    'hijos': construir_arbol(opcion.subopciones.filter(status=True).order_by('orden'))
                })
            return resultado

        opciones_raiz = self.opciondepartamentochatbot_set.filter(opcion_padre__isnull=True, status=True).order_by('orden')
        return construir_arbol(opciones_raiz)

    def obtener_perfiles(self):
        return self.perfildepartamentochatbot_set.filter(status=True).order_by('usuario__first_name')

    def nodo_inicio(self):
        return self.opciondepartamentochatbot_set.filter(es_inicio=True, status=True).first() \
            or self.opciondepartamentochatbot_set.filter(opcion_padre__isnull=True, status=True).order_by('orden').first()

    def get_palabras_clave(self) -> list:
        return [p.strip().lower() for p in (self.palabras_clave or '').splitlines() if p.strip()]


class OpcionDepartamentoChatBot(ModeloBase):
    """
    Nodo de flujo estilo n8n. Cada nodo tiene:
      - `tipo_nodo`: qué hace (menu, pregunta, http, condicional, etc.)
      - `config` (JSON): parámetros tipados por tipo de nodo.
      - Conexiones salientes: vía `ConexionNodoChatbot` (DAG, con ramas etiquetadas).
        Se mantiene `opcion_padre` como fallback legacy (árbol simple de menús).

    Expresiones en `config`/strings: sintaxis `{{variables.x}}`, `{{contacto.numero}}`,
    `{{response.body.data[0].nombre}}`. El motor las resuelve al ejecutar.
    """
    TIPOS_NODO = [
        ('inicio',       'Inicio'),
        ('menu',         'Menú de opciones'),
        ('respuesta',    'Enviar respuesta'),
        ('pregunta',     'Capturar entrada del usuario'),
        ('http',         'Llamada HTTP (API externa)'),
        ('condicional',  'If / Else'),
        ('switch',       'Switch por valor'),
        ('set_variable', 'Definir variable(s)'),
        ('handoff',      'Transferir a humano'),
        ('esperar',      'Esperar (delay)'),
        ('fin',          'Fin de conversación'),
    ]
    VALIDACIONES = [
        ('none',   'Sin validación'),
        ('regex',  'Regex personalizada'),
        ('email',  'Email'),
        ('numero', 'Número'),
        ('cedula', 'Cédula (EC)'),
        ('ruc',    'RUC (EC)'),
        ('fecha',  'Fecha (YYYY-MM-DD)'),
        ('telefono', 'Teléfono'),
    ]

    departamento = models.ForeignKey(DepartamentoChatBot, on_delete=models.CASCADE, verbose_name="Departamento")
    orden = models.PositiveSmallIntegerField(default=0, verbose_name="Orden")
    nombre = models.CharField(max_length=100, verbose_name="Nombre")
    respuesta = models.TextField(verbose_name="Respuesta", default='', blank=True)
    opcion_padre = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='subopciones', verbose_name="Opción padre")

    tipo_nodo = models.CharField(max_length=20, choices=TIPOS_NODO, default='respuesta', verbose_name='Tipo de nodo')
    es_inicio = models.BooleanField(default=False, verbose_name='Nodo de inicio del flujo')
    config = models.JSONField(
        default=dict, blank=True,
        verbose_name='Parámetros (JSON)',
        help_text='Parámetros específicos del tipo de nodo. Ver plantillas en la documentación.'
    )

    endpoint = models.ForeignKey(
        'EndpointApiChatbot', on_delete=models.PROTECT,
        null=True, blank=True, related_name='nodos',
        verbose_name='Endpoint API', help_text='Sólo para tipo HTTP.'
    )

    variable_destino = models.CharField(
        max_length=80, blank=True, default='',
        verbose_name='Variable destino',
        help_text='Nombre de la variable donde se guarda la entrada del usuario o la respuesta de la API.'
    )
    validacion_tipo = models.CharField(max_length=20, choices=VALIDACIONES, default='none', verbose_name='Validación')
    validacion_expresion = models.CharField(max_length=250, blank=True, default='', verbose_name='Regex de validación')
    mensaje_error = models.TextField(blank=True, default='', verbose_name='Mensaje si la validación falla')
    reintentos_max = models.PositiveSmallIntegerField(default=3, verbose_name='Reintentos máximos')

    posicion_x = models.FloatField(default=0, verbose_name='Posición X (editor)')
    posicion_y = models.FloatField(default=0, verbose_name='Posición Y (editor)')

    class Meta:
        verbose_name = 'Nodo de Flujo ChatBot'
        verbose_name_plural = 'Nodos de Flujo ChatBot'
        ordering = ['departamento', 'orden', 'id']

    def __str__(self):
        return f"{self.departamento.nombre} · [{self.get_tipo_display()}] {self.nombre}"

    def siguientes(self, etiqueta: str = ''):
        """Devuelve nodos destino por etiqueta de salida (vacío = default)."""
        qs = self.salidas.filter(status=True).order_by('orden')
        if etiqueta:
            qs = qs.filter(etiqueta=etiqueta)
        return [c.nodo_destino for c in qs]

    def siguiente_default(self):
        conn = self.salidas.filter(status=True, etiqueta='').order_by('orden').first()
        if conn:
            return conn.nodo_destino
        hijo = self.subopciones.filter(status=True).order_by('orden').first()
        return hijo


class CredencialApiChatbot(ModeloBase):
    """
    Credencial reutilizable entre varios endpoints (estilo n8n Credentials).
    NOTA: los secretos se guardan en `secretos` (JSON). Si el proyecto añade
    cifrado a nivel de aplicación, migrar aquí. Por ahora va en claro igual
    que `ApiKeyIA.descripcion`.
    """
    TIPOS_AUTH = [
        ('none',          'Sin autenticación'),
        ('bearer',        'Bearer token'),
        ('basic',         'Basic auth (usuario/contraseña)'),
        ('apikey_header', 'API Key en header'),
        ('apikey_query',  'API Key en query string'),
        ('custom_header', 'Header(s) personalizado(s)'),
    ]
    nombre = models.CharField(max_length=100, verbose_name='Nombre')
    tipo = models.CharField(max_length=20, choices=TIPOS_AUTH, default='none', verbose_name='Tipo de autenticación')
    secretos = models.JSONField(
        default=dict, blank=True,
        verbose_name='Secretos (JSON)',
        help_text='Ej Bearer: {"token": "..."}. Basic: {"usuario": "...", "password": "..."}. '
                  'ApiKey: {"nombre_header": "X-API-Key", "valor": "..."}. Custom: {"headers": {"H1": "v1"}}.'
    )
    descripcion = models.TextField(blank=True, default='', verbose_name='Descripción')

    class Meta:
        verbose_name = 'Credencial API ChatBot'
        verbose_name_plural = 'Credenciales API ChatBot'

    def __str__(self):
        return f"{self.nombre} ({self.get_tipo_display()})"


class EndpointApiChatbot(ModeloBase):
    """
    Endpoint HTTP reutilizable. Un nodo tipo `http` apunta a uno de estos
    y sólo sobre-escribe path/body/query en su `config`.
    """
    nombre = models.CharField(max_length=120, verbose_name='Nombre')
    base_url = models.CharField(
        max_length=500, verbose_name='Base URL',
        help_text='Ej: https://api.miservicio.com. Sin slash final.'
    )
    credencial = models.ForeignKey(
        CredencialApiChatbot, on_delete=models.PROTECT,
        null=True, blank=True, related_name='endpoints',
        verbose_name='Credencial'
    )
    headers_default = models.JSONField(
        default=dict, blank=True,
        verbose_name='Headers por defecto (JSON)',
        help_text='Ej: {"Content-Type": "application/json", "Accept": "application/json"}'
    )
    timeout_seg = models.PositiveSmallIntegerField(default=15, verbose_name='Timeout (segundos)')
    descripcion = models.TextField(blank=True, default='', verbose_name='Descripción')

    class Meta:
        verbose_name = 'Endpoint API ChatBot'
        verbose_name_plural = 'Endpoints API ChatBot'

    def __str__(self):
        return f"{self.nombre} [{self.base_url}]"


class ConexionNodoChatbot(ModeloBase):
    """
    Arista del grafo entre nodos. Permite múltiples salidas por nodo,
    diferenciadas por `etiqueta`:
      - ''           → salida por defecto (flujo lineal)
      - 'true'/'false' → ramas de `condicional`
      - 'ok'/'error' → ramas de `http`
      - 'opcion_1'/'opcion_2'… → ramas de `menu`/`switch`
      - 'timeout'     → ramo cuando se agotan los reintentos de `pregunta`
    """
    nodo_origen = models.ForeignKey(
        OpcionDepartamentoChatBot, on_delete=models.CASCADE,
        related_name='salidas', verbose_name='Nodo origen'
    )
    nodo_destino = models.ForeignKey(
        OpcionDepartamentoChatBot, on_delete=models.CASCADE,
        related_name='entradas', verbose_name='Nodo destino'
    )
    etiqueta = models.CharField(max_length=60, blank=True, default='', verbose_name='Etiqueta de salida')
    orden = models.PositiveSmallIntegerField(default=0)
    descripcion = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        verbose_name = 'Conexión entre nodos'
        verbose_name_plural = 'Conexiones entre nodos'
        ordering = ['nodo_origen', 'orden']
        constraints = [
            models.UniqueConstraint(
                fields=['nodo_origen', 'nodo_destino', 'etiqueta'],
                name='uniq_conexion_chatbot'
            ),
        ]

    def __str__(self):
        etq = f"[{self.etiqueta}]" if self.etiqueta else ''
        return f"{self.nodo_origen_id} →{etq} {self.nodo_destino_id}"


class EstadoFlujoChatbot(ModeloBase):
    """
    Estado runtime del flujo para una conversación. Persiste en qué nodo
    quedó el contacto y qué variables ha capturado.
    """
    conversacion = models.OneToOneField(
        'whatsapp.ConversacionWhatsApp', on_delete=models.CASCADE,
        related_name='estado_flujo', verbose_name='Conversación'
    )
    departamento = models.ForeignKey(
        DepartamentoChatBot, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='estados_runtime',
        verbose_name='Departamento'
    )
    nodo_actual = models.ForeignKey(
        OpcionDepartamentoChatBot, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
        verbose_name='Nodo actual'
    )
    variables = models.JSONField(default=dict, blank=True, verbose_name='Variables capturadas')
    intentos = models.PositiveSmallIntegerField(default=0, verbose_name='Intentos en el nodo actual')
    finalizado = models.BooleanField(default=False, verbose_name='Flujo finalizado')
    en_handoff = models.BooleanField(
        default=False, verbose_name='En handoff humano',
        help_text='True cuando la conversación fue transferida a un asesor. '
                  'El motor no responde mientras esté en true.'
    )
    actualizado = models.DateTimeField(auto_now=True, verbose_name='Última actualización')

    class Meta:
        verbose_name = 'Estado de Flujo ChatBot'
        verbose_name_plural = 'Estados de Flujo ChatBot'

    def __str__(self):
        dep = self.departamento.nombre if self.departamento else '—'
        nod = self.nodo_actual.nombre if self.nodo_actual else '—'
        return f"Conv#{self.conversacion_id} · {dep} · nodo: {nod}"

    def set_variable(self, nombre: str, valor):
        self.variables = {**(self.variables or {}), nombre: valor}

    def reset(self):
        self.nodo_actual = None
        self.variables = {}
        self.intentos = 0
        self.finalizado = False
        self.en_handoff = False


class PerfilDepartamentoChatBot(ModeloBase):
    departamento = models.ForeignKey(DepartamentoChatBot, on_delete=models.SET_NULL, null=True, blank=True)
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)

    class Meta:
        verbose_name = 'Perfil Negocio ChatBot'
        verbose_name_plural = 'Perfiles Negocios ChatBot'

    def __str__(self):
        return f"{self.usuario.get_full_name()} - {self.departamento.nombre if self.departamento else 'Sin departamento'}"


# ---------------------------------------------------------------------------
# Detección de fin de conversación + acciones automáticas
# ---------------------------------------------------------------------------

class ReglaFinConversacion(ModeloBase):
    """
    Detecta el cierre de una conversación y dispara acciones.

    Puede estar asociada a:
      - una SesionWhatsApp (config específica por número) — campo `sesion`
      - un AgentesIA (plantilla reutilizable)             — campo `agente`

    El webhook primero busca la regla de la sesión; si no existe, cae en
    la del agente como plantilla.
    """
    sesion = models.OneToOneField(
        'whatsapp.SesionWhatsApp', on_delete=models.CASCADE,
        related_name='regla_fin', verbose_name='Sesión WhatsApp',
        blank=True, null=True,
    )
    agente = models.OneToOneField(
        'AgentesIA', on_delete=models.CASCADE, related_name='regla_fin',
        verbose_name='Agente IA (plantilla)',
        blank=True, null=True,
    )
    activo = models.BooleanField(default=True, verbose_name='Activo')
    usar_senal_llm = models.BooleanField(
        default=True,
        verbose_name='Detección por LLM',
        help_text='El LLM emitirá [FIN_CONVERSACION] cuando detecte una despedida o cierre natural.'
    )
    frases_cierre = models.TextField(
        blank=True, null=True,
        verbose_name='Frases de cierre (una por línea)',
        help_text='El sistema detectará el fin si el usuario envía alguna de estas frases. Ej: gracias hasta luego'
    )

    class Meta:
        verbose_name = 'Regla de Fin de Conversación'
        verbose_name_plural = 'Reglas de Fin de Conversación'

    def __str__(self):
        if self.sesion_id:
            return f"ReglaFin → {self.sesion}"
        if self.agente_id:
            return f"ReglaFin (plantilla) → {self.agente.nombre}"
        return f"ReglaFin #{self.pk}"

    def get_frases(self) -> list:
        if not self.frases_cierre:
            return []
        return [f.strip().lower() for f in self.frases_cierre.splitlines() if f.strip()]

    def detectar_por_frase(self, texto: str) -> bool:
        texto_norm = texto.strip().lower()
        return any(frase in texto_norm for frase in self.get_frases())

    @classmethod
    def para_sesion(cls, session):
        """
        Retorna la ReglaFinConversacion efectiva para una sesión:
        primero la de la sesión, luego la del agente como plantilla.
        """
        regla = getattr(session, 'regla_fin', None)
        if regla and regla.activo:
            return regla
        agente = getattr(session, 'agente_ia', None)
        if agente:
            regla_agente = getattr(agente, 'regla_fin', None)
            if regla_agente and regla_agente.activo:
                return regla_agente
        return None


class AccionFinConversacion(ModeloBase):
    """
    Una acción a ejecutar cuando se detecta el fin de conversación.
    Puede haber múltiples acciones por regla (email + webhook, etc.).
    """
    TIPOS = [
        ('email',    'Enviar correo electrónico'),
        ('whatsapp', 'Enviar mensaje WhatsApp al supervisor'),
        ('webhook',  'Llamar URL externa (HTTP POST)'),
        ('ninguna',  'Solo marcar conversación como finalizada'),
    ]
    regla = models.ForeignKey(
        ReglaFinConversacion, on_delete=models.CASCADE,
        related_name='acciones', verbose_name='Regla'
    )
    tipo = models.CharField(max_length=20, choices=TIPOS, verbose_name='Tipo de acción')
    destino = models.CharField(
        max_length=500, blank=True, null=True,
        verbose_name='Destino',
        help_text='Email, número WhatsApp con código de país (ej: 593912345678) o URL según el tipo.'
    )
    plantilla_mensaje = models.TextField(
        blank=True, null=True,
        verbose_name='Plantilla de mensaje',
        help_text='Variables disponibles: {nombre_contacto}, {numero}, {sesion}, {resumen}, {agente}'
    )

    class Meta:
        verbose_name = 'Acción de Fin de Conversación'
        verbose_name_plural = 'Acciones de Fin de Conversación'

    def __str__(self):
        return f"{self.get_tipo_display()} → {self.destino or '(sin destino)'}"

    def render_mensaje(self, contexto: dict) -> str:
        if not self.plantilla_mensaje:
            return ''
        try:
            return self.plantilla_mensaje.format(**contexto)
        except (KeyError, ValueError):
            return self.plantilla_mensaje


class AuditoriaAgenteIA(models.Model):
    """Analisis generado por IA sobre la configuracion de un agente.
    Guarda snapshot de la config, metricas, y sugerencias devueltas por el LLM.
    """
    ESTADO_CHOICES = (
        ('pendiente', 'Pendiente'),
        ('generado',  'Generado'),
        ('aplicado',  'Aplicado parcialmente'),
        ('cerrado',   'Aplicado completo'),
        ('error',     'Error'),
    )
    agente = models.ForeignKey(
        AgentesIA, on_delete=models.CASCADE, related_name='auditorias',
        verbose_name='Agente auditado',
    )
    usuario = models.ForeignKey(
        'autenticacion.Usuario', on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name='Usuario que solicito',
    )
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='pendiente')
    # Snapshot de la config que se audito (para poder rollback)
    snapshot_prompt = models.TextField(blank=True, null=True)
    snapshot_contexto = models.TextField(blank=True, null=True)
    # Metricas calculadas al momento de la auditoria
    metricas = models.JSONField(default=dict, blank=True)
    # Respuesta del LLM (JSON estructurado con sugerencias)
    sugerencias = models.JSONField(default=dict, blank=True)
    # Log de aplicacion: {campo: {aplicado_en, usuario}}
    aplicaciones = models.JSONField(default=dict, blank=True)
    razonamiento = models.TextField(blank=True, null=True)
    error_mensaje = models.TextField(blank=True, null=True)
    respuesta_cruda = models.TextField(blank=True, null=True, verbose_name='Respuesta cruda del LLM (debug)')
    tokens_usados = models.PositiveIntegerField(default=0)
    modelo_usado = models.CharField(max_length=80, blank=True, null=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Auditoria de Agente IA'
        verbose_name_plural = 'Auditorias de Agentes IA'
        ordering = ['-fecha', '-id']

    def __str__(self):
        return f"Auditoria #{self.id} — {self.agente.nombre} ({self.estado})"


# ─── Herramientas configurables por agente (tool-calling dinámico) ───────────

METODO_HTTP_CHOICES = (
    ('GET',  'GET'),
    ('POST', 'POST'),
)

UBICACION_PARAMS_CHOICES = (
    ('query', 'Query string (?param=valor)'),
    ('json',  'JSON body'),
    ('form',  'Form data (x-www-form-urlencoded)'),
    ('path',  'En la URL {param}'),
)

TIPO_PARAM_CHOICES = (
    ('string',  'Texto'),
    ('integer', 'Número entero'),
    ('number',  'Número decimal'),
    ('boolean', 'Sí/No'),
)


class HerramientaAgente(ModeloBase):
    """
    Herramienta (tool) que el LLM puede invocar vía function-calling para
    consultar una API externa. Cada AgentesIA puede tener múltiples herramientas
    configurables por el cliente final sin tocar código.

    El schema `parametros` describe los datos que el LLM debe recolectar del
    usuario antes de llamar la API. Cuando el agente responde, si detecta que
    el usuario quiere la información que esta tool ofrece, pedirá los datos
    faltantes de forma natural y luego ejecutará la llamada.
    """
    agente = models.ForeignKey(
        AgentesIA, on_delete=models.CASCADE, related_name='herramientas',
        verbose_name='Agente',
    )
    nombre = models.SlugField(
        max_length=64, verbose_name='Identificador (slug)',
        help_text='Identificador interno para el LLM, ej: consultar_saldo. Sin espacios.'
    )
    nombre_amigable = models.CharField(
        max_length=120, verbose_name='Nombre amigable',
        help_text='Nombre visible para el usuario administrador'
    )
    descripcion = models.TextField(
        verbose_name='Descripción (la ve el LLM)',
        help_text='Qué hace la herramienta y cuándo usarla. Esta descripción es la que '
                  'el modelo lee para decidir si llamarla.'
    )
    metodo = models.CharField(
        max_length=10, choices=METODO_HTTP_CHOICES, default='GET', verbose_name='Método HTTP'
    )
    url = models.URLField(
        max_length=500, verbose_name='URL',
        help_text='URL del endpoint. Puede incluir {param} para sustituir en el path.'
    )
    headers = models.JSONField(
        default=dict, blank=True, verbose_name='Headers estáticos',
        help_text='Ej: {"Authorization": "Bearer xxx", "Accept": "application/json"}'
    )
    parametros = models.JSONField(
        default=list, blank=True, verbose_name='Parámetros (schema para el LLM)',
        help_text='Lista de campos que el agente debe pedir al usuario. Cada item: '
                  '{"nombre": "cedula", "tipo": "string", "descripcion": "...", '
                  '"requerido": true, "pregunta_sugerida": "¿Me das tu cédula?"}'
    )
    ubicacion_params = models.CharField(
        max_length=10, choices=UBICACION_PARAMS_CHOICES, default='query',
        verbose_name='Ubicación de parámetros',
    )
    plantilla_respuesta = models.TextField(
        blank=True, default='', verbose_name='Plantilla Jinja de respuesta (opcional)',
        help_text='Si se define, el LLM verá el resultado formateado. Ej: '
                  '"Tu saldo es ${{monto}} al {{fecha}}". Vacío = el LLM recibe el JSON crudo.'
    )
    timeout = models.PositiveIntegerField(
        default=10, verbose_name='Timeout (segundos)',
        help_text='Tiempo máximo de espera. Máximo permitido: 30s.'
    )
    activo = models.BooleanField(default=True, verbose_name='Activa')

    class Meta:
        verbose_name = 'Herramienta de Agente'
        verbose_name_plural = 'Herramientas de Agentes'
        ordering = ['agente', 'nombre']
        constraints = [
            models.UniqueConstraint(fields=['agente', 'nombre'], name='uniq_herramienta_nombre_por_agente'),
        ]

    def __str__(self):
        return f"{self.agente.nombre} — {self.nombre}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.timeout and self.timeout > 30:
            raise ValidationError({'timeout': 'El timeout máximo permitido es 30 segundos.'})
        if not isinstance(self.parametros, list):
            raise ValidationError({'parametros': 'Debe ser una lista de objetos.'})
        for idx, p in enumerate(self.parametros):
            if not isinstance(p, dict):
                raise ValidationError({'parametros': f'El parámetro #{idx+1} debe ser un objeto.'})
            if not p.get('nombre'):
                raise ValidationError({'parametros': f'El parámetro #{idx+1} no tiene nombre.'})
            if p.get('tipo') not in dict(TIPO_PARAM_CHOICES):
                raise ValidationError({'parametros': f'Tipo inválido en parámetro "{p.get("nombre")}".'})


class LogHerramientaAgente(models.Model):
    """
    Auditoría de cada invocación de una HerramientaAgente — crítico para
    depurar cuando el cliente configura una URL/params mal.
    """
    herramienta = models.ForeignKey(
        HerramientaAgente, on_delete=models.CASCADE, related_name='logs',
        verbose_name='Herramienta',
    )
    conversacion = models.ForeignKey(
        'whatsapp.ConversacionWhatsApp', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='logs_herramienta', verbose_name='Conversación',
    )
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    request_url = models.TextField(blank=True, default='')
    request_params = models.JSONField(default=dict, blank=True)
    response_status = models.IntegerField(default=0, verbose_name='Código HTTP')
    response_body = models.TextField(blank=True, default='', verbose_name='Respuesta (truncada)')
    duracion_ms = models.PositiveIntegerField(default=0, verbose_name='Duración (ms)')
    exito = models.BooleanField(default=False)
    error_mensaje = models.TextField(blank=True, default='')

    class Meta:
        verbose_name = 'Log de herramienta'
        verbose_name_plural = 'Logs de herramientas'
        ordering = ['-fecha']
        indexes = [models.Index(fields=['herramienta', '-fecha'])]

    def __str__(self):
        estado = 'OK' if self.exito else 'ERR'
        return f"[{estado}] {self.herramienta.nombre} ({self.response_status}) @ {self.fecha:%Y-%m-%d %H:%M}"


# ─── Preguntas Frecuentes curables por agente ──────────────────────────────

FAQ_ORIGEN_CHOICES = (
    ('manual',       'Ingresada manualmente'),
    ('auditor',      'Sugerida por auditor IA'),
    ('conversacion', 'Aprendida de conversación'),
    ('feedback',     'Corrección de agente humano'),
)

FAQ_ESTADO_CHOICES = (
    ('pendiente',    'Pendiente de revisión'),
    ('aprobada',     'Aprobada (activa)'),
    ('desactivada',  'Desactivada'),
)


class FaqAgente(ModeloBase):
    """
    Pregunta/respuesta curada que complementa el entrenamiento del agente.

    Las top-N (por `prioridad`) en estado `aprobada` se inyectan literal en el
    prompt de cada respuesta. Las demás quedan disponibles vía búsqueda FAISS
    al agregarlas al vectorstore cuando se aprueban.
    """
    agente = models.ForeignKey(
        AgentesIA, on_delete=models.CASCADE, related_name='faqs',
        verbose_name='Agente',
    )
    pregunta = models.TextField('Pregunta')
    respuesta = models.TextField('Respuesta')
    origen = models.CharField(max_length=15, choices=FAQ_ORIGEN_CHOICES, default='manual')
    estado = models.CharField(max_length=15, choices=FAQ_ESTADO_CHOICES, default='pendiente')
    prioridad = models.PositiveSmallIntegerField(
        default=0, verbose_name='Prioridad',
        help_text='Mayor = aparece antes en el prompt. Solo afecta las top-N del prompt.'
    )
    hits = models.PositiveIntegerField(default=0, verbose_name='Veces usada')
    conversacion_origen = models.ForeignKey(
        'whatsapp.ConversacionWhatsApp', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='faqs_generadas',
        verbose_name='Conversación de origen',
    )
    mensaje_origen = models.ForeignKey(
        'whatsapp.MensajeWhatsApp', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='faqs_generadas',
        verbose_name='Mensaje de origen',
    )
    auditoria_origen = models.ForeignKey(
        AuditoriaAgenteIA, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='faqs_generadas',
        verbose_name='Auditoría de origen',
    )
    embebido_en_faiss = models.BooleanField(
        default=False,
        help_text='True si esta FAQ ya fue indexada en el vectorstore del agente.'
    )
    fecha_aprobacion = models.DateTimeField('Fecha de aprobación', null=True, blank=True)
    usuario_aprobacion = models.ForeignKey(
        'autenticacion.Usuario', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='faqs_aprobadas',
        verbose_name='Aprobada por',
    )

    class Meta:
        verbose_name = 'FAQ de Agente'
        verbose_name_plural = 'FAQs de Agentes'
        ordering = ['-prioridad', '-fecha_registro']
        indexes = [
            models.Index(fields=['agente', 'estado']),
            models.Index(fields=['agente', '-prioridad']),
        ]

    def __str__(self):
        return f"[{self.get_estado_display()}] {self.pregunta[:60]}"
