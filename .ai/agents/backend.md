# Backend Agent - Django Development

Guía para desarrollo backend Django en **fastchatdj** (CRM WhatsApp + IA).

---

## Apps reales

```
autenticacion/    # Usuario custom (extends AbstractUser), perfiles cliente/admin, login/recovery
seguridad/        # Configuracion singleton, Modulo/GroupModulo (control acceso URL), auditoria, empresas, notificaciones
area_geografica/  # Pais → Provincia → Ciudad → Parroquia
whatsapp/         # SesionWhatsApp, Contacto, ConversacionWhatsApp, MensajeWhatsApp, ConfigMeta, PlantillaWhatsApp, consumers, webhooks
crm/              # PerfilNegocioIA, AgentesIA, EntrenamientosIA, productos/servicios, departamentos chatbot
agents_ai/        # AgenteConsultor, AgenteResumidor (LangChain + Google GenAI / OpenAI), FAISS vectorstores
core/             # ModeloBase, ModelFormBase, ConsultasAjax, middleware, encriptación, helpers
public/           # Vistas no autenticadas (registro, login, recovery)
cron_jobs/        # Tareas programadas (despedidas, envíos diferidos)
```

**Doble proveedor WhatsApp:** `SesionWhatsApp.proveedor` ∈ `{'baileys', 'meta'}`. Helpers `sesion.es_baileys` / `sesion.es_meta`. Nunca acceder campos Baileys (`qr_code`, `whatsapp_id`) sin guardar `es_baileys`.

---

## Modelos

### Estructura estándar

```python
from core.custom_models import ModeloBase
from django.db import models

class PlantillaWhatsApp(ModeloBase):
    # ModeloBase ya añade: usuario_creacion, fecha_registro,
    # usuario_modificacion, fecha_modificacion, status (soft-delete)

    config_meta = models.ForeignKey(
        'whatsapp.ConfigMeta',
        on_delete=models.CASCADE,
        related_name='plantillas'
    )
    nombre = models.CharField(max_length=200)
    idioma = models.CharField(max_length=10, default='es')
    categoria = models.CharField(max_length=20, choices=CATEGORIAS_PLANTILLA)
    cuerpo = models.TextField()
    estado_meta = models.CharField(max_length=20, default='BORRADOR')

    class Meta:
        verbose_name = 'Plantilla WhatsApp'
        verbose_name_plural = 'Plantillas WhatsApp'
        ordering = ['-fecha_registro']

    def __str__(self):
        return f'{self.nombre} ({self.idioma})'
```

### Soft-delete (ModeloBase)

```python
# ❌ NO eliminar físicamente
contacto.delete()

# ✅ Soft-delete
contacto.status = False
contacto.save()

# ✅ Filtrar siempre activos
Contacto.objects.filter(status=True)
```

### ModeloBase real (`core/custom_models.py:118`)

Campos:
- `usuario_creacion` (FK Usuario, nullable)
- `fecha_registro` (DateTimeField, auto_now_add)
- `usuario_modificacion` (FK Usuario, nullable)
- `fecha_modificacion` (DateTimeField, nullable)
- `status` (Boolean, default True)

`save()` autopuebla usuario desde `core.custom_middleware.get_current_request()`.

`NormalModel` (clase padre de `ModeloBase`) inyecta dinámicamente atributos en `__init__`:
- `<bool_field>_boolhtml`, `_yesorno`, `_texthtml`
- `<decimal_field>_money`, `_unlocalize`, `_integer`
- `<file_field>` íconos por extensión

---

## Vistas

### Estructura estándar

```python
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from core.funciones import secure_module, addData
from whatsapp.models import Contacto

@login_required
@secure_module
def listado_contactos(request):
    data = {
        'titulo': 'Contactos',
        'modulo': 'WhatsApp',
        'ruta': request.path,
    }
    addData(request, data)

    contactos = Contacto.objects.filter(status=True)\
        .select_related('sesion', 'pais')\
        .prefetch_related('etiquetas')\
        .order_by('-fecha_registro')

    data['contactos'] = contactos
    return render(request, 'whatsapp/contacto_listado.html', data)
```

### AJAX (POST handler)

```python
from django.views.decorators.http import require_http_methods
from core.custom_forms import FormError

@login_required
@require_http_methods(["POST"])
def guardar_plantilla(request):
    try:
        form = PlantillaWhatsAppForm(request.POST, request.FILES)
        if form.is_valid():
            plantilla = form.save()
            return JsonResponse([{
                'error': False,
                'msg_reload': True,
                'msg_title': 'Guardado',
                'msg_body': f'Plantilla {plantilla.nombre} guardada'
            }])
        raise FormError(form)
    except FormError as e:
        return JsonResponse([{
            'error': True,
            'message': 'Errores de validación',
            'form': e.error_dict
        }])
    except Exception as e:
        logger.error(f'Error guardar_plantilla: {e}', exc_info=True)
        return JsonResponse([{'error': True, 'message': str(e)}])
```

**Formato respuesta** lo procesa `static/js/forms.js` automáticamente. Ver `skills/forms-ajax.md`.

### AJAX dispatcher central (`core/ajax.py:11`)

`ConsultasAjax` en `/ajaxrequest/<accion>/` despacha por nombre de acción. Vista `consultas` en `/consultas/` similar. Para handlers compartidos (autocomplete, listas dependientes, validaciones) ahí; para CRUD principal usar vistas dedicadas.

---

## Optimización queries

### select_related (FK)

```python
# ❌ N+1
for c in Contacto.objects.filter(status=True):
    print(c.sesion.nombre)  # query por iteración

# ✅
for c in Contacto.objects.filter(status=True).select_related('sesion', 'pais'):
    print(c.sesion.nombre)
```

### prefetch_related (reverse FK / M2M)

```python
sesiones = SesionWhatsApp.objects.filter(status=True).prefetch_related(
    'conversaciones__mensajes'
)
```

### defer (campos pesados)

```python
MensajeWhatsApp.objects.filter(status=True).defer('media_blob', 'raw_payload')
```

### Agregación SQL

```python
from django.db.models import Count, Q

SesionWhatsApp.objects.annotate(
    total_conversaciones=Count('conversaciones', filter=Q(conversaciones__status=True)),
    total_mensajes=Count('conversaciones__mensajes')
)
```

---

## Permisos — `@secure_module`

Implementado en `core/funciones.py:404`. Comprueba: superuser pasa; staff autenticado debe tener `Modulo` cuya URL haga `istartswith` de `request.path`, vía `GroupModulo`. Si falla redirige a `/panel/`.

```python
@login_required
@secure_module
def mi_vista(request):
    data = {'titulo': 'X'}
    addData(request, data)  # inyecta permisos + contexto user
    ...
```

`addData()` (en `core/funciones.py:523`) inyecta `confi` (Configuracion singleton), datos del usuario, fechas, dominio, etc. al contexto del template.

**No hacer** chequeos manuales `request.user.has_perm(...)` — se maneja por `Modulo`/`GroupModulo`.

---

## Forms

```python
from core.custom_forms import ModelFormBase

class ContactoForm(ModelFormBase):
    class Meta:
        model = Contacto
        fields = ('nombre', 'numero', 'sesion', 'etiquetas')

    def clean_numero(self):
        numero = self.cleaned_data.get('numero')
        if Contacto.objects.filter(numero=numero, sesion=self.cleaned_data.get('sesion'), status=True)\
                .exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Número ya registrado en esta sesión')
        return numero
```

`ModelFormBase` autoaplica:
1. Clases Bootstrap 4
2. Switchery a `BooleanField`
3. Select2 a `ChoiceField` (clase `.jselect2`)
4. Modo solo lectura: `MiForm(ver=True)`
5. Asteriscos en requeridos
6. `toArray()` para extraer `cleaned_data`

---

## Transacciones

`ATOMIC_REQUESTS = True` envuelve cada vista. Para operaciones puntuales:

```python
from django.db import transaction

@transaction.atomic
def crear_conversacion_con_bienvenida(sesion, contacto, texto):
    conv = ConversacionWhatsApp.objects.create(sesion=sesion, contacto=contacto)
    MensajeWhatsApp.objects.create(conversacion=conv, contenido=texto, direccion='enviado')
    return conv
```

---

## WhatsApp — flujo recepción

```
Node.js → POST /whatsapp/webhook_handler/ (X-API-Key: NODE_SECRET_KEY)
   ↓ process_incoming_message()
   ↓ idempotente por mensaje_id_externo
crea/actualiza: MensajeWhatsApp, ConversacionWhatsApp, Contacto, EstadisticasConversacion
   ↓ async_to_sync → channel_layer.group_send → ChatConsumer (HTML render)
   ↓ si SesionWhatsApp.agente_ia is set:
AgenteConsultor.responder() → FAISS similarity → LangChain prompt → Google GenAI
   ↓
WhatsAppService.send_message() → WHATSAPP_API_URL (Baileys)
  o MetaWhatsAppService.send_text_message() → Meta Cloud API
```

**Dispatcher transporte:** `services.get_whatsapp_service(sesion)` retorna instancia adecuada según `sesion.proveedor`. Migrar call sites a esto antes de añadir features.

**Rate-limit Node:** flag cache `wa_rate_limited_<session_id>` con TTL = `retryAfterMs`. Mientras está, `process_incoming_message` corta antes de bienvenida/IA/avisos.

**Endpoints reliability** (todos requieren `X-API-Key: NODE_SECRET_KEY`):
- `POST /whatsapp/webhook_handler/batch/` — drena outbox Node, retorna ACK por evento (max 200/batch)
- `POST /whatsapp/heartbeat/` — Node ping cada 30-60s; cache 180s. Helpers: `node_esta_vivo()`, `estado_heartbeat_sesion(session_id)`
- `POST /whatsapp/trace/` — trazas Node → `TrazaMensajeIA`

---

## File upload

```python
from core.funciones import generar_nombre

if 'archivo' in request.FILES:
    f = request.FILES['archivo']
    f._name = generar_nombre(slugify(f._name), f._name)  # único por timestamp
    form.instance.archivo = f
```

---

## Errores

```python
import logging
logger = logging.getLogger(__name__)

try:
    ...
except ObjectDoesNotExist:
    return JsonResponse([{'error': True, 'message': 'Registro no encontrado'}])
except ValidationError as e:
    return JsonResponse([{'error': True, 'message': str(e)}])
except Exception as e:
    logger.error(f'Error en {__name__}: {e}', exc_info=True)
    return JsonResponse([{'error': True, 'message': 'Error interno'}])
```

No usar `print()`. Todo log con `logger`.

---

## Pitfalls

❌ NO:
- Olvidar `status=True` en queries
- `.all()` sin `select_related()` para FK
- Hardcodear secretos (usar `credenciales.json`)
- Saltarse `@secure_module`
- `delete()` físico (soft-delete)
- Acceder campos Baileys sin guardar `sesion.es_baileys`

✅ SÍ:
- Heredar `ModeloBase`
- `select_related` / `prefetch_related`
- `@login_required` + `@secure_module`
- `JsonResponse([{...}])` formato esperado por `forms.js`
- Branch por `sesion.proveedor` en código que toca WhatsApp

---

**Ver también:**
- `skills/django-patterns.md` — patrones reusables
- `skills/forms-ajax.md` — formato respuesta JSON
- `agents/frontend.md` — UI patterns
