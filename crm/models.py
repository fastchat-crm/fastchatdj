import json
import os
from datetime import timedelta

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

    class Meta:
        verbose_name = 'Respuesta Entrenada IA'
        verbose_name_plural = 'Respuestas Entrenadas IA'

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

        def _money_map_to_str(m: dict | None) -> str:
            if not m:
                return ""
            # Ordena por clave numérica si es posible (1,2,3,4,5…)
            try:
                items = sorted(m.items(), key=lambda kv: int(kv[0]))
            except Exception:
                items = list(m.items())
            return ", ".join(f"{k}: {v}" for k, v in items if v is not None and str(v).strip() != "")
        for apikeyobj in apikeys:
            if not apikeyobj.descripcion:
                continue
            vs_manager = VectorStoreManager(
                storage_dir=base_dir,
                provider='gemini' if apikeyobj.proveedor == 2 else 'openai',
                apikey=apikeyobj.descripcion
            )
            documentos = []
            for detalle in detalles:
                try:
                    r = requests.get(detalle.enlace, timeout=30)
                    if r.status_code != 200:
                        continue
                    data = r.json()
                    if data.get("listCatalogo"):
                        for c in data.get("listCatalogo"):
                            page_content = f"""Curso: {c.get('nombre') or ''}
                            Categoría: {c.get('categoria', {}).get('descripcion') or ''}
                            Nombre: {c.get('nombre') or ''}
                            Unidad de negocio: {c.get('unidad_negocio') or ''}
                            Descripción: {c.get('descripcion') or ''}
                            Precio total (USD): {c.get('precio', {}).get('real')}
                            Fechas: {c.get('fechainicio', '')} a {c.get('fechafin')}
                            Horas que dura el curso: {c.get('horas', {}).get('total')}
                            Activo: {c.get('activo')}
                            Brochure: {c.get('brochure_url') or ''}
                            Portada: {c.get('portada_url') or ''}
                            """
                            metadata = {
                                "tipo": "listCatalogo",
                                "detalle_id": detalle.id,
                                "id": c.get("id"),
                                "slug": c.get("slug"),
                                "categoria": c.get("categoria"),
                                "unidad_negocio": c.get("unidad_negocio"),
                                "precio_total": c.get("precio", {}).get("total"),
                                "fechainicio": c.get("fechas", {}).get("inicio"),
                                "fechafin": c.get("fechas", {}).get("fin"),
                                "portada_url": c.get("portada_url"),
                                "brochure_url": c.get("brochure_url"),
                            }
                            docs = vs_manager.build_from_string(page_content, metadata=metadata)
                            documentos.extend(docs)
                    if data.get("data"):
                        for r in data["data"]:
                            costos = r.get("costos", {}) or {}
                            insc_str = _money_map_to_str(costos.get("inscripcion"))
                            matr_str = _money_map_to_str(costos.get("matricula"))

                            page_content = f"""Curso: {r.get('nombre') or ''}
                    Periodo: {r.get('periodo') or ''}
                    Centro de costo: {r.get('centro_costo') or ''}
                    Fechas: {r.get('fechainicio') or ''} a {r.get('fechafin') or ''}
                    Número de cuotas: {r.get('numero_cuotas') or ''}
                    Cupos disponibles: {r.get('tiene_cupo')}
                    Requisitos: {(r.get('requisitos') or '').strip()}
                    Descripción: {(r.get('descripcion') or '').strip()}
                    Costos:
                      - Inscripción: {insc_str or 'N/D'}
                      - Matrícula: {matr_str or 'N/D'}

                    Contexto: {(r.get('contexto') or '').strip()}
                    """

                            metadata = {
                                "tipo": "oferta_periodo",  # para distinguir de 'catalogo'
                                "detalle_id": detalle.id,
                                "id": r.get("id"),
                                "nombre": r.get("nombre"),
                                "periodo": r.get("periodo"),
                                "centro_costo": r.get("centro_costo"),
                                "fechainicio": r.get("fechainicio"),
                                "fechafin": r.get("fechafin"),
                                "numero_cuotas": r.get("numero_cuotas"),
                                "tiene_cupo": r.get("tiene_cupo"),
                                "costos_inscripcion": costos.get("inscripcion"),
                                "costos_matricula": costos.get("matricula"),
                            }

                            docs = vs_manager.build_from_string(page_content, metadata=metadata)
                            documentos.extend(docs)
                except Exception as e:
                    print(f"Error procesando enlace {detalle.enlace}: {e}")
                    continue
            if documentos:
                vs_path = vs_manager.build_and_save(documentos, nombre_vs)
                agente.vectorstore_enlaces_path = os.path.relpath(vs_path, settings.MEDIA_ROOT)
                # Siempre fijar una expiración mínima de 10 min para que el check
                # de caché no vuelva a entrar en la próxima petición.
                agente.vectorstore_enlaces_expira = timezone.now() + timedelta(
                    hours=tiempo_cache_horas if tiempo_cache_horas else 0,
                    minutes=0 if tiempo_cache_horas else 10,
                )
                agente.save()
                AgentesIA.objects.bulk_update([agente], ['vectorstore_enlaces_path', 'vectorstore_enlaces_expira'])
            break

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
                    provider='gemini' if apikeyobj.proveedor == 2 else 'openai',
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
)

class ApiKeyIA(ModeloBase):
    perfil = models.ForeignKey(PerfilNegocioIA, on_delete=models.CASCADE, blank=True, null=True, verbose_name='Perfil Negocio IA')
    descripcion = models.CharField(max_length=255, verbose_name="Api Key")
    proveedor = models.IntegerField(choices=PROVEEDOR_CHOICES, default=1, verbose_name='Proveedor')
    usuario = models.CharField(max_length=100, blank=True, null=True, verbose_name='Usuario')
    contrasena = models.CharField(max_length=100, blank=True, null=True, verbose_name='Contraseña')
    msgerror = models.TextField(blank=True, null=True, verbose_name='Mensaje de error', editable=False)
    estado = models.BooleanField(default=True, verbose_name='Estado')
    alias = models.CharField(max_length=100, blank=True, null=True, verbose_name='Alias')

    class Meta:
        verbose_name = 'Api Keys IA'
        verbose_name_plural = 'Apis Keys IA'

    def __str__(self):
        return f"[{self.get_proveedor_display()}]: {self.alias}"


class DepartamentoChatBot(ModeloBase):
    nombre = models.CharField(max_length=100, verbose_name="Nombre")
    color = models.CharField(max_length=100, verbose_name="Color", default='')
    mensaje_saludo = models.TextField(verbose_name="Mensaje de saludo", default='')

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
                    'hijos': construir_arbol(opcion.subopciones.filter(status=True).order_by('orden'))
                })
            return resultado

        opciones_raiz = self.opciondepartamentochatbot_set.filter(opcion_padre__isnull=True, status=True).order_by('orden')
        return construir_arbol(opciones_raiz)

    def obtener_perfiles(self):
        return self.perfildepartamentochatbot_set.filter(status=True).order_by('usuario__first_name')


class OpcionDepartamentoChatBot(ModeloBase):
    departamento = models.ForeignKey(DepartamentoChatBot, on_delete=models.CASCADE, verbose_name="Departamento")
    orden = models.PositiveSmallIntegerField(default=0, verbose_name="Orden")
    nombre = models.CharField(max_length=100, verbose_name="Nombre")
    respuesta = models.TextField(verbose_name="Respuesta", default='')
    opcion_padre = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='subopciones', verbose_name="Opción padre")

    class Meta:
        verbose_name = 'Opción Departamento ChatBot'
        verbose_name_plural = 'Opciones Departamentos ChatBot'

    def __str__(self):
        return f"{self.departamento.nombre} - {self.nombre}"


class PerfilDepartamentoChatBot(ModeloBase):
    departamento = models.ForeignKey(DepartamentoChatBot, on_delete=models.SET_NULL, null=True, blank=True)
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)

    class Meta:
        verbose_name = 'Perfil Negocio ChatBot'
        verbose_name_plural = 'Perfiles Negocios ChatBot'

    def __str__(self):
        return f"{self.usuario.get_full_name()} - {self.departamento.nombre if self.departamento else 'Sin departamento'}"
