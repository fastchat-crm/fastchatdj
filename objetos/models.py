"""Objetos personalizados — modelo de datos extensible en runtime.

El problema que resuelve: cada cliente de un rubro nuevo (inmobiliaria, clínica,
concesionaria) obligaba a agregar modelos a `models.py` y correr migraciones.
Acá el usuario define sus propias entidades desde la UI y el sistema las
interpreta, sin DDL ni deploy.

Enfoque: **metadata + JSONB**, no EAV.

    ObjetoPersonalizado   → define la entidad ("Propiedad", "Póliza")
    CampoPersonalizado    → define cada campo y su tipo
    RegistroPersonalizado → una fila; los valores viven en `datos` (JSONB)
    AsociacionRegistro    → relaciona dos registros cualesquiera

Se eligió JSONB sobre EAV porque ya corremos PostgreSQL 15, el proyecto ya usa
JSONB en varios modelos, y un EAV obliga a un JOIN por campo consultado. El
costo es que la integridad la valida la aplicación (`validar_datos`), no la BD.
Ver `.ai/docs/estudio_gohighlevel.md` sección 4.3.
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.db import models

from autenticacion.models import Usuario
from core.custom_models import ModeloBase

# Tipos de campo soportados. La clave se guarda en BD; el label se muestra en la
# UI; `widget` le dice al template qué input renderizar.
TIPO_TEXTO = 'texto'
TIPO_TEXTO_LARGO = 'texto_largo'
TIPO_NUMERO = 'numero'
TIPO_DECIMAL = 'decimal'
TIPO_BOOLEANO = 'booleano'
TIPO_FECHA = 'fecha'
TIPO_FECHA_HORA = 'fecha_hora'
TIPO_EMAIL = 'email'
TIPO_TELEFONO = 'telefono'
TIPO_URL = 'url'
TIPO_SELECCION = 'seleccion'
TIPO_SELECCION_MULTIPLE = 'seleccion_multiple'

TIPO_CAMPO_CHOICES = (
    (TIPO_TEXTO, 'Texto corto'),
    (TIPO_TEXTO_LARGO, 'Texto largo'),
    (TIPO_NUMERO, 'Número entero'),
    (TIPO_DECIMAL, 'Número decimal'),
    (TIPO_BOOLEANO, 'Sí / No'),
    (TIPO_FECHA, 'Fecha'),
    (TIPO_FECHA_HORA, 'Fecha y hora'),
    (TIPO_EMAIL, 'Correo electrónico'),
    (TIPO_TELEFONO, 'Teléfono'),
    (TIPO_URL, 'Enlace'),
    (TIPO_SELECCION, 'Lista desplegable'),
    (TIPO_SELECCION_MULTIPLE, 'Selección múltiple'),
)

# Tipos que necesitan que el usuario cargue opciones.
TIPOS_CON_OPCIONES = (TIPO_SELECCION, TIPO_SELECCION_MULTIPLE)

_RE_SLUG = re.compile(r'^[a-z][a-z0-9_]*$')


def normalizar_clave(texto):
    """Convierte una etiqueta libre en una clave usable dentro del JSONB."""
    base = (texto or '').strip().lower()
    base = base.replace('á', 'a').replace('é', 'e').replace('í', 'i')
    base = base.replace('ó', 'o').replace('ú', 'u').replace('ñ', 'n')
    base = re.sub(r'[^a-z0-9]+', '_', base).strip('_')
    if not base:
        return ''
    if base[0].isdigit():
        base = f'c_{base}'
    return base[:50]


class ObjetoPersonalizado(ModeloBase):
    """Una entidad definida por el usuario."""
    usuario = models.ForeignKey(
        Usuario, on_delete=models.CASCADE, related_name='objetos_personalizados',
        verbose_name='Propietario'
    )
    nombre_singular = models.CharField(
        max_length=80, verbose_name='Nombre en singular',
        help_text='Cómo se llama un registro suelto. Ej: "Propiedad", "Póliza", "Vehículo".'
    )
    nombre_plural = models.CharField(
        max_length=80, verbose_name='Nombre en plural',
        help_text='Cómo se llama el listado. Ej: "Propiedades", "Pólizas", "Vehículos".'
    )
    slug = models.SlugField(
        max_length=60, unique=True, verbose_name='Identificador',
        help_text='Se usa en la URL del módulo. Se genera solo a partir del nombre.'
    )
    icono = models.CharField(
        max_length=50, blank=True, default='fa fa-cube', verbose_name='Ícono',
        help_text='Clase de Font Awesome. Ej: "fa fa-home", "fa fa-car".'
    )
    descripcion = models.TextField(blank=True, default='', verbose_name='Descripción')

    class Meta:
        verbose_name = 'Objeto personalizado'
        verbose_name_plural = 'Objetos personalizados'
        ordering = ('nombre_plural',)

    def __str__(self):
        return self.nombre_plural

    def campos_activos(self):
        return self.campos.filter(status=True).order_by('orden', 'id')

    def campos_de_listado(self):
        """Campos que se muestran como columnas. Si el usuario no marcó
        ninguno, se toman los primeros cuatro para que la tabla no salga vacía."""
        marcados = list(self.campos_activos().filter(mostrar_en_listado=True))
        return marcados or list(self.campos_activos()[:4])

    def validar_datos(self, datos, parcial=False):
        """Valida un dict de valores contra los campos del objeto.

        Devuelve `(limpios, errores)`. `parcial=True` omite la comprobación de
        obligatorios — se usa al editar, donde el form puede mandar un subconjunto.
        """
        limpios, errores = {}, {}
        for campo in self.campos_activos():
            presente = campo.nombre in datos
            if not presente and parcial:
                continue
            valor, error = campo.limpiar(datos.get(campo.nombre))
            if error:
                errores[campo.nombre] = error
            else:
                limpios[campo.nombre] = valor
        return limpios, errores


class CampoPersonalizado(ModeloBase):
    """Un campo de un objeto personalizado."""
    objeto = models.ForeignKey(
        ObjetoPersonalizado, on_delete=models.CASCADE, related_name='campos',
        verbose_name='Objeto'
    )
    nombre = models.CharField(
        max_length=50, verbose_name='Clave interna',
        help_text='Nombre con el que se guarda el valor. Se genera solo desde la etiqueta.'
    )
    etiqueta = models.CharField(
        max_length=100, verbose_name='Etiqueta',
        help_text='Lo que ve el usuario en el formulario.'
    )
    tipo = models.CharField(
        max_length=25, choices=TIPO_CAMPO_CHOICES, default=TIPO_TEXTO,
        verbose_name='Tipo de dato'
    )
    requerido = models.BooleanField(
        default=False, verbose_name='Obligatorio',
        help_text='No se puede guardar el registro si este campo viene vacío.'
    )
    orden = models.PositiveSmallIntegerField(
        default=0, verbose_name='Orden',
        help_text='Posición en el formulario. Menor number aparece primero.'
    )
    opciones = models.JSONField(
        blank=True, null=True, default=None, verbose_name='Opciones',
        help_text='Lista de valores para los campos de selección.'
    )
    ayuda = models.CharField(
        max_length=255, blank=True, default='', verbose_name='Texto de ayuda',
        help_text='Aclaración que se muestra debajo del campo.'
    )
    mostrar_en_listado = models.BooleanField(
        default=False, verbose_name='Mostrar como columna',
        help_text='Si se activa, el campo aparece como columna en el listado.'
    )

    class Meta:
        verbose_name = 'Campo personalizado'
        verbose_name_plural = 'Campos personalizados'
        ordering = ('orden', 'id')
        unique_together = (('objeto', 'nombre'),)

    def __str__(self):
        return f'{self.objeto.nombre_singular} · {self.etiqueta}'

    def clean(self):
        errores = {}
        if self.nombre and not _RE_SLUG.match(self.nombre):
            errores['nombre'] = ('La clave interna debe empezar con una letra y usar solo '
                                 'minúsculas, números y guion bajo.')
        if self.tipo in TIPOS_CON_OPCIONES and not (self.opciones or []):
            errores['opciones'] = 'Cargá al menos una opción para un campo de selección.'
        if errores:
            raise ValidationError(errores)

    @property
    def es_multivalor(self):
        return self.tipo == TIPO_SELECCION_MULTIPLE

    def lista_opciones(self):
        return [str(o) for o in (self.opciones or []) if str(o).strip()]

    def limpiar(self, valor):
        """Normaliza y valida un valor suelto. Devuelve `(valor, error)`.

        El valor que sale es siempre serializable a JSON: las fechas se guardan
        en ISO, los decimales como string (no float, para no perder precisión en
        importes).
        """
        vacio = valor is None or (isinstance(valor, str) and not valor.strip()) \
            or (isinstance(valor, (list, tuple)) and not valor)

        if vacio:
            if self.requerido:
                return None, f'{self.etiqueta} es obligatorio.'
            return ([] if self.es_multivalor else None), ''

        try:
            return self._convertir(valor), ''
        except ValueError as ex:
            return None, str(ex)

    def _convertir(self, valor):
        tipo = self.tipo

        if tipo in (TIPO_TEXTO, TIPO_TEXTO_LARGO, TIPO_TELEFONO):
            return str(valor).strip()

        if tipo == TIPO_EMAIL:
            texto = str(valor).strip()
            if '@' not in texto or '.' not in texto.split('@')[-1]:
                raise ValueError(f'{self.etiqueta} no es un correo válido.')
            return texto

        if tipo == TIPO_URL:
            texto = str(valor).strip()
            if not texto.startswith(('http://', 'https://')):
                raise ValueError(f'{self.etiqueta} debe empezar con http:// o https://.')
            return texto

        if tipo == TIPO_NUMERO:
            try:
                return int(str(valor).strip())
            except (TypeError, ValueError):
                raise ValueError(f'{self.etiqueta} debe ser un número entero.')

        if tipo == TIPO_DECIMAL:
            try:
                # Se guarda como string: un float en JSON pierde precisión y
                # estos campos suelen ser importes.
                return str(Decimal(str(valor).strip().replace(',', '.')))
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError(f'{self.etiqueta} debe ser un número.')

        if tipo == TIPO_BOOLEANO:
            if isinstance(valor, bool):
                return valor
            return str(valor).strip().lower() in ('1', 'true', 'on', 'si', 'sí', 'yes')

        if tipo == TIPO_FECHA:
            return self._a_iso(valor, solo_fecha=True)

        if tipo == TIPO_FECHA_HORA:
            return self._a_iso(valor, solo_fecha=False)

        if tipo == TIPO_SELECCION:
            texto = str(valor).strip()
            if texto not in self.lista_opciones():
                raise ValueError(f'{self.etiqueta}: "{texto}" no está entre las opciones.')
            return texto

        if tipo == TIPO_SELECCION_MULTIPLE:
            crudos = valor if isinstance(valor, (list, tuple)) else [valor]
            permitidas = self.lista_opciones()
            elegidas = []
            for v in crudos:
                texto = str(v).strip()
                if not texto:
                    continue
                if texto not in permitidas:
                    raise ValueError(f'{self.etiqueta}: "{texto}" no está entre las opciones.')
                elegidas.append(texto)
            return elegidas

        return str(valor).strip()

    def _a_iso(self, valor, solo_fecha):
        if isinstance(valor, datetime):
            return valor.date().isoformat() if solo_fecha else valor.isoformat()
        if isinstance(valor, date):
            return valor.isoformat()
        texto = str(valor).strip().replace('T', ' ')
        formatos = ('%Y-%m-%d', '%d/%m/%Y') if solo_fecha else \
                   ('%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M')
        for fmt in formatos:
            try:
                parseada = datetime.strptime(texto, fmt)
                return parseada.date().isoformat() if solo_fecha else parseada.isoformat()
            except ValueError:
                continue
        esperado = 'AAAA-MM-DD' if solo_fecha else 'AAAA-MM-DD HH:MM'
        raise ValueError(f'{self.etiqueta} debe tener el formato {esperado}.')


class RegistroPersonalizado(ModeloBase):
    """Una fila de un objeto personalizado. Los valores viven en `datos`."""
    objeto = models.ForeignKey(
        ObjetoPersonalizado, on_delete=models.CASCADE, related_name='registros',
        verbose_name='Objeto'
    )
    datos = models.JSONField(default=dict, verbose_name='Datos')

    class Meta:
        verbose_name = 'Registro personalizado'
        verbose_name_plural = 'Registros personalizados'
        ordering = ('-id',)
        indexes = [
            # GIN sobre el JSONB: sin esto, filtrar por un campo custom hace
            # scan completo de la tabla.
            GinIndex(fields=['datos'], name='objetos_registro_datos_gin'),
            models.Index(fields=['objeto', 'status'], name='objetos_registro_obj_st'),
        ]

    def __str__(self):
        return self.etiqueta_visible()

    def etiqueta_visible(self):
        """Texto con el que se identifica el registro en listados y selectores.

        Toma el primer campo de texto con valor; si no hay ninguno, cae al id
        para no mostrar una fila sin nombre.
        """
        for campo in self.objeto.campos_de_listado():
            valor = self.datos.get(campo.nombre)
            if valor not in (None, '', []):
                return str(valor)[:120]
        return f'{self.objeto.nombre_singular} #{self.pk}'

    def valores_para_listado(self):
        """Pares (campo, valor formateado) de las columnas del listado."""
        salida = []
        for campo in self.objeto.campos_de_listado():
            salida.append({'campo': campo, 'valor': self.valor_formateado(campo)})
        return salida

    def valor_formateado(self, campo):
        valor = self.datos.get(campo.nombre)
        if valor in (None, '', []):
            return ''
        if campo.tipo == TIPO_BOOLEANO:
            return 'Sí' if valor else 'No'
        if campo.es_multivalor and isinstance(valor, list):
            return ', '.join(str(v) for v in valor)
        return str(valor)


class AsociacionRegistro(ModeloBase):
    """Relación entre dos registros de cualquier objeto.

    Equivale al Association Management de GoHighLevel: permite armar
    "Propiedad ← pertenece a → Cliente" sin definir ForeignKeys nuevas.
    """
    origen = models.ForeignKey(
        RegistroPersonalizado, on_delete=models.CASCADE, related_name='asociaciones_salientes',
        verbose_name='Registro de origen'
    )
    destino = models.ForeignKey(
        RegistroPersonalizado, on_delete=models.CASCADE, related_name='asociaciones_entrantes',
        verbose_name='Registro de destino'
    )
    etiqueta = models.CharField(
        max_length=80, blank=True, default='', verbose_name='Tipo de relación',
        help_text='Cómo se llama el vínculo. Ej: "pertenece a", "es titular de".'
    )

    class Meta:
        verbose_name = 'Asociación entre registros'
        verbose_name_plural = 'Asociaciones entre registros'
        unique_together = (('origen', 'destino', 'etiqueta'),)

    def __str__(self):
        vinculo = self.etiqueta or 'se relaciona con'
        return f'{self.origen.etiqueta_visible()} {vinculo} {self.destino.etiqueta_visible()}'

    def clean(self):
        if self.origen_id and self.origen_id == self.destino_id:
            raise ValidationError({'destino': 'Un registro no se puede asociar consigo mismo.'})
