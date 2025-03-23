import json
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.views import View

from area_geografica.models import Provincia, Ciudad, Pais
from autenticacion.models import Usuario
from django.http import JsonResponse, HttpResponse


class ConsultasAjax(View):
    def get(self, request, *args, **kwargs):
        try:
            accion = kwargs['accion']

            if accion == 'consultar-prefijo-celular-por-pais':
                id = request.GET['id'].lower()
                model = (request.GET.get('model') or '').lower()
                if model == 'ciudad':
                    pais = Ciudad.objects.get(id=id).provincia.pais
                else:
                    pais = Pais.objects.get(id=id)
                codigo = pais.codigotelefono or ""
                if len(codigo) > 0 and not codigo.startswith("+"):
                    codigo = "+{}".format(codigo)
                return JsonResponse({"prefijo": codigo})

            if accion == 'consultar-area-geografica':
                id = request.GET['id'].lower()
                carga = request.GET['carga'].lower()
                seleccionado = json.loads(request.GET.get('seleccionado') or '{}')

                provinciasHtml = ''
                ciudadesHtml = ''

                provinciaSelected = int(seleccionado.get("provinciaSelected") or 0)
                ciudadSelected = int(seleccionado.get("ciudadSelected") or 0)

                if carga == 'pais':
                    provincias = Provincia.objects.filter(status=True, pais_id=id).order_by('nombre')
                    for p in provincias:
                        provinciasHtml += '<option value="{}" {}>{}</option>'.format(p.id, "", p.nombre)
                    if provinciaSelected and provincias.filter(id=provinciaSelected).exists():
                        ciudades = Ciudad.objects.filter(status=True, provincia_id=provinciaSelected).order_by('nombre')
                        for p in ciudades:
                            ciudadesHtml += '<option value="{}" {}>{}</option>'.format(p.id,
                                                                                         "",
                                                                                         p.nombre)

                if carga == 'provincia':
                    ciudades = Ciudad.objects.filter(status=True, provincia_id=id).order_by('nombre')
                    for p in ciudades:
                        ciudadesHtml += '<option value="{}" {}>{}</option>'.format(p.id,
                                                                                     "",
                                                                                     p.nombre)

                return JsonResponse({"provinciasHtml": provinciasHtml, "ciudadesHtml": ciudadesHtml})


            if accion == 'consultarusername':
                username = request.GET['username'].lower()
                pk = request.GET.get('pk', '0') or 0
                val = ''
                buscado = '"{}"'.format(username)
                if Usuario.objects.filter(username=username).exclude(pk=pk).exists():
                    val = Usuario.objects.get(pk=pk).username if Usuario.objects.filter(pk=pk).exists() else ""
                    state = True
                else:
                    state = False
                response = JsonResponse({'state': state, 'val': val, 'buscado': buscado})
                return HttpResponse(response.content)

            if accion == 'buscarusuarios':
                q = request.GET["q"]
                modelo = Usuario.objects.filter(Q(is_active=True) & (Q(first_name__icontains=q) |
                                                                     Q(last_name__icontains=q) |
                                                                     Q(documento__icontains=q) |
                                                                     Q(username__icontains=q)))
                resp = {
                    "results": [
                        {'id': str(cr.pk), 'text': cr.__str__()} for
                        cr in modelo
                    ]
                }
                return JsonResponse(resp, safe=False)

            if accion == 'consultarcedula':
                documento = request.GET['documento']
                pk = request.GET.get('pk', '0') or 0
                val = ''
                buscado = '"{}"'.format(documento)
                if Usuario.objects.filter(documento=documento).exclude(pk=pk).exists():
                    val = Usuario.objects.get(pk=pk).documento if Usuario.objects.filter(
                        pk=pk).exists() else ""
                    state = True
                else:
                    state = False
                response = JsonResponse({'state': state, 'val': val, 'buscado': buscado})
                return HttpResponse(response.content)

            if accion == 'consultarcedulaadmin':
                cedula = request.GET['cedula']
                if Usuario.objects.filter(documento=cedula).exists():
                    state = True
                else:
                    state = False
                response = JsonResponse({'state': state})
                return HttpResponse(response.content)

            if accion == 'duplicado':
                c = Usuario.objects.filter(username=request.GET['username'].lower()).count()
                if c > 0:
                    respuesta = True
                else:
                    respuesta = False
                response = JsonResponse({'respuesta': respuesta})
                return HttpResponse(response.content)

            if accion == 'duplicado-mail':
                email = request.GET['mail']
                if request.user.is_authenticated:
                    model = Usuario.objects.filter(email=email, is_active=True).exclude(
                        email=request.user.email)
                else:
                    model = Usuario.objects.filter(email=email, is_active=True)
                if model.exists():
                    state = True
                else:
                    state = False
                response = JsonResponse({'respuesta': state})
                return HttpResponse(response.content)

            if accion == 'duplicado-documento':
                documento = request.GET['documento']
                if request.user.is_authenticated:
                    model = Usuario.objects.filter(documento=documento, is_active=True).exclude(documento=request.user.documento)
                else:
                    model = Usuario.objects.filter(documento=documento, is_active=True)
                if model.exists():
                    state = True
                else:
                    state = False
                response = JsonResponse({'respuesta': state})
                return HttpResponse(response.content)

        except Exception as ex:
            response = JsonResponse({'state': False, 'error': str(ex)})
            return HttpResponse(response.content)

    def post(self, request, *args, **kwargs):
        try:
            action = request.POST['action']

        except Exception as ex:
            return HttpResponse(json.dumps({'state': False, 'error': str(ex)}))
