import json
from datetime import datetime
from decimal import Decimal


def remover_espacios_de_mas(valor: str) -> str:
    import re
    return re.sub("\s+", " ", (valor or "").strip())


def get_query_dataframe(using, query):
    import pandas as pd
    from django.db import connections
    with connections[using].cursor() as cursor:
        df = pd.read_sql(query, cursor.db.connection)
    return df


def listar_packages_python():
    import pkg_resources
    installed_packages = pkg_resources.working_set
    installed_packages_list = sorted(["%s==%s" % (i.key, i.version)
                                      for i in installed_packages])
    print("\n".join(installed_packages_list))

def customgetattr(object, name):
    tree = name.split(".")
    obj = object
    for t in tree:
        if hasattr(obj, t):
            obj = getattr(obj, t)
            obj = obj() if str(type(obj)) in ("<class 'method-wrapper'>", "<class 'method'>", "<class 'function'>") else obj
        else:
            obj = ""
            break
    return obj


def salva_logs(request, archivo, metodo, action, tipo, linea, descripcion):
    from seguridad.models import ErrorLog
    user = request.user
    errorlog = ErrorLog(usuario_id=user.id,
                        archivo=archivo,
                        metodo=metodo,
                        accion=action,
                        tipo=tipo,
                        linea=linea,
                        descripcion=descripcion,
                        fecha=datetime.now()
                        )
    errorlog.save()


def get_verbose_name(app_label, model):
    from django.apps import apps
    try:
        return apps.get_model(app_label, model)._meta.verbose_name
    except LookupError:
        return None


def get_app_label(app_label):
    from django.apps import apps
    try:
        return apps.get_app_config(app_label).verbose_name
    except LookupError:
        return None


def generar_name_id(nombre):
    from django.utils.text import slugify
    return slugify(nombre)


def listar_campos_tabla(modelo, schema='public'):
    descartar = (
    'id', 'status', 'fecha_registro', 'fecha_salida', 'hora_salida', 'razonsalida', 'usersalida',
    'fechasalida', 'horasalida')
    from django.db import connection
    query = "SELECT column_name FROM information_schema.columns WHERE table_schema = '{}' AND table_name   = '{}';".format(
        schema, modelo.objects.model._meta.db_table)
    cursor = connection.cursor()
    cursor.execute(query)
    campos = list([c[0] for c in cursor.fetchall() if not c[0] in descartar])
    return campos


def ordenar_modulos_url(data, qs_modulos, modulos_seleccionados=[]):
    from fastchatdj.urls import urls_sistema
    _urls_sistema = urls_sistema
    for u in _urls_sistema:
        url = "/{}".format(u["url"])  # /seguridad/usuarios
        modulos = qs_modulos.filter(url__startswith=url)
        if u["sub_urls"]:
            for su in u["sub_urls"]:
                mod_url = "/{}{}".format(u["url"], su["url"])  # /seguridad/modulo/grupo/
                if modulos.filter(url=mod_url).exists():
                    _urls_sistema[_urls_sistema.index(u)]["sub_urls"][u["sub_urls"].index(su)][
                        "orden"] = modulos.filter(
                        url=mod_url).first().orden
                    _urls_sistema[_urls_sistema.index(u)]["sub_urls"][u["sub_urls"].index(su)][
                        "color_icon"] = "text-blue"
                else:
                    _urls_sistema[_urls_sistema.index(u)]["sub_urls"][u["sub_urls"].index(su)]["orden"] = u[
                        "sub_urls"].index(su)

                _urls_sistema[_urls_sistema.index(u)]["sub_urls"][u["sub_urls"].index(su)]["modulo_seleccionado"] = str(
                    mod_url in modulos_seleccionados).lower()
            _urls_sistema[_urls_sistema.index(u)]["sub_urls"] = sorted(
                _urls_sistema[_urls_sistema.index(u)]["sub_urls"],
                key=lambda i: i['orden'])
            for su in u["sub_urls"]:
                mod_url = "/{}{}".format(u["url"], su["url"])
                dicJsTree = {
                    "icon": "fa fa-link fa-lg ",
                    "nombre": su["nombre"],
                    "url": mod_url,
                    "input_id": "url_{}_{}".format(u["sub_urls"].index(su) + 1, _urls_sistema.index(u) + 1),
                    "orden": u["sub_urls"].index(su) + 1,
                    "selected": mod_url in modulos_seleccionados
                }
                dicValue = {
                    "nombre": su["nombre"],
                    "url": mod_url,
                    "orden": u["sub_urls"].index(su) + 1,
                }
                _urls_sistema[_urls_sistema.index(u)]["sub_urls"][u["sub_urls"].index(su)]["dicJsTree"] = json.dumps(
                    dicJsTree)
                _urls_sistema[_urls_sistema.index(u)]["sub_urls"][u["sub_urls"].index(su)]["dicValue"] = json.dumps(
                    dicValue)
    data["urls_sistema"] = _urls_sistema


def round_num_dec(value, decimales=2):
    return Decimal(value).quantize(Decimal(10) ** (decimales*-1))
