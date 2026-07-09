import json
import sys
from datetime import date
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Count
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.template.loader import get_template

from core.funciones import addData, mi_paginador, secure_module, log, paginador
from core.funciones_adicionales import ordenar_modulos_url, salva_logs
from seguridad.forms import ModuloForm
from seguridad.models import Modulo, ModuloGrupo, GroupModulo
from django.contrib import messages


@login_required
@secure_module
def modulossistemaView(request):
    data = {'titulo': 'Mantenimiento de Url',
            'modulo': 'Url',
            'ruta': request.path,
            'fecha': str(date.today())
            }
    model = Modulo
    Formulario = ModuloForm
    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        try:
            with transaction.atomic():
                if action == 'add':
                    form = Formulario(request.POST, request=request)
                    if form.is_valid():
                        form.save()
                        log(f"Registro un nuevo modulo {form.instance.__str__()}", request, "add")
                        res_json.append({'error': False,
                                         "reload": True
                                         })
                    else:
                        res_json.append({'error': True,
                                             "form": [{k: v[0]} for k, v in form.errors.items()],
                                             "message": "Error en el formulario"
                                             })
                elif action == 'change':
                    modulo = model.objects.get(pk=int(request.POST['pk']))
                    form = Formulario(request.POST, request.FILES, instance=modulo,request=request)
                    if form.is_valid():
                        form.save()
                        log(f"Edito un modulo {form.instance.__str__()}", request, "change")
                        res_json.append({'error': False,
                                         "reload": True
                                         })
                    else:
                        res_json.append({'error': True,
                                             "form": [{k: v[0]} for k, v in form.errors.items()],
                                             "message": "Error en el formulario"
                                             })
                elif action == 'delete':
                    modulo = model.objects.get(pk=int(request.POST['id']))
                    modulo.status = False
                    modulo.save(request)
                    log(f"Elimino modulo {modulo.__str__()}", request, "delete")
                    messages.success(request, f"Registro Eliminado")
                    res_json = {"error": False}
                elif action == 'checkactivoister':
                    try:
                        pk, estado = request.POST['id'], request.POST['val']
                        mensaje = 'Activo' if estado == 'true' else 'Inactivo'
                        retorno = 1 if estado == 'true' else 2
                        qsbase = model.objects.get(pk=pk)
                        qsbase.ister = True if retorno == 1 else False
                        qsbase.save(request)
                        log(f"Modifico estado ister de modulo: {mensaje} - {qsbase.__str__()}", request, "change")
                        return HttpResponse(json.dumps({'result': True, 'mensaje': mensaje, 'retorno': retorno}))
                    except Exception as ex:
                        return HttpResponse(json.dumps({'result': False, 'mensaje': ex, 'retorno': 1}))
                elif action == 'checkactivohomo':
                    try:
                        pk, estado = request.POST['id'], request.POST['val']
                        mensaje = 'Activo' if estado == 'true' else 'Inactivo'
                        retorno = 1 if estado == 'true' else 2
                        qsbase = model.objects.get(pk=pk)
                        qsbase.homologacion = True if retorno == 1 else False
                        qsbase.save(request)
                        log(f"Modifico estado homologación de modulo: {mensaje} - {qsbase.__str__()}", request,
                            "change")
                        return HttpResponse(json.dumps({'result': True, 'mensaje': mensaje, 'retorno': retorno}))
                    except Exception as ex:
                        return HttpResponse(json.dumps({'result': False, 'mensaje': ex, 'retorno': 1}))
                elif action == 'checkactivopos':
                    try:
                        pk, estado = request.POST['id'], request.POST['val']
                        mensaje = 'Activo' if estado == 'true' else 'Inactivo'
                        retorno = 1 if estado == 'true' else 2
                        qsbase = model.objects.get(pk=pk)
                        qsbase.postulate = True if retorno == 1 else False
                        qsbase.save(request)
                        log(f"Modifico estado postulación de modulo: {mensaje} - {qsbase.__str__()}", request, "change")
                        return HttpResponse(json.dumps({'result': True, 'mensaje': mensaje, 'retorno': retorno}))
                    except Exception as ex:
                        return HttpResponse(json.dumps({'result': False, 'mensaje': ex, 'retorno': 1}))
                elif action == 'checkexternos':
                    try:
                        pk, estado = request.POST['id'], request.POST['val']
                        mensaje = 'Activo' if estado == 'true' else 'Inactivo'
                        retorno = 1 if estado == 'true' else 2
                        qsbase = model.objects.get(pk=pk)
                        qsbase.externo = True if retorno == 1 else False
                        qsbase.save(request)
                        log(f"Modifico estado postulación de modulo: {mensaje} - {qsbase.__str__()}", request, "change")
                        return HttpResponse(json.dumps({'result': True, 'mensaje': mensaje, 'retorno': retorno}))
                    except Exception as ex:
                        return HttpResponse(json.dumps({'result': False, 'mensaje': ex, 'retorno': 1}))
                elif action == 'act_descrip':
                    try:
                        with transaction.atomic():
                            filtro = model.objects.get(pk=int((request.POST['id'])))
                            filtro.descripcion = request.POST['valor']
                            filtro.save(request)
                            log(f"Actualizo descripción url {filtro.__str__()}", request, "change")
                            res_json.append({"result": "ok"})
                    except Exception as ex:
                        res_json.append({"error": True, "mensaje": u"Error al guardar los datos."})
                elif action == 'act_orden':
                    try:
                        filtro = model.objects.get(pk=int(request.POST['id']))
                        filtro.orden = int(request.POST['valor'])
                        filtro.save(request)
                        log(f"Actualizo orden url {filtro.__str__()}", request, "change")
                        return HttpResponse(json.dumps({'result': True, 'orden': filtro.orden}))
                    except (ValueError, TypeError):
                        return HttpResponse(json.dumps({'result': False, 'mensaje': 'Orden inválido'}))
                    except Exception as ex:
                        return HttpResponse(json.dumps({'result': False, 'mensaje': str(ex)}))
                elif action == 'guardar_grupos_modulo':
                    pk_modulo = int(request.POST.get('pk_modulo') or 0)
                    grupos_ids = [int(g) for g in request.POST.getlist('c_grupos', []) if g.isdigit()]
                    modulo = model.objects.filter(pk=pk_modulo, status=True).first()
                    if not modulo:
                        res_json.append({'error': True, 'message': 'Module not found.'})
                    else:
                        grupos_actuales = set(ModuloGrupo.objects.filter(modulos=modulo, status=True).values_list('pk', flat=True))
                        grupos_nuevos = set(grupos_ids)
                        a_agregar = grupos_nuevos - grupos_actuales
                        a_quitar = grupos_actuales - grupos_nuevos
                        for gid in a_agregar:
                            mg = ModuloGrupo.objects.filter(pk=gid, status=True).first()
                            if mg:
                                mg.modulos.add(modulo)
                        for gid in a_quitar:
                            mg = ModuloGrupo.objects.filter(pk=gid, status=True).first()
                            if mg:
                                mg.modulos.remove(modulo)
                        log(f"Synced groups for module {modulo.__str__()}: +{len(a_agregar)} / -{len(a_quitar)}", request, "change")
                        res_json.append({
                            'error': False,
                            'message': f"Groups updated (+{len(a_agregar)} / -{len(a_quitar)}).",
                            'reload': True
                        })
                elif action == 'extraer_urls':
                    from fastchatdj.urls import urls_sistema
                    seleccionadas = set(request.POST.getlist('c_urls'))
                    if not seleccionadas:
                        res_json.append({'error': True, 'message': 'Selecciona al menos una URL para importar.'})
                    else:
                        nuevas = []
                        existentes_urls = set(model.objects.values_list('url', flat=True))
                        for u in urls_sistema:
                            if not u.get("sub_urls"):
                                continue
                            for idx, su in enumerate(u["sub_urls"]):
                                mod_url = "/{}{}".format(u["url"], su["url"])
                                if mod_url in existentes_urls or mod_url not in seleccionadas:
                                    continue
                                mod_obj = model.objects.create(
                                    orden=idx,
                                    nombre=su["nombre"],
                                    url=mod_url,
                                )
                                existentes_urls.add(mod_url)
                                nuevas.append(mod_obj.id)
                        log(f"Importo {len(nuevas)} URLs nuevas del sistema", request, "add")
                        res_json.append({
                            'error': False,
                            'reload': True,
                            'message': f"{len(nuevas)} URL(s) importadas." if nuevas else "No había URLs nuevas para importar."
                        })
                elif action == 'depurar_urls':
                    from fastchatdj.urls import urls_sistema
                    ids = [int(x) for x in request.POST.getlist('c_modulos') if x.isdigit()]
                    if not ids:
                        res_json.append({'error': True, 'message': 'Selecciona al menos una URL para depurar.'})
                    else:
                        urls_diccionario = set()
                        for u in urls_sistema:
                            for su in (u.get("sub_urls") or []):
                                urls_diccionario.add("/{}{}".format(u["url"], su["url"]))
                        depuradas = 0
                        for filtro in model.objects.filter(pk__in=ids, status=True).exclude(url__in=urls_diccionario):
                            filtro.status = False
                            filtro.save(request)
                            log(f"Depuro URL huerfana {filtro.__str__()}", request, "delete")
                            depuradas += 1
                        res_json.append({
                            'error': False,
                            'reload': True,
                            'message': f"{depuradas} URL(s) depuradas." if depuradas else "No se depuró ninguna URL."
                        })
        except ValueError as ex:
            res_json.append({'error': True,
                             "message": str(ex)
                             })
        except Exception as ex:
            salva_logs(request, __file__, request.method,
                       action, type(ex).__name__,
                       'Error on line {}'.format(sys.exc_info()[-1].tb_lineno), ex)
            res_json.append({'error': True,
                             "message": "Intente Nuevamente"
                             })
        return JsonResponse(res_json, safe=False)
    elif request.method == 'GET':
        addData(request, data)
        if 'action' in request.GET:
            data["action"] = action = request.GET['action']
            if action == 'add':
                data["form"] = Formulario()
                template = get_template("seguridad/modulossistema/form.html")
                return JsonResponse({"result": True, 'data': template.render(data)})
            elif action == 'change':
                try:
                    data['id'] = id = int(request.GET['id'])
                    data['filtro'] = filtro = model.objects.get(pk=id)
                    form = Formulario(instance=filtro)
                    data['form'] = form
                    template = get_template("seguridad/modulossistema/form.html")
                    return JsonResponse({"result": True, 'data': template.render(data)})
                except Exception as ex:
                    pass
            elif action == 'ver':
                pk = int(request.GET['pk'])
                modulo = model.objects.get(pk=pk)
                data["pk"] = pk
                data["form"] = Formulario(instance=modulo, ver=True)
                return render(request, 'seguridad/modulossistema/form.html', data)
            elif action == 'previa_extraer_urls':
                from fastchatdj.urls import urls_sistema
                existentes_urls = set(model.objects.values_list('url', flat=True))
                grupos_urls = []
                for u in urls_sistema:
                    if not u.get("sub_urls"):
                        continue
                    pendientes = []
                    for su in u["sub_urls"]:
                        mod_url = "/{}{}".format(u["url"], su["url"])
                        if mod_url in existentes_urls:
                            continue
                        pendientes.append({'nombre': su["nombre"], 'url': mod_url})
                    if pendientes:
                        grupos_urls.append({'app': u.get("nombre") or u["url"], 'urls': pendientes})
                total_pendientes = sum(len(g['urls']) for g in grupos_urls)
                if not total_pendientes:
                    return JsonResponse({'result': False, 'message': 'No hay URLs nuevas para importar.'})
                data['grupos_urls'] = grupos_urls
                data['total_pendientes'] = total_pendientes
                template = get_template('seguridad/modulossistema/form_extraer_urls.html')
                return JsonResponse({'result': True, 'data': template.render(data)})
            elif action == 'previa_depurar_urls':
                from fastchatdj.urls import urls_sistema
                urls_diccionario = set()
                for u in urls_sistema:
                    for su in (u.get("sub_urls") or []):
                        urls_diccionario.add("/{}{}".format(u["url"], su["url"]))
                huerfanos = list(
                    model.objects.filter(status=True)
                    .exclude(url__in=urls_diccionario)
                    .order_by('url')
                )
                if not huerfanos:
                    return JsonResponse({'result': False, 'message': 'No hay URLs huérfanas: todas existen en el diccionario.'})
                grupos_huerfanos = {}
                for m in huerfanos:
                    seg = (m.url or '/').strip('/').split('/')[0] or '(raíz)'
                    grupos_huerfanos.setdefault(seg, []).append(m)
                data['grupos_huerfanos'] = [
                    {'app': k, 'modulos': v} for k, v in sorted(grupos_huerfanos.items())
                ]
                data['total_huerfanos'] = len(huerfanos)
                template = get_template('seguridad/modulossistema/form_depurar_urls.html')
                return JsonResponse({'result': True, 'data': template.render(data)})
            elif action == 'grupos_modulo':
                pk_modulo = int(request.GET.get('id') or 0)
                modulo = model.objects.filter(pk=pk_modulo, status=True).first()
                if not modulo:
                    return JsonResponse({'result': False, 'message': 'Module not found.'})
                grupos_actuales_ids = set(ModuloGrupo.objects.filter(modulos=modulo, status=True).values_list('pk', flat=True))
                data['modulo'] = modulo
                data['grupos'] = ModuloGrupo.objects.filter(status=True).order_by('prioridad', 'nombre')
                data['grupos_actuales_ids'] = grupos_actuales_ids
                template = get_template('seguridad/modulossistema/form_grupos.html')
                return JsonResponse({'result': True, 'data': template.render(data)})

        criterio, filtros, url_vars =  request.GET.get('criterio', ''), Q(status=True), ''
        ister, homologacion, postulate = request.GET.get('ister',''), request.GET.get('homologacion',''), request.GET.get('postulate','')
        usadas = request.GET.get('usadas', '')
        grupo_id = request.GET.get('grupo', '')
        rol_id = request.GET.get('rol', '')
        orden = request.GET.get('orden', 'id_desc')

        if grupo_id.isdigit():
            data['grupo_sel'] = int(grupo_id)
            url_vars += f'&grupo={grupo_id}'
            filtros = filtros & Q(modulogrupo__id=int(grupo_id), modulogrupo__status=True)
        if rol_id.isdigit():
            data['rol_sel'] = int(rol_id)
            url_vars += f'&rol={rol_id}'
            filtros = filtros & Q(groupmodulo__id=int(rol_id), groupmodulo__status=True)
        if usadas in ('1', '0'):
            data['usadas'] = usadas
            url_vars += f'&usadas={usadas}'
            ids_usadas = list(
                x for x in ModuloGrupo.objects.filter(status=True).values_list('modulos__id', flat=True).distinct() if x
            )
            if usadas == '1':
                filtros = filtros & Q(id__in=ids_usadas)
            else:
                filtros = filtros & ~Q(id__in=ids_usadas)
        if ister:
            data['ister'] = ister
            url_vars += f'&ister={ister}'
            if ister == '0':
                filtros = filtros & Q(ister=True)
            else:
                filtros = filtros & Q(ister=False)
        if homologacion:
            data['homologacion'] = homologacion
            url_vars += f'&homologacion={homologacion}'
            if homologacion == '0':
                filtros = filtros & Q(homologacion=True)
            else:
                filtros = filtros & Q(homologacion=False)
        if postulate:
            data['postulate'] = postulate
            url_vars += f'&postulate={postulate}'
            if postulate == '0':
                filtros = filtros & Q(postulate=True)
            else:
                filtros = filtros & Q(postulate=False)
        if criterio:
            filtros = filtros & (Q(nombre__icontains=criterio) | Q(url__icontains=criterio))
            data["criterio"] = criterio
            url_vars += '&criterio=' + criterio
        # modulossistema = model.objects.filter(status=True)
        # from isterpry.urls import urls_sistema
        # _urls_sistema = urls_sistema
        # for u in _urls_sistema:
        #     url = "/{}".format(u["url"])
        #     modulos = modulossistema.filter(url__startswith=url)
        #     if u["sub_urls"]:
        #         for su in u["sub_urls"]:
        #             mod_url = "/{}{}".format(u["url"], su["url"])
        #             if not modulos.filter(url=mod_url).exists():
        #                 orden = u["sub_urls"].index(su)
        #                 mod_obj = Modulo.objects.create(orden=orden, nombre=su["nombre"], url=mod_url)
        #                 log(f"Sistema creo modulo {mod_obj.__str__()}", request, "add")
        orden_map = {
            'id_desc': '-id',
            'id_asc': 'id',
            'nombre_asc': 'nombre',
            'nombre_desc': '-nombre',
            'fecha_asc': 'fecha_registro',
            'fecha_desc': '-fecha_registro',
        }
        order_field = orden_map.get(orden, '-id')
        data['orden'] = orden
        if orden != 'id_desc':
            url_vars += f'&orden={orden}'

        qs_modulos = (
            model.objects.filter(filtros)
            .prefetch_related('modulogrupo_set', 'groupmodulo_set__group')
            .annotate(roles_count=Count('groupmodulo', filter=Q(groupmodulo__status=True), distinct=True))
            .distinct()
        )
        data["list_count"] = qs_modulos.count()
        data["url_vars"] = url_vars
        from datetime import datetime, timedelta
        data["umbral_reciente"] = datetime.now() - timedelta(days=7)
        ids_usadas_set = set(
            x for x in ModuloGrupo.objects.filter(status=True).values_list('modulos__id', flat=True).distinct() if x
        )
        data["ids_usadas"] = ids_usadas_set
        data["grupos_filtro"] = ModuloGrupo.objects.filter(status=True).order_by('nombre')
        data["roles_filtro"] = GroupModulo.objects.filter(status=True).select_related('group').order_by('group__name')
        paginador(request, qs_modulos.order_by(order_field), 20, data, url_vars)
        return render(request, 'seguridad/modulossistema/listado.html', data)
