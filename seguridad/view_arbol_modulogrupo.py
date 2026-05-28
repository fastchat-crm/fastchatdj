import json
from datetime import date
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import render, redirect
from core.funciones import addData, salva_auditoria, secure_module
from seguridad.models import ModuloGrupo, Modulo
from django.contrib import messages


@login_required
@secure_module
def arbol_modulo_grupo(request):
    data = {'titulo': 'Grupos de Urls',
            'modulo': 'Grupos de Urls',
            'ruta': request.path,
            'ruta_val': request.path,
            'group': 'Seguridad',
            'fecha': str(date.today())
            }
    addData(request, data)
    model = ModuloGrupo


    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        if action == 'cambiar_lugar_grupo':

                try:
                    with transaction.atomic():
                        c_modulos = request.POST.getlist('c_modulos', [])
                        cambios = 0
                        for x in c_modulos:
                            cm = json.loads(x)
                            try:
                                pk_destino = int(cm.get("pk_destino") or 0)
                                pk_modulo = int(cm.get("pk_modulo") or 0)
                                orden_nuevo = int(cm.get("orden") or 0)
                            except (TypeError, ValueError):
                                continue
                            if pk_destino <= 0 or pk_modulo <= 0:
                                continue
                            mg_destino = ModuloGrupo.objects.filter(pk=pk_destino, status=True).first()
                            modulo = Modulo.objects.filter(pk=pk_modulo, status=True).first()
                            if not mg_destino or not modulo:
                                continue
                            grupos_actuales = set(ModuloGrupo.objects.filter(modulos=modulo, status=True).values_list('pk', flat=True))
                            if grupos_actuales == {pk_destino} and modulo.orden == orden_nuevo:
                                continue
                            if modulo.orden != orden_nuevo:
                                modulo.orden = orden_nuevo
                                modulo.save(request)
                            for mg_otro in ModuloGrupo.objects.filter(modulos=modulo, status=True).exclude(pk=pk_destino):
                                mg_otro.modulos.remove(modulo)
                            mg_destino.modulos.add(modulo)
                            cambios += 1
                        if cambios:
                            messages.success(request, f"{cambios} URL group assignment(s) updated.")
                        else:
                            messages.info(request, "No changes detected.")
                except ValueError as e:
                    messages.error(request, str(e))
                except Exception as ex:
                    messages.error(request, "An error occurred. Please try again.")

                return redirect(request.path)

    elif request.method == 'GET':

            modulos = ModuloGrupo.objects.filter(status=True).order_by('prioridad')
            data['listado'] = modulos
            return render(request, 'seguridad/modulogrupo/listado_arbol.html', data)
