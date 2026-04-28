import json
from datetime import datetime

from babel.dates import format_date
from django.contrib.humanize.templatetags.humanize import intcomma
from django.core import signing
from django import template
from django.template.defaultfilters import stringfilter

from django.utils.html import format_html
from django.template.defaultfilters import floatformat
from autenticacion.models import Usuario
from seguridad.models import ModuloGrupo, Modulo, GroupModulo


register = template.Library()

@register.filter
def encrypt_id(value):
    """Envuelve un id entero en un token firmado, apto para query strings.
    Uso: ?sesion={{ sesion.id|encrypt_id }}"""
    from core.funciones import encrypt_sesion_id
    return encrypt_sesion_id(value)


@register.filter
def currency(value):
    """
    Convierte un valor en formato monetario con separadores de miles y dos decimales.
    """
    value = floatformat(value, 2)  # Asegura que tenga dos decimales
    value = intcomma(value)  # Agrega separadores de miles
    return format_html(f"${value}")

@register.filter
def divisible(value, arg):
    """Divide el valor por el argumento"""
    try:
        return float(value) / float(arg)
    except (ValueError, ZeroDivisionError):
        return 0

def callmethod(obj, methodname):
    method = getattr(obj, methodname)
    if "__callArg" in obj.__dict__:
        ret = method(*obj.__callArg)
        del obj.__callArg
        return ret
    return method()


def args(obj, arg):
    if "__callArg" not in obj.__dict__:
        obj.__callArg = []
    obj.__callArg.append(arg)
    return obj


register.filter("call", callmethod)
register.filter("args", args)


def encrypt(value):
    myencrip = ""
    if type(value) is int:
        value = str(value)
    i = 1
    for c in value.zfill(20):
        myencrip = myencrip + chr(int(44450 / 350) - ord(c) + int(i / int(9800 / 4900)))
        i = i + 1
    return myencrip

register.filter("encrypt", encrypt)

@register.filter(is_safe=True)
@stringfilter
def truncatechars_middle(value, arg):
    try:
        ln = int(arg)
    except ValueError:
        return value
    if len(value) <= ln:
        return value
    else:
        return '{}...{}'.format(value[:ln//2], value[-((ln+1)//2):])


@register.filter
def get_encrypt(values):
    try:
        return signing.dumps(values, compress=True)
    except Exception as ex:
        return ""


@register.filter
def get_url_vars(path, dict_url_vars=""):
    try:
        dict_url_vars_completo = dict_url_vars or ""
        dict_url_vars_completo = json.loads(get_decrypt(dict_url_vars_completo.replace("dict_url_vars=", "")))
        dict_url_vars_completo = dict_url_vars_completo.get(path) or ""
        return "{}?{}".format(path, dict_url_vars_completo)
    except Exception as ex:
        return path

@register.filter
def split(val, sep=","):
    return val.split(sep)

@register.filter
def ordernarLista(lista):
    return sorted(lista)


@register.filter
def get_tipo_percent(self, name):
    return getattr(self, 'tipo_' + name)


@register.filter
def get_decrypt(cyphertxt):
    try:
        return signing.loads(cyphertxt)
    except Exception as ex:
        return ""


@register.filter
def convert_float_to_js(value):
    return str(value).replace(',', '.')


@register.filter
def get_color_tipo(val):
    COLOR_TIPO = (
        (1, "#767777"),
        (2, "#29B6F6"),
        (3, "#F39C12"),
        (4, "#138D75"),
    )
    return dict(COLOR_TIPO)[int(val)]


@register.simple_tag
def ver_valor_dict(dicionario, llave):
    return dicionario.get(llave)


@register.simple_tag
def ver_valor_dict_str(dicionario, llave, default):
    return str(dicionario.get(llave) or default)


@register.filter
def get_modulos(request):
    data = {}
    user = Usuario.objects.get(username=request.user.username)
    data['grupos'] = ModuloGrupo.objects.filter(status=True, modulos__id__in=list(
        GroupModulo.objects.filter(status=True, group__in=user.groups.all()).values_list('modulos__id'))).order_by(
        'prioridad')
    modulos = Modulo.objects.filter(url=request.path)
    if modulos.exists():
        if data['grupos'].filter(modulos__in=modulos, status=True).exists():
            data["group"] = data['grupos'].filter(modulos__in=modulos, status=True).first().nombre
    return data


@register.filter('startswith')
def startswith(text, starts):
    if isinstance(text, str):
        return text.lower().startswith(starts.lower())
    return False


@register.simple_tag
def traducir_permiso(value):
    valor = str(value).lower()
    es_permiso_de_django = 'can add' in valor or 'can view' in valor or 'can change' in valor or 'can delete' in valor
    if es_permiso_de_django:
        return ' '.join(valor.replace("can", "Puede") \
                        .replace('add', 'Agregar') \
                        .replace('view', 'Ver') \
                        .replace('delete', 'Eliminar') \
                        .replace('change', 'Modificar').split(' ')[0:2])
    return value


def calendarbox(var, dia):
    return var[dia]

def filter_fecha_turno(qs, dia):
    dias = {
        7: 1,
        6: 7,
        5: 6,
        4: 5,
        3: 4,
        2: 3,
        1: 2
    }
    return qs.filter(fecha_turno__week_day=dias[dia])

def calendarboxdetails(var, dia):
    lista = var[dia]
    result = []
    for x in lista:
        b = [x.split(',')[0], x.split(',')[1]]
        result.append(b)
    return result

register.filter("calendarbox", calendarbox)
register.filter("calendarboxdetails", calendarboxdetails)
register.filter("filter_fecha_turno", filter_fecha_turno)


from django.core.files.storage import default_storage

@register.simple_tag
def get_image_path(value):
    path = default_storage.path(value)
    return path


@register.simple_tag
def traducir_mes(value):
    return ' '.join(str(value).lower().replace('january', 'Ene') \
                    .replace('february', 'Feb') \
                    .replace('march', 'Mar') \
                    .replace('april', 'Abr') \
                    .replace('may', 'May') \
                    .replace('june', 'Jun') \
                    .replace('july', 'Jul') \
                    .replace('august', 'Ago') \
                    .replace('september', 'Sep') \
                    .replace('october', 'Oct') \
                    .replace('november', 'Nov') \
                    .replace('december', 'Dic').split(' ')[0:2])

@register.simple_tag
def traducir_mes_completo(value):
    return ' '.join(str(value).lower().replace('january', 'Enero') \
                    .replace('february', 'Febrero') \
                    .replace('march', 'Marzo') \
                    .replace('april', 'Abril') \
                    .replace('may', 'Mayo') \
                    .replace('june', 'Junio') \
                    .replace('july', 'Julio') \
                    .replace('august', 'Agosto') \
                    .replace('september', 'Septiembre') \
                    .replace('october', 'Octubre') \
                    .replace('november', 'Noviembre') \
                    .replace('december', 'Diciembre').split(' ')[0:2])


def solo_caracteres(texto):
    acentos = [u'á', u'é', u'í', u'ó', u'ú', u'Á', u'É', u'Í', u'Ó', u'Ú', u'ñ', u'Ñ']
    alfabeto = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z', '.', '/', '#', ',', ' ']
    resultado = ''
    for letra in texto:
        if letra in alfabeto:
            resultado += letra
        elif letra in acentos:
            if letra == u'á':
                resultado += 'a'
            elif letra == u'é':
                resultado += 'e'
            elif letra == u'í':
                resultado += 'i'
            elif letra == u'ó':
                resultado += 'o'
            elif letra == u'ú':
                resultado += 'u'
            elif letra == u'Á':
                resultado += 'A'
            elif letra == u'É':
                resultado += 'E'
            elif letra == u'Í':
                resultado += 'I'
            elif letra == u'Ó':
                resultado += 'O'
            elif letra == u'Ú':
                resultado += 'U'
            elif letra == u'Ñ':
                resultado += 'N'
            elif letra == u'ñ':
                resultado += 'n'
        else:
            resultado += '?'
    return resultado


register.filter("solo_caracteres", solo_caracteres)


@register.filter(name='comma_to_dot')
def comma_to_dot(value):
    return str(value).replace(',', '.')


def fecha_natural(fecha=datetime.now().date()):
    # Para mostrar todo el formato usar:format='log'
    format_custom = "d 'de' MMMM 'del' y"
    return format_date(fecha, format=format_custom, locale='es')

register.filter("fecha_natural", fecha_natural)


# ─────────────────────────────────────────────────────────────────────
# Formato WhatsApp: *negrita* _cursiva_ ~tachado~ ```código``` + URLs
# Aplicar como `{{ mensaje.mensaje|whatsapp_format }}` en cualquier
# template que muestre texto recibido/enviado por WhatsApp.
# ─────────────────────────────────────────────────────────────────────
import re as _re_wa
from django.utils.html import escape as _esc_wa
from django.utils.safestring import mark_safe as _safe_wa


_WA_CODE_BLOCK = _re_wa.compile(r'```([\s\S]+?)```')
_WA_BOLD       = _re_wa.compile(r'(?<!\w)\*([^\*\n]+?)\*(?!\w)')
_WA_ITALIC     = _re_wa.compile(r'(?<!\w)_([^_\n]+?)_(?!\w)')
_WA_STRIKE     = _re_wa.compile(r'(?<!\w)~([^~\n]+?)~(?!\w)')
_WA_INLINE_CODE = _re_wa.compile(r'`([^`\n]+?)`')
_WA_URL        = _re_wa.compile(r'(https?://[^\s<>"]+)')


@register.filter(is_safe=True)
@stringfilter
def whatsapp_format(value):
    """Renderiza texto plano con formato estilo WhatsApp:
    *negrita*, _cursiva_, ~tachado~, ```código```, `inline`, URLs y
    saltos de línea. Escape HTML primero para prevenir XSS, después
    aplica los reemplazos sobre el HTML escapado.
    """
    if not value:
        return ''
    txt = _esc_wa(value)
    txt = _WA_CODE_BLOCK.sub(
        lambda m: f'<pre class="wa-code">{m.group(1)}</pre>', txt
    )
    txt = _WA_INLINE_CODE.sub(r'<code class="wa-inline-code">\1</code>', txt)
    txt = _WA_BOLD.sub(r'<strong>\1</strong>', txt)
    txt = _WA_ITALIC.sub(r'<em>\1</em>', txt)
    txt = _WA_STRIKE.sub(r'<del>\1</del>', txt)
    txt = _WA_URL.sub(
        r'<a href="\1" target="_blank" rel="noopener" class="wa-link">\1</a>', txt
    )
    txt = txt.replace('\n', '<br>')
    return _safe_wa(txt)

