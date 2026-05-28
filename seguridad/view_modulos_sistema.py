import json
import sys
from datetime import date
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.template.loader import get_template

from core.funciones import addData, mi_paginador, secure_module, log, paginador
from core.funciones_adicionales import ordenar_modulos_url, salva_logs
from seguridad.forms import ModuloForm
from seguridad.models import Modulo, ModuloGrupo
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
                elif action == 'extraer_urls':
                    from fastchatdj.urls import urls_sistema
                    nuevas = []
                    existentes_urls = set(model.objects.values_list('url', flat=True))
                    for u in urls_sistema:
                        if not u.get("sub_urls"):
                            continue
                        for idx, su in enumerate(u["sub_urls"]):
                            mod_url = "/{}{}".format(u["url"], su["url"])
                            if mod_url in existentes_urls:
                                continue
                            mod_obj = model.objects.create(
                                orden=idx,
                                nombre=su["nombre"],
                                url=mod_url,
                            )
                            existentes_urls.add(mod_url)
                            nuevas.append(mod_obj.id)
                    log(f"Extracted {len(nuevas)} new URLs from sistema", request, "add")
                    return JsonResponse({
                        'error': False,
                        'creadas': len(nuevas),
                        'message': f"{len(nuevas)} new URL(s) added." if nuevas else "No new URLs to add."
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

        criterio, filtros, url_vars =  request.GET.get('criterio', ''), Q(status=True), ''
        ister, homologacion, postulate = request.GET.get('ister',''), request.GET.get('homologacion',''), request.GET.get('postulate','')
        usadas = request.GET.get('usadas', '')
        orden = request.GET.get('orden', 'id_desc')

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

        qs_modulos = model.objects.filter(filtros).prefetch_related('modulogrupo_set').distinct()
        data["list_count"] = qs_modulos.count()
        data["url_vars"] = url_vars
        from datetime import datetime, timedelta
        data["umbral_reciente"] = datetime.now() - timedelta(days=7)
        ids_usadas_set = set(
            x for x in ModuloGrupo.objects.filter(status=True).values_list('modulos__id', flat=True).distinct() if x
        )
        data["ids_usadas"] = ids_usadas_set
        paginador(request, qs_modulos.order_by(order_field), 20, data, url_vars)
        return render(request, 'seguridad/modulossistema/listado.html', data)
