import json
from datetime import datetime
from functools import reduce

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.shortcuts import render, redirect
from area_geografica.models import *
from django.http import JsonResponse, HttpResponse

from core.funciones import convertir_fecha
from core.funciones_api import traerApiPersona

def consultas(request):
    if request.method == 'GET':
        if 'action' in request.GET:
            action = request.GET['action']
            try:
                if action == 'paises':
                    try:
                        lista = []
                        pais = Pais.objects.filter(status=True).order_by('nombre')
                        for p in pais:
                            lista.append([p.id, p.nombre])
                        return JsonResponse({'result': 'ok', 'lista': lista})
                    except Exception as ex:
                        return JsonResponse({"result": "bad", "mensaje": u"Error al obtener los datos."})

                if action == 'provincias':
                    try:
                        pais = Pais.objects.get(pk=request.GET['id'])
                        lista = []
                        for provincia in pais.provincia_set.filter(status=True).order_by('nombre'):
                            lista.append([provincia.id, provincia.nombre])
                        return JsonResponse({'result': 'ok', 'lista': lista})
                    except Exception as ex:
                        return JsonResponse({"result": "bad", "mensaje": u"Error al obtener los datos."})

                if action == 'cantones':
                    try:
                        provincia = Provincia.objects.get(pk=request.GET['id'])
                        lista = []
                        for canton in provincia.ciudad_set.filter(status=True).order_by('nombre'):
                            lista.append([canton.id, canton.nombre])
                        return JsonResponse({'result': 'ok', 'lista': lista})
                    except Exception as ex:
                        return JsonResponse({"result": "bad", "mensaje": u"Error al obtener los datos."})

                if action == 'parroquias':
                    try:
                        canton = Ciudad.objects.get(pk=request.GET['id'])
                        lista = []
                        for parroquia in canton.parroquia_set.filter(status=True).order_by('nombre'):
                            lista.append([parroquia.id, parroquia.nombre])
                        return JsonResponse({'result': 'ok', 'lista': lista})
                    except Exception as ex:
                        return JsonResponse({"result": "bad", "mensaje": u"Error al obtener los datos."})

                if action == 'buscarlocalidad':
                    try:
                        q = request.GET['q'].upper().strip().replace(',', ' ').replace('-', ' ').strip()
                        s = q.split()
                        qsubicacion = Ciudad.objects.filter(
                            status=True,
                            provincia__status=True,
                            provincia__pais__status=True
                        ).order_by('nombre', 'provincia__nombre')
                        if len(s) >= 1:
                            # Realizamos una consulta dinámica utilizando 'reduce' para aplicar Q objects con el operador OR (|)
                            # para cada palabra en la entrada del usuario (q).
                            filter_q = reduce(lambda x, y: x | y, [Q(nombre__icontains=word) | Q(provincia__nombre__icontains=word) | Q(provincia__pais__nombre__icontains=word) for word in s])
                            qsubicacion = qsubicacion.filter(filter_q).distinct()
                        data = {
                            "result": "ok",
                            "results": [{
                                "id": x.id,
                                "name": x.nombre,
                                "provincia": x.provincia.nombre,
                                "pais": x.provincia.pais.nombre,
                                'prefijo': x.provincia.pais.codigotelefono
                            } for x in qsubicacion[:50]]  # Limitamos los resultados a 50
                        }
                        return JsonResponse(data)
                    except Exception as ex:
                        pass

            except Exception as ex:
                return JsonResponse({"result": "bad", "mensaje": f"Error al obtener los datos. {ex}"})
