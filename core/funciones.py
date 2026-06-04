import json
from datetime import time, timedelta
import random

from dateutil.relativedelta import relativedelta
from django.contrib.admin.models import DELETION, ADDITION, CHANGE, LogEntry
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage, InvalidPage
from django.core import signing
from django.db.models import Value, F, QuerySet
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect
from seguridad.models import *
from datetime import date
from django.db import transaction
from .constantes import NOMBRE_MONEDA, SIMBOLO_MONEDA
from .funciones_adicionales import round_num_dec
from django.core.cache import cache

import unicodedata

unicode = str


def remover_caracteres_especiales_unicode(cadena):
    return cadena.replace(u'ñ', u'n').replace(u'Ñ', u'N').replace(u'Á', u'A').replace(u'á', u'a').replace(u'É',
                                                                                                          u'E').replace(
        u'é', u'e').replace(u'Í', u'I').replace(u'í', u'i').replace(u'Ó', u'O').replace(u'ó', u'o').replace(u'Ú',
                                                                                                            u'U').replace(
        u'ú', u'u').replace(u'ü', u'u').replace(u'Ü', u'U').replace(u'°', u'_').replace(u'º', u'_').replace('[',
                                                                                                            '').replace(
        ']', '').replace('{', '').replace('}', '').replace('-', '')


def null_to_numeric(valor, decimales=None):
    if decimales:
        return round((valor if valor else 0), decimales)
    return valor if valor else 0


def codigo_ramdon():
    x = range(10)
    codigo = list(x)
    return "".join([str(_) for _ in random.sample(codigo, 6)])


def codigoRandomLetDig(N=10):
    import random
    import string
    return ''.join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(N))


def null_to_decimal(valor, decimales=None):
    if valor:
        if decimales:
            if decimales > 0:
                return float(Decimal(valor if valor else 0).quantize(
                    Decimal('.' + ''.zfill(decimales - 1) + '1')) if valor else 0)
            else:
                return float(Decimal(valor if valor else 0).quantize(Decimal('0')))
    return valor if valor else 0

def default_expira_10_min():
    return timezone.now() + relativedelta(minutes=10)

def convertir_fecha(s):
    if ':' in s:
        sep = ':'
    elif '-' in s:
        sep = '-'
    else:
        sep = '/'
    return date(int(s.split(sep)[2]), int(s.split(sep)[1]), int(s.split(sep)[0]))


def convertir_hora(s):
    if ':' in s:
        sep = ':'
    return time(int(s.split(sep)[0]), int(s.split(sep)[1]))


def convertir_fecha_invertida(s):
    if ':' in s:
        sep = ':'
    elif '-' in s:
        sep = '-'
    else:
        sep = '/'
    return date(int(s.split(sep)[0]), int(s.split(sep)[1]), int(s.split(sep)[2]))


def convertir_fecha_invertida__mes_dia_ano(s):
    if ':' in s:
        sep = ':'
    elif '-' in s:
        sep = '-'
    else:
        sep = '/'
    return date(int(s.split(sep)[2].split(' ')[0]), int(s.split(sep)[0]), int(s.split(sep)[1]))


def convertir_fecha_invertida_dia_mes_ano(s):
    if ':' in s:
        sep = ':'
    elif '-' in s:
        sep = '-'
    else:
        sep = '/'
    return date(int(s.split(sep)[2]), int(s.split(sep)[1]), int(s.split(sep)[0]))


def pagination2(request, list_qs, cantidad):
    page = request.GET.get('page', 1)
    paginator = Paginator(list_qs, cantidad)
    paginas = []
    primera_pagina = False
    ultima_pagina = False
    try:
        list_qs = paginator.page(page)
    except PageNotAnInteger:
        list_qs = paginator.page(1)
    except EmptyPage:
        list_qs = paginator.page(paginator.num_pages)
    return list_qs


def rangos_paginado(p, pagina):
    left = p - 4
    right = p + 4
    if left < 1:
        left = 1
    if right > pagina.paginator.num_pages:
        right = pagina.paginator.num_pages
    pagina.paginas = range(left, right + 1)
    pagina.primera_pagina = True if left > 1 else False
    pagina.ultima_pagina = True if right < pagina.paginator.num_pages else False
    pagina.ellipsis_izquierda = left - 1
    pagina.ellipsis_derecha = right + 1


def paginador_api(request, list_qs, cantidad, *values, functionDataListado=None):
    data = {}
    if cantidad <= 0:
        cantidad = 1
    paging = MiPaginador(list_qs, cantidad)
    p = 1
    try:
        if 'page' in request.GET:
            p = int(request.GET['page'])
        data['siguiente'] = p + 1
        page = paging.page(p)
    except:
        page = paging.page(p)
    paging.desde = p if p == 1 else cantidad * p - (cantidad - 1)
    paging.hasta = cantidad if p == 1 else cantidad * p
    if paging.hasta > paging.total:
        paging.hasta = paging.total
    if paging.total == 0:
        paging.desde = 0
    data['listado'] = page.object_list
    data['pageHasNext'] = pageHasNext = page.has_next()
    data['pageNextPag'] = pageNextPag = page.next_page_number() if pageHasNext else 0
    data['dataJsonPaginacion'] = {"hasNext": pageHasNext, "nextPag": pageNextPag}

    data["paginas"] = []
    if paging.num_pages > 5:
        if paging.primera_pagina:
            data["paginas"].append(
                {
                    "page": 1,
                    "isActive": False,
                    "texto": str(1)
                }
            )
            data["paginas"].append(
                {
                    "page": paging.ellipsis_izquierda,
                    "isActive": True,
                    "texto": "..."
                }
            )
        for pagenumber in paging.paginas:
            data["paginas"].append(
                {
                    "page": pagenumber,
                    "isActive": pagenumber == page.number,
                    "texto": str(pagenumber)
                }
            )
        if paging.ultima_pagina:
            data["paginas"].append(
                {
                    "page": paging.ellipsis_derecha,
                    "isActive": True,
                    "texto": "..."
                }
            )
            data["paginas"].append(
                {
                    "page": paging.num_pages,
                    "isActive": False,
                    "texto": str(paging.num_pages)
                }
            )
    else:
        for pagenumber in paging.paginas:
            data["paginas"].append(
                {
                    "page": pagenumber,
                    "isActive": pagenumber == page.number,
                    "texto": str(pagenumber)
                }
            )
    if functionDataListado:
        functionDataListado(data)
    else:
        data["listado"] = list(data["listado"].values(*values) if len(values) > 0 else data["listado"].values())
    return data


def paginador_old(request, list_qs, cantidad, data, url_vars=''):
    if cantidad <= 0:
        cantidad = 1
    paging = MiPaginador(list_qs, cantidad)
    p = 1
    try:
        if 'page' in request.GET:
            p = int(request.GET['page'])
        data['siguiente'] = p + 1
        page = paging.page(p)
    except:
        page = paging.page(p)
    if not "page=" in url_vars:
        url_vars += "&page={}".format(p)
    paging.desde = p if p == 1 else cantidad * p - (cantidad - 1)
    paging.hasta = cantidad if p == 1 else cantidad * p
    if paging.hasta > paging.total:
        paging.hasta = paging.total
    if paging.total == 0:
        paging.desde = 0
    data['paging'] = paging
    data['rangospaging'] = paging.rangos_paginado(p)
    data['page'] = page
    data['listado'] = page.object_list
    data['pageHasNext'] = pageHasNext = page.has_next()
    data['pageNextPag'] = pageNextPag = page.next_page_number() if pageHasNext else 0
    data['dataJsonPaginacion'] = json.dumps({"hasNext": pageHasNext, "nextPag": pageNextPag})
    get_filtros_anteriores(request, data, url_vars, en_paginador=True)


def paginador(request, list_qs, cantidad, data, url_vars=''):
    """
    Paginación optimizada que cambia su comportamiento basado en el volumen de datos.
    Para consultas pesadas (>10K registros) solo muestra anterior/siguiente.
    """
    UMBRAL_CONSULTA_PESADA = 10000

    if cantidad <= 0:
        cantidad = 1

    try:
        page_number = max(1, int(request.GET.get('page', 1)))
    except (TypeError, ValueError):
        page_number = 1

    offset = (page_number - 1) * cantidad

    # Obtener total y verificar si es una consulta pesada
    is_queryset = isinstance(list_qs, QuerySet)

    if is_queryset:
        if not list_qs.exists():
            return _empty_response(data)
        total_query = list_qs.count()
    else:
        total_query = len(list_qs)
        if total_query == 0:
            return _empty_response(data)

    is_heavy_query = total_query > UMBRAL_CONSULTA_PESADA

    # Obtener registros de la página actual
    end_index = min(offset + cantidad, total_query)
    paginated_qs = list_qs[offset:end_index]

    # Verificar si hay página siguiente
    has_next = total_query > (offset + cantidad)
    has_previous = page_number > 1

    # Calcular desde y hasta
    desde = offset + 1 if paginated_qs else 0
    hasta = offset + len(paginated_qs)

    # Estructura de página
    class PageLike:
        def __init__(self, object_list, number, has_next, has_previous):
            self.object_list = object_list
            self.number = number
            self._has_next = has_next
            self._has_previous = has_previous

        def has_next(self):
            return self._has_next

        def has_previous(self):
            return self._has_previous

        def next_page_number(self):
            return self.number + 1 if self._has_next else None

    page = PageLike(
        object_list=paginated_qs,
        number=page_number,
        has_next=has_next,
        has_previous=has_previous
    )

    # Estructura de paginación
    if is_heavy_query:
        paging = {
            'total': total_query,
            'desde': desde,
            'hasta': hasta,
            'is_heavy_query': True,
            'paginas': [],
            'primera_pagina': False,
            'ultima_pagina': False
        }
    else:
        num_pages = (total_query + cantidad - 1) // cantidad
        rango = 5
        left = max(1, page_number - rango)
        right = min(num_pages, page_number + rango)

        paging = {
            'num_pages': num_pages,
            'paginas': list(range(left, right + 1)),
            'primera_pagina': left > 1,
            'ultima_pagina': right < num_pages,
            'ellipsis_izquierda': left - 1,
            'ellipsis_derecha': right + 1,
            'total': total_query,
            'desde': desde,
            'hasta': hasta,
            'is_heavy_query': False
        }

    # Actualizar data
    data.update({
        'page': page,
        'paging': paging,
        'listado': paginated_qs,
        'pageHasNext': has_next,
        'pageNextPag': page_number + 1 if has_next else 0,
        'dataJsonPaginacion': json.dumps({
            "hasNext": has_next,
            "nextPag": page_number + 1 if has_next else 0
        })
    })

    if "page=" not in url_vars:
        url_vars += f"&page={page_number}"

    return data


def _empty_response(data):
    """Helper function para manejar respuestas vacías"""
    data.update({
        'page': EmptyPage,
        'paging': {
            'paginas': [],
            'primera_pagina': False,
            'ultima_pagina': False,
            'total': 0,
            'desde': 0,
            'hasta': 0,
            'is_heavy_query': False
        },
        'listado': [],
        'pageHasNext': False,
        'pageNextPag': 0,
        'dataJsonPaginacion': json.dumps({"hasNext": False, "nextPag": 0})
    })
    return data


def get_filtros_anteriores(request, data, url_vars, en_paginador: bool = False):
    data["dict_url_vars"] = ""
    if en_paginador:
        if url_vars:
            try:
                dict_url_vars = json.loads(get_decrypt(request.GET.get('dict_url_vars'))[1]) if request.GET.get(
                    'dict_url_vars') else {}
                dict_url_vars[request.path] = url_vars
                d = json.dumps(dict_url_vars)
                data["dict_url_vars"] = "dict_url_vars={}".format(get_encrypt(d)[1])
            except Exception as ex:
                print(ex)
    elif request.GET.get("dict_url_vars"):
        data["dict_url_vars"] = "dict_url_vars={}".format(
            request.GET.get("dict_url_vars", "").replace("dict_url_vars=", ""))


def secure_module(f):
    from django.contrib import messages
    def new_f(*args, **kwargs):
        request = args[0]
        if request.user.is_superuser:
            return f(*args, **kwargs)
        if request.user.is_authenticated and request.user.is_staff:
            try:
                urls_validas = ['perfilpanel', 'panel']
                if request.path.replace('/', '') in urls_validas:
                    return f(*args, **kwargs)
                modulos_id = list(
                    GroupModulo.objects.filter(group__in=request.user.groups.all()).values_list('modulos__id',
                                                                                                flat=True))
                ms = Modulo.objects.filter(status=True, id__in=modulos_id).annotate(
                    url_2=Value(request.path, output_field=models.CharField()))
                if ms.filter(url_2__istartswith=F('url')).exists():
                    return f(*args, **kwargs)
                else:
                    messages.error(request, "No tienes acceso.")
                    return HttpResponseRedirect("/panel/")
            except Exception as ex:
                print(ex)
                if request.user.is_superuser:
                    messages.error(request, 'Método: {}, Error: {}'.format(request.method, str(ex)))
                return HttpResponseRedirect("/")
        else:
            return HttpResponseRedirect("/")

    return new_f


def generar_nombre(nombre, original):
    from django.utils.text import slugify
    ext = ""
    if original.find(".") > 0:
        ext = original[original.rfind("."):]
    return slugify("{} {}".format(nombre, datetime.now().strftime("%Y-%m-%d %H-%M"))) + ext.lower()


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[-1].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def export_to_excel(columnas=[], queryset=None, filename="reporte_excel", nombre_hoja="Hoja1"):
    from django.http import HttpResponse
    # df = pd.DataFrame(data=queryset, columns=columnas)
    # df.to_csv()
    # excel_file = IO()
    # xlwriter = pd.ExcelWriter(excel_file, engine='xlsxwriter')
    # df.to_excel(xlwriter, 'sheetname')
    # xlwriter.save()
    # xlwriter.close()
    # excel_file.seek(0)
    #
    # response = HttpResponse(excel_file.read(),
    #                         content_type='application/ms-excel vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    # # set the file name in the Content-Disposition header
    # response['Content-Disposition'] = 'attachment; filename={}.xlsx'.format(filename)
    # return response
    import xlwt
    from django.http import HttpResponse
    response = HttpResponse(content_type='application/ms-excel')
    response['Content-Disposition'] = 'attachment; filename="{}.xls"'.format(filename)
    wb = xlwt.Workbook(encoding='utf-8')
    ws = wb.add_sheet(nombre_hoja)
    columnas2 = list(columnas)
    columnas2.sort(key=len, reverse=True)
    col_width = 256 * len(columnas2[0])  # 20 characters wide
    # Sheet header, first row
    row_num = 0
    font_style = xlwt.XFStyle()
    font_style.font.bold = True

    columns = columnas
    for col_num in range(len(columns)):
        ws.col(col_num).width = col_width
        ws.write(row_num, col_num, columns[col_num], font_style)
    # Sheet body, remaining rows
    font_style = xlwt.XFStyle()
    rows = queryset
    for row in rows:
        row_num += 1
        for col_num in range(len(row)):
            ws.write(row_num, col_num, str(row[col_num] or ""), font_style)
    wb.save(response)
    return response


def get_datos_email_html(datos, userDestino, subject, template_name, archivo=[]):
    from fastchatdj.settings import EMAIL_HOST_USER
    from django.template.loader import render_to_string
    from django.utils.html import strip_tags
    confi = Configuracion.get_instancia()
    empresa = confi.nombre_empresa
    datos['empresa'] = empresa
    datos['correo'] = "innovateach@gmail.com"
    datos['nombreempresa'] = empresa
    html_message = render_to_string(template_name, datos)
    plain_message = strip_tags(html_message)
    from_email = empresa
    to = userDestino.email
    return {"subject": subject, "plain_message": plain_message, "from_email": from_email, "to": [to],
            "html_message": html_message, "archivos": archivo}


def custom_get_timezone(request, user=None):
    import pytz
    from fastchatdj.settings import TIME_ZONE
    if request.user.is_authenticated:
        return timezone.now().astimezone(pytz.timezone(TIME_ZONE))
    return timezone.now().astimezone(pytz.timezone(TIME_ZONE))


def addData(request, data):
    # Abrir la publickey para encriptar
    from fastchatdj import settings
    from fastchatdj.settings import BASE_DIR, URL_GENERAL
    from django.utils import timezone
    data['remotenameaddr'] = '%s' % (request.META['SERVER_NAME'])
    data['server_response'] = SERVER_RESPONSE = '207'
    data["URL_GENERAL"] = URL_GENERAL
    data["campos_no_mostrados"] = []
    data["full_url"] = full_url = request.path + "?" + "&".join(["{}={}".format(k, v) for k, v in request.GET.items()])
    data["full_url_hash"] = get_encrypt(full_url)[1]
    confi = Configuracion.get_instancia()
    from django.contrib.sessions.models import Session
    hoy = custom_get_timezone(request)
    hora_actual = hoy.time()
    # WEB PUSH
    webpush_settings = getattr(settings, 'WEBPUSH_SETTINGS', {})
    # ------FILTRO HECHOS EN LOS LISTADOS
    data['dict_url_vars_input'] = mark_safe(
        '<input type="hidden" name="dict_url_vars" id="id_dict_url_vars" value="{}" />'.format(
            request.GET.get('dict_url_vars') or ""))
    if request.GET.get('dict_url_vars'):
        try:
            dict_url_vars_completo = request.GET.get('dict_url_vars') or "{}"
            dict_url_vars_completo = json.loads(get_decrypt(dict_url_vars_completo)[1])
            data['dict_url_vars_completo'] = dict_url_vars_completo.get(request.path) or ""
        except Exception as ex:
            print(ex)
    # -.---WEB PUSH----
    data['fecha_actual'] = hoy.date()
    data['other_action'] = request.GET.get('other-action')
    data['hoy'] = hoy.strftime('%d/%M/%Y %H:%m')
    data['dominio_reunion'] = 'meet.jit.si'
    data['confi'] = confi
    data['favicon'] = confi.ico.url if confi.ico else ""
    data['logo'] = confi.logo_sistema.url if confi.logo_sistema else ""
    data['fondo_perfil'] = confi.fondo_perfil.url if confi.fondo_perfil else ""
    data['bannerlog'] = confi.banner_login.url if confi.banner_login else ""
    data['nombreempresa'] = confi.nombre_empresa
    data['telefonoempresa'] = confi.telefono if confi.telefono else ''
    data['alias'] = confi.alias
    data['NOMBRE_MONEDA'] = NOMBRE_MONEDA
    data['SIMBOLO_MONEDA'] = SIMBOLO_MONEDA
    data["DOMINIO_DEL_SISTEMA"] = request.build_absolute_uri('/')[:-1].strip("/")
    data['hora_actual'] = hora_actual
    data['hoy'] = datetime.now().date()
    data['hoy_str'] = str(datetime.now().date())
    if 'user_anterior' in request.session:
        data["sesion_anterior"] = True
    if request.user.is_authenticated:
        # Notificaciones para el dropdown del topbar (base.html). Sin esto el
        # popup queda siempre vacío. Mostramos las 5 últimas no leídas y el
        # total no leído para el badge.
        try:
            from seguridad.models import Notificacion as _Notif
            _qs_not = _Notif.objects.filter(
                destinatario=request.user, leido=False, status=True,
            ).order_by('-fecha_registro')
            data['totalnot'] = _qs_not.count()
            data['listnotification'] = list(_qs_not[:5])
        except Exception:
            data['totalnot'] = 0
            data['listnotification'] = []
        if request.user.cambio_clave and request.path != '/changepass/':
            data['activar_cambio_clave'] = request.user.cambio_clave
        if not 'perfilprincipal' in request.session:
            request.session['perfilprincipal'] = request.user.get_perfil_per()
        data['perfilprincipal'] = request.session['perfilprincipal'] if 'perfilprincipal' in request.session else None
        get_filtros_anteriores(request, data, None)
        data["fecha_session_expira"] = (request.session.model.objects.get(
            pk=request.session.session_key).expire_date - timezone.now()).seconds
        if not request.session.exists(request.session.session_key):
            request.session.create()
        # if not UsuarioConectado.objects.values('id').filter(sesion=Session.objects.get(session_key=request.session.session_key), user_id=request.user.id).exists():
        #     ucc = UsuarioConectado.objects.get_or_create(sesion=Session.objects.get(session_key=request.session.session_key), user_id=request.user.id)[0]
        # else:
        #     ucc = UsuarioConectado.objects.filter(sesion=Session.objects.get(session_key=request.session.session_key), user_id=request.user.id).first()
        # ucc.fecha_conexion = timezone.now()
        # ucc.dispositivo = request.META['HTTP_USER_AGENT']
        # ucc.ip = str(request.ipAdd)
        # ucc.save()
        data['ruta_val'] = request.path
        if request.user.es_administrativo():
            data['gruposUserLogueado'] = ", ".join(list(request.user.groups.all().values_list('name', flat=True)))
            data["modulos_id"] = modulos_id = list(
                GroupModulo.objects.filter(group__in=request.user.groups.all()).values_list('modulos__id', flat=True))
            data['grupos'] = ModuloGrupo.objects.filter(status=True, modulos__id__in=modulos_id).order_by(
                'prioridad').distinct()
            modulos = Modulo.objects.annotate(url_2=Value(request.path, output_field=models.CharField())).filter(
                url_2__istartswith=F('url'))
            if modulos.exists():
                if data['grupos'].filter(modulos__in=modulos, status=True).exists():
                    data["group"] = data['grupos'].filter(modulos__in=modulos, status=True).first().nombre
            if 'ruta_lista' not in request.session:
                request.session['ruta_lista'] = [['/panel/', 'Inicio']]
            rutalista = request.session['ruta_lista']
            if request.path and request.method == 'GET':
                if Modulo.objects.values('url').filter(url=request.path).exists():
                    modulo = Modulo.objects.values("url", "nombre").filter(url=request.path).first()
                    url = [modulo['url'], modulo['nombre']]
                    if rutalista.count(url) <= 0:
                        if rutalista.__len__() >= 4:
                            b = rutalista[1]
                            rutalista.remove(b)
                            rutalista.append(url)
                        else:
                            rutalista.append(url)
                    request.session['ruta_lista'] = rutalista
                    data["url_back"] = '/'
                    url_back = [data['url_back']]
                    request.session['url_back'] = url_back
            data["ruta_lista"] = rutalista


def redirectAfterPostGet(request):
    dict_url_vars = request.GET.get('dict_url_vars') or request.POST.get('dict_url_vars') or ""
    if dict_url_vars:
        try:
            dict_url_vars = json.loads(get_decrypt(dict_url_vars)[1]).get(request.path) or ""
        except Exception as ex:
            print(ex)
    salida = "?action=add&" if '_add' in request.POST else request.path + "?"
    return salida + "{}".format(dict_url_vars)


class MiPaginador(Paginator):
    def __init__(self, object_list, per_page, orphans=0, allow_empty_first_page=True, rango=5):
        super(MiPaginador, self).__init__(object_list, per_page, orphans=orphans,
                                          allow_empty_first_page=allow_empty_first_page)
        self.rango = rango
        self.paginas = []
        self.primera_pagina = False
        self.ultima_pagina = False
        self.total = object_list.count()
        self.desde = 0
        self.hasta = 0

    def rangos_paginado(self, pagina):
        left = pagina - self.rango
        right = pagina + self.rango
        if left < 1:
            left = 1
        if right > self.num_pages:
            right = self.num_pages
        self.paginas = range(left, right + 1)
        self.primera_pagina = True if left > 1 else False
        self.ultima_pagina = True if right < self.num_pages else False
        self.ellipsis_izquierda = left - 1
        self.ellipsis_derecha = right + 1


def ip_client_address(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[-1].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_encrypt(values):
    try:
        return True, signing.dumps(values, compress=True)
    except Exception as ex:
        return False, str(ex)


def get_decrypt(cyphertxt):
    try:
        return True, signing.loads(cyphertxt)
    except Exception as ex:
        return False, str(ex)


# --- Identificadores opacos para URLs (firmados, no cifrado fuerte) ---

def encrypt_sesion_id(pk):
    """Devuelve un token opaco a partir de un id entero. Uso en links /?sesion=<token>."""
    if pk in (None, ''):
        return ''
    ok, token = get_encrypt(int(pk))
    return token if ok else ''


def decrypt_sesion_id(token, default=None):
    """Inversa de encrypt_sesion_id. Si el token no parece firmado, intenta int() directo
    (tolerante con tabs abiertas / links viejos en claro)."""
    if token in (None, ''):
        return default
    if isinstance(token, int):
        return token
    ok, valor = get_decrypt(token)
    if ok:
        try:
            return int(valor)
        except (TypeError, ValueError):
            return default
    # Fallback: id crudo
    try:
        return int(token)
    except (TypeError, ValueError):
        return default


WA_SESION_ACTIVA_KEY = 'wa_sesion_id'


def leer_sesion_id(request, default=None, persistir=True):
    """Resuelve el id de sesión activa para la request.

    Prioridad:
      1. Querystring 'sesion'/'sesion_id' (deep-link). Acepta token cifrado o
         id crudo. Si viene, además fija la sesión global en request.session.
      2. Selección global del usuario en request.session[WA_SESION_ACTIVA_KEY].
         Valor 0/None significa "Todas las sesiones" → se devuelve default.
    """
    raw = request.GET.get('sesion') or request.GET.get('sesion_id') or ''
    sid = decrypt_sesion_id(raw, default=None)
    if sid is not None:
        if persistir and hasattr(request, 'session'):
            request.session[WA_SESION_ACTIVA_KEY] = sid
        return sid
    if hasattr(request, 'session'):
        gsid = request.session.get(WA_SESION_ACTIVA_KEY)
        if gsid:
            return gsid
    return default


def set_wa_sesion_activa(request, sid):
    """Fija la sesión global del usuario. sid entero válido, o 0 para 'Todas'."""
    try:
        sid = int(sid or 0)
    except (TypeError, ValueError):
        sid = 0
    request.session[WA_SESION_ACTIVA_KEY] = sid
    return sid


def postFormJson(request, nombre_post_aud, Forms=(), link_listado='', varurl=""):
    res_json = []
    SERVER_ERROR = "Error, inténtelo nuevamente"
    FORM_ERROR = "Datos inconsistentes"
    form_is_valid = False
    ##
    try:
        with transaction.atomic():
            for form in Forms:
                form_is_valid = form.is_valid()

            if form_is_valid:
                for form in Forms:
                    form.save()
                    res_json.append(
                        {'error': False, "to": link_listado + '?pk=' + get_encrypt(form.instance.id)[1] + varurl})
            else:
                for form in Forms:
                    res_json.append(
                        {'error': True, "form": [{k: v[0]} for k, v in form.errors.items()], "message": FORM_ERROR}
                    )
    except Exception as ex:
        res_json.append({'error': True, "message": SERVER_ERROR})
    return JsonResponse(res_json, safe=False)


def ret_dos_decimales(value):
    from django.core.exceptions import ValidationError
    if value < 0:
        raise ValidationError("No válido")
    return round(value, 2)


def val_foto_size(value):
    from django.core.exceptions import ValidationError
    filesize = value.size

    if filesize > 1572864:
        raise ValidationError("El tamaño máximo de archivo que se puede cargar es 1.5MB")
    else:
        return value


def db_table_exists(table):
    try:
        from django.db import connection
        cursor = connection.cursor()
        table_names = [x.name for x in list(connection.introspection.get_table_list(cursor))]
    except Exception as ex:
        print("unable to determine if the table '%s' exists" % table)
    else:
        return table in table_names


def salva_auditoria(request, model, action, nombre, qs_nuevo=None, qs_anterior=None):
    from seguridad.models import AudiUsuarioTabla
    import json
    arr = []
    anterior = {}
    nuevo = {}
    if qs_anterior:
        anterior["fields"] = {}
        for x in qs_anterior:
            for k, v in x.items():
                anterior["fields"][k] = str(v)
        anterior["pk"] = qs_anterior[0]["id"]
        anterior["fields"]["__ff_detalle_ff__"] = "ANTERIOR"
        anterior["model"] = "{}.{}".format(model._meta.app_label, model._meta.model_name)
        arr.append(anterior)
    if qs_nuevo:
        nuevo["fields"] = {}
        for x in qs_nuevo:
            for k, v in x.items():
                nuevo["fields"][k] = str(v)
        nuevo["pk"] = qs_nuevo[0]["id"]
        nuevo["fields"]["__ff_detalle_ff__"] = "NUEVO"
        nuevo["model"] = "{}.{}".format(model._meta.app_label, model._meta.model_name)
        arr.append(nuevo)
    data_json = json.dumps(arr)
    user = request.user
    auditusuariotabla = AudiUsuarioTabla(usuario_id=user.id,
                                         modelo=model,
                                         registroname=nombre,
                                         accion=action,
                                         datos_json=data_json,
                                         ip=str(request.ipAdd))
    if 'user_anterior' in request.session:
        auditusuariotabla.usuario_admin_id = int(request.session['user_anterior'])
    auditusuariotabla.save()


def merge_values(values):
    import itertools
    grouped_results = itertools.groupby(values, key=lambda value: value['id'])
    merged_values = []
    for k, g in grouped_results:
        groups = list(g)
        merged_value = {}
        for group in groups:
            for key, val in group.items():
                if not merged_value.get(key):
                    merged_value[key] = val
                elif val != merged_value[key]:
                    if isinstance(merged_value[key], list):
                        if val not in merged_value[key]:
                            merged_value[key].append(val)
                    else:
                        old_val = merged_value[key]
                        merged_value[key] = [old_val, val]
        merged_values.append(merged_value)
    return merged_values


def mi_paginador(request, list_qs, cantidad, data):
    paging = MiPaginador(list_qs, cantidad)
    p = 1
    try:
        if 'page' in request.GET:
            p = int(request.GET['page'])
        data['siguiente'] = p + 1
        page = paging.page(p)
    except:
        page = paging.page(p)

    paging.desde = p if p == 1 else cantidad * p - (cantidad - 1)
    paging.hasta = cantidad if p == 1 else cantidad * p
    if paging.hasta > paging.total:
        paging.hasta = paging.total
    if paging.total == 0:
        paging.desde = 0
    data['paging'] = paging
    data['rangospaging'] = paging.rangos_paginado(p)
    data['page'] = page
    data['listado'] = page.object_list


def codnombre(nombres, apellidos, user_pk=0):
    lnombres = nombres.split(' ')
    lapellidos = apellidos.split(' ')
    codnombre = "{}{}".format(lnombres[0].lower()[0], str(lapellidos[0].lower()))
    if Usuario.objects.filter(username__icontains=codnombre).exclude(pk=user_pk).exists():
        count2 = Usuario.objects.filter(username__icontains=codnombre).count() + 1
        codnombre = "{}{}{}".format(lnombres[0].lower()[0], str(lapellidos[0].lower()), count2)
    return codnombre


def formatear_nombres(cadena):
    import re
    return re.sub("\s+", " ", cadena.strip())


def renderizar_texto_dinamico(template_str, variables_contexto):
    from django.template import Template, Context
    try:
        django_template = Template(template_str)
        contexto = Context(variables_contexto)
        return django_template.render(contexto)
    except Exception as e:
        return f"Error processing template: {e}"


def log(mensaje, request, accion, user=None, obj=None):
    if accion == "del":
        logaction = DELETION
    elif accion == "add":
        logaction = ADDITION
    else:
        logaction = CHANGE
    LogEntry.objects.log_action(
        user_id=request.user.id if not user else user.id,
        content_type_id=None,
        object_id=obj,
        object_repr='',
        action_flag=logaction,
        change_message=unicode(mensaje))


def save_log_entry(mensaje, request, accion, user=None, obj=None):
    from django.contrib.contenttypes.models import ContentType
    if accion in ("del", "delete"):
        logaction = DELETION
    elif accion == "add":
        logaction = ADDITION
    else:
        logaction = CHANGE
    content_type = obj and ContentType.objects.get_for_model(obj)
    LogEntry.objects.log_action(
        user_id=request and request.user and request.user.is_authenticated and request.user.id or user and user.id or 1,
        content_type_id=content_type and content_type.id, object_id=obj and obj.id, object_repr=str(obj),
        action_flag=logaction, change_message=unicode(mensaje)
    )


def enviar_mensaje_bot_telegram(mensaje):
    import requests
    json_arr = []
    try:
        pass
        # from seguridad.models import  Configuracion
        # confi_ = Configuracion.get_instancia()
        # api = confi_.tokentelegram if confi_ else '1239752846:AAE5DIDlCcUT5MFqHN339OV7G5UOK0rNhNM'
        # chats = ["1078235324", "857267973",]
        # for x in chats:
        #     data = {'chat_id': x, 'text': mensaje, 'parse_mode': 'HTML'}
        #     url = "https://api.telegram.org/bot{}/sendMessage".format(api)
        #     json_arr.append(requests.post(url, data).json())
    except Exception as ex:
        print("TELEGRAM ERROR" + str(ex))
    return json_arr


class Dict2Obj():
    def __init__(self, dicc):
        if isinstance(dicc, dict):
            for k, v in dicc.items():
                setattr(self, str(k), v)


def logCron(proceso, detalle, exito=False):
    # Obtiene la fecha y hora actuales
    ahora = timezone.now()

    # Calcula el tiempo límite de las últimas 3 horas
    hace_tres_horas = ahora - timedelta(hours=3)

    # Verifica si ya existe un registro con el mismo proceso, detalle y en las últimas 3 horas
    existe_log = CronLogEjecucion.objects.filter(
        proceso=proceso,
        detalle=detalle,
        fecha=ahora.date(),
        hora__gte=hace_tres_horas.time()  # Hora mayor o igual al límite de 3 horas atrás
    ).exists()

    # Solo crea el registro si no existe uno igual en las últimas 3 horas
    if not existe_log:
        CronLogEjecucion.objects.create(
            proceso=proceso,
            detalle=detalle,
            conexito=exito
        )
        # Aviso por correo solo ante fallo (y solo cuando es un log nuevo, así la
        # deduplicación de 3h evita spam). No agrega crons: es event-driven.
        if not exito:
            _notificar_fallo_cron(proceso, detalle)


def _notificar_fallo_cron(proceso, detalle):
    """Manda un correo a los responsables cuando un proceso/cron falla.
    Best-effort: si el correo falla, no rompe el logueo del cron."""
    try:
        from django.conf import settings
        from django.core.mail import send_mail
        destinatarios = getattr(settings, 'CHATBOT_ERROR_NOTIFY_EMAILS', []) or []
        if not destinatarios:
            return
        asunto = f'[fastchat] Falló el proceso: {proceso}'
        cuerpo = (
            f'El proceso "{proceso}" reportó un fallo.\n\n'
            f'Detalle:\n{detalle}\n\n'
            f'Fecha: {timezone.now():%Y-%m-%d %H:%M}\n\n'
            f'Aviso automático. Se deduplica: máximo 1 correo cada 3h por el mismo error.'
        )
        send_mail(asunto, cuerpo, settings.DEFAULT_FROM_EMAIL, destinatarios, fail_silently=True)
    except Exception:
        pass


def notificacion(titulo, cuerpo, destinatario, url, prioridad, tipo=1, request=None):
    from seguridad.models import Notificacion
    notificacion = Notificacion(titulo=titulo, cuerpo=cuerpo,
                                destinatario=destinatario, url=url,
                                prioridad=prioridad,
                                tipo=tipo,
                                fecha_hora_visible=datetime.now() + timedelta(days=1))
    if request:
        notificacion.save(request)
    else:
        notificacion.save()

def rate_limit(limit=10, seconds=60):
    def _apply(view_func):
        def _wrapped(request, *args, **kwargs):
            ip = request.META.get("REMOTE_ADDR")
            key = f"rate:{ip}"
            requests = cache.get(key, 0)

            if requests >= limit:
                return JsonResponse({"error": "Demasiadas solicitudes"}, status=429)

            cache.set(key, requests + 1, timeout=seconds)
            return view_func(request, *args, **kwargs)
        return _wrapped
    return _apply