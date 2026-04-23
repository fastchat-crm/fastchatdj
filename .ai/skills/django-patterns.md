# Django Patterns — fastchatdj

Patrones reusables específicos del CRM WhatsApp.

---

## QuerySet — optimización

### FK con select_related

```python
# ❌ N+1
for c in Contacto.objects.filter(status=True):
    print(c.sesion.nombre)

# ✅
for c in Contacto.objects.filter(status=True).select_related('sesion', 'pais'):
    print(c.sesion.nombre)
```

### Reverse FK / M2M con prefetch_related

```python
# ❌ Query por sesión
for s in SesionWhatsApp.objects.filter(status=True):
    print(s.conversaciones.count())

# ✅
for s in SesionWhatsApp.objects.filter(status=True).prefetch_related('conversaciones'):
    print(s.conversaciones.count())
```

### Prefetch anidado

```python
sesiones = SesionWhatsApp.objects.filter(status=True).prefetch_related(
    'conversaciones',
    'conversaciones__contacto',
    'conversaciones__mensajes',
)
for s in sesiones:
    for conv in s.conversaciones.all():
        for m in conv.mensajes.all():
            print(m.contenido)
```

### defer (campos pesados)

```python
MensajeWhatsApp.objects.filter(status=True).defer(
    'media_blob',
    'raw_payload',
).select_related('conversacion__contacto')
```

### Agregación SQL

```python
from django.db.models import Count, Avg, Sum, Q

SesionWhatsApp.objects.annotate(
    total_conversaciones=Count('conversaciones', filter=Q(conversaciones__status=True)),
    mensajes_hoy=Count('conversaciones__mensajes', filter=Q(
        conversaciones__mensajes__fecha_registro__date=timezone.localdate()
    ))
)
```

---

## ModeloBase — save override

```python
class PlantillaWhatsApp(ModeloBase):
    nombre = models.CharField(max_length=200)
    codigo = models.CharField(max_length=20, unique=True)

    def save(self, *args, **kwargs):
        if not self.pk:
            self.codigo = self._generar_codigo()
        super().save(*args, **kwargs)

    def _generar_codigo(self):
        ultimo = PlantillaWhatsApp.objects.order_by('-id').first()
        return f'PLT-{(ultimo.id if ultimo else 0) + 1:05d}'
```

### Save con validación

```python
def save(self, *args, **kwargs):
    self.full_clean()
    if self.fecha_fin and self.fecha_fin < self.fecha_inicio:
        raise ValidationError('Fecha fin debe ser posterior a inicio')
    super().save(*args, **kwargs)
```

`ModeloBase.save()` autopuebla `usuario_creacion`/`usuario_modificacion` desde `core.custom_middleware.get_current_request()`.

---

## Transacciones

`ATOMIC_REQUESTS = True` envuelve cada vista. Casos puntuales:

### Decorador

```python
from django.db import transaction

@transaction.atomic
def archivar_conversacion(conv_id):
    conv = ConversacionWhatsApp.objects.select_for_update().get(id=conv_id)
    conv.estado = 'ARCHIVADA'
    conv.save()
    conv.mensajes.update(visible=False)
```

### Context manager

```python
def importar_contactos(rows):
    with transaction.atomic():
        for r in rows:
            Contacto.objects.create(**r)
```

### Savepoints (anidado)

```python
def proceso():
    with transaction.atomic():
        sesion = SesionWhatsApp.objects.create(...)
        try:
            sid = transaction.savepoint()
            ConfigMeta.objects.create(sesion=sesion, ...)
            transaction.savepoint_commit(sid)
        except Exception:
            transaction.savepoint_rollback(sid)  # sólo retrocede ConfigMeta
```

---

## Form validation

### clean_<field>

```python
class ContactoForm(ModelFormBase):
    class Meta:
        model = Contacto
        fields = ['numero', 'nombre', 'sesion']

    def clean_numero(self):
        numero = self.cleaned_data.get('numero')
        if not numero.isdigit() or len(numero) < 7:
            raise forms.ValidationError('Número inválido')
        if Contacto.objects.filter(
            numero=numero,
            sesion=self.cleaned_data.get('sesion'),
            status=True
        ).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Ya existe en esta sesión')
        return numero
```

### clean() (cross-field)

```python
def clean(self):
    cleaned = super().clean()
    inicio = cleaned.get('fecha_inicio')
    fin = cleaned.get('fecha_fin')
    if inicio and fin and fin < inicio:
        raise forms.ValidationError({'fecha_fin': 'Debe ser posterior a inicio'})
    return cleaned
```

---

## Managers custom

### Sólo activos

```python
class ActivosManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(status=True)

class Contacto(ModeloBase):
    objects = models.Manager()
    activos = ActivosManager()

# Uso
Contacto.activos.all()  # sólo status=True
```

### Con select_related por defecto

```python
class ConversacionManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related(
            'sesion', 'contacto'
        ).filter(status=True)
```

(Ver `whatsapp/models_querysetmanagers.py:9` `ContactoManager` real.)

---

## Signals

### post_save

```python
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=MensajeWhatsApp)
def actualizar_estadisticas(sender, instance, created, **kwargs):
    if created and instance.direccion == 'recibido':
        EstadisticasConversacion.objects.filter(
            conversacion=instance.conversacion
        ).update(ultimo_mensaje=instance.fecha_registro)
```

### pre_save

```python
@receiver(pre_save, sender=Contacto)
def normalizar_numero(sender, instance, **kwargs):
    if instance.numero:
        instance.numero = instance.numero.replace(' ', '').replace('+', '')
```

---

## Middleware — request actual

`core.custom_middleware` guarda el request en thread-local. `ModeloBase.save()` lo lee para autopoblar usuario. Para acceder manual:

```python
from core.custom_middleware import get_current_request

def algun_helper():
    request = get_current_request()
    if request and request.user.is_authenticated:
        return request.user
```

---

## Paginación

### Manual

```python
from django.core.paginator import Paginator

def listado_contactos(request):
    qs = Contacto.objects.filter(status=True)
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'listado.html', {'contactos': page, 'paginator': paginator})
```

### Template incluido

`{% include 'paginacion.html' %}` (helper del proyecto).

---

## JsonResponse — formato AJAX

Backend siempre devuelve **lista de objetos** (forma esperada por `forms.js`).

### Éxito + reload

```python
return JsonResponse([{
    'error': False,
    'msg_reload': True,
    'msg_title': 'Guardado',
    'msg_body': 'Plantilla creada'
}])
```

### Éxito + redirect

```python
return JsonResponse([{
    'error': False,
    'msg_to': True,
    'to': '/whatsapp/plantillas/',
    'msg_title': 'Listo',
    'msg_body': 'Operación completada'
}])
```

### Éxito + ejecutar JS

```python
return JsonResponse([{'error': False, 'function_js': 'recargarTabla(); cerrarModal();'}])
```

### Errores form

```python
errores = [{f: errs[0]} for f, errs in form.errors.items()]
return JsonResponse([{'error': True, 'message': 'Errores', 'form': errores}])
```

Ver `skills/forms-ajax.md` para contrato completo.

---

## File upload

```python
from core.funciones import generar_nombre
from django.utils.text import slugify

class PlantillaWhatsAppForm(ModelFormBase):
    class Meta:
        model = PlantillaWhatsApp
        fields = ['nombre', 'header_archivo']

    def clean_header_archivo(self):
        f = self.cleaned_data.get('header_archivo')
        if f:
            ext = f.name.split('.')[-1].lower()
            if ext not in ['jpg', 'jpeg', 'png', 'mp4', 'pdf']:
                raise forms.ValidationError('Formato no permitido por Meta')
            if f.size > 16 * 1024 * 1024:  # 16MB límite Meta
                raise forms.ValidationError('Archivo > 16MB')
        return f

# En vista
if 'header_archivo' in request.FILES:
    f = request.FILES['header_archivo']
    f._name = generar_nombre(slugify(f._name), f._name)
    form.instance.header_archivo = f
```

---

## Q objects

### OR

```python
Contacto.objects.filter(
    Q(numero__icontains=criterio) |
    Q(nombre__icontains=criterio) |
    Q(email__icontains=criterio)
)
```

### AND + OR

```python
ConversacionWhatsApp.objects.filter(
    Q(status=True) &
    (Q(estado='ABIERTA') | Q(estado='PAUSADA')) &
    Q(sesion=sesion_actual)
).distinct()
```

### NOT

```python
MensajeWhatsApp.objects.filter(~Q(direccion='enviado'))
```

---

## F expressions

### Update atómico

```python
from django.db.models import F

EstadisticasConversacion.objects.filter(
    conversacion=conv
).update(total_mensajes=F('total_mensajes') + 1)
```

### Comparación campos

```python
ConversacionWhatsApp.objects.filter(
    fecha_modificacion__lt=F('fecha_registro')  # error de datos
)
```

---

## Email (SendGrid)

```python
from django.core.mail import send_mail
from django.template.loader import render_to_string

html = render_to_string('emails/notif_plantilla.html', {'plantilla': plantilla})
send_mail(
    subject='Plantilla aprobada',
    message='',  # texto plano
    from_email='no-reply@tudominio',
    recipient_list=[user.email],
    html_message=html
)
```

Para envíos masivos/threaded ver helpers en `core/`.

---

## Soft-delete (ModeloBase)

```python
# ❌ NO
mensaje.delete()

# ✅
mensaje.status = False
mensaje.save()

# Bulk
MensajeWhatsApp.objects.filter(
    conversacion__estado='ARCHIVADA'
).update(status=False)

# Filtrar siempre
Contacto.objects.filter(status=True)
sesion.contactos.filter(status=True)
```

---

## Cache (Redis)

```python
from django.core.cache import cache

# Set con TTL
cache.set(f'wa_rate_limited_{sesion.id}', True, timeout=retry_after_ms / 1000)

# Get con default
limited = cache.get(f'wa_rate_limited_{sesion.id}', False)

# Delete
cache.delete(f'wa_rate_limited_{sesion.id}')
```

Patrón usado en `whatsapp/view_webhook_handler.py` para rate-limit.

---

## Pitfalls

❌:
```python
Contacto.objects.all()                 # incluye soft-deleted
for c in Contacto.objects.all():       # N+1 con FK
    print(c.sesion.nombre)
fecha = datetime(2025, 1, 1)           # naive, no TZ
mensaje.delete()                       # físico, pierde audit
sesion.qr_code                         # falla si proveedor='meta'
```

✅:
```python
Contacto.objects.filter(status=True)
Contacto.objects.filter(status=True).select_related('sesion')
from django.utils import timezone
fecha = timezone.now()
mensaje.status = False; mensaje.save()
if sesion.es_baileys:
    sesion.qr_code
```
