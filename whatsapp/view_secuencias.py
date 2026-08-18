"""Secuencias drip — CRUD de secuencias/pasos e inscripciones de contactos."""
import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, paginador, secure_module, log
from .funciones_secuencias import cancelar_manual, inscribir_contacto
from .models import (
    Contacto, EtiquetaContacto, InscripcionSecuencia, PasoSecuencia,
    SecuenciaWhatsApp, SegmentoContacto,
)


def _guardar_pasos(secuencia, pasos_json):
    try:
        pasos = json.loads(pasos_json or '[]')
    except ValueError:
        raise ValueError('Formato de pasos inválido.')
    if not pasos:
        raise ValueError('La secuencia necesita al menos un paso.')
    ids_recibidos = []
    for idx, p in enumerate(pasos, start=1):
        mensaje = (p.get('mensaje') or '').strip()
        if not mensaje:
            raise ValueError(f'El paso {idx} no tiene mensaje.')
        try:
            espera = int(p.get('espera_horas') or 0)
        except (TypeError, ValueError):
            espera = 0
        if espera < 1:
            raise ValueError(f'El paso {idx} necesita una espera de al menos 1 hora.')
        paso_id = p.get('id')
        if paso_id:
            PasoSecuencia.objects.filter(pk=paso_id, secuencia=secuencia).update(
                orden=idx, espera_horas=espera, mensaje=mensaje,
            )
            ids_recibidos.append(int(paso_id))
        else:
            nuevo = PasoSecuencia.objects.create(
                secuencia=secuencia, orden=idx, espera_horas=espera, mensaje=mensaje,
            )
            ids_recibidos.append(nuevo.id)
    secuencia.pasos.filter(status=True).exclude(id__in=ids_recibidos).update(status=False)


@login_required
@secure_module
def secuenciasView(request):
    data = {
        'titulo': 'Secuencias',
        'descripcion': 'Series de mensajes automáticos con esperas entre pasos (drip)',
        'ruta': request.path,
    }
    addData(request, data)

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            with transaction.atomic():
                if action == 'add':
                    nombre = (request.POST.get('nombre') or '').strip()
                    if not nombre:
                        return JsonResponse({'error': True, 'message': 'Nombre obligatorio.'})
                    etiqueta_id = request.POST.get('etiqueta_disparadora') or None
                    secuencia = SecuenciaWhatsApp.objects.create(
                        nombre=nombre,
                        descripcion=(request.POST.get('descripcion') or '').strip(),
                        activa=request.POST.get('activa') == 'on',
                        salir_al_responder=request.POST.get('salir_al_responder') == 'on',
                        etiqueta_disparadora_id=etiqueta_id,
                    )
                    _guardar_pasos(secuencia, request.POST.get('pasos_json'))
                    log(f'Secuencia {secuencia.nombre} creada', request, 'add', obj=secuencia.id)
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'change':
                    secuencia = SecuenciaWhatsApp.objects.get(pk=int(request.POST['pk']), status=True)
                    secuencia.nombre = (request.POST.get('nombre') or secuencia.nombre).strip()
                    secuencia.descripcion = (request.POST.get('descripcion') or '').strip()
                    secuencia.activa = request.POST.get('activa') == 'on'
                    secuencia.salir_al_responder = request.POST.get('salir_al_responder') == 'on'
                    secuencia.etiqueta_disparadora_id = request.POST.get('etiqueta_disparadora') or None
                    secuencia.save()
                    _guardar_pasos(secuencia, request.POST.get('pasos_json'))
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'delete':
                    secuencia = SecuenciaWhatsApp.objects.get(pk=int(request.POST['id']), status=True)
                    secuencia.status = False
                    secuencia.save()
                    secuencia.inscripciones.filter(estado='activa', status=True).update(
                        estado='cancelada_manual',
                    )
                    return JsonResponse({'error': False})

                if action == 'toggle_activa':
                    secuencia = SecuenciaWhatsApp.objects.get(pk=int(request.POST['id']), status=True)
                    secuencia.activa = not secuencia.activa
                    secuencia.save()
                    return JsonResponse({'error': False, 'activa': secuencia.activa})

                if action == 'inscribir':
                    secuencia = SecuenciaWhatsApp.objects.get(pk=int(request.POST['secuencia_id']), status=True)
                    contacto = Contacto.objects.get(pk=int(request.POST['contacto_id']), status=True)
                    inscripcion, mensaje = inscribir_contacto(secuencia, contacto)
                    return JsonResponse({'error': inscripcion is None, 'message': mensaje})

                if action == 'inscribir_segmento':
                    secuencia = SecuenciaWhatsApp.objects.get(pk=int(request.POST['secuencia_id']), status=True)
                    segmento = SegmentoContacto.objects.get(pk=int(request.POST['segmento_id']), status=True)
                    from .funciones_segmentos import queryset_segmento
                    inscritos = 0
                    omitidos = 0
                    for contacto in queryset_segmento(segmento):
                        inscripcion, _ = inscribir_contacto(secuencia, contacto)
                        if inscripcion is not None:
                            inscritos += 1
                        else:
                            omitidos += 1
                    return JsonResponse({
                        'error': False,
                        'message': f'{inscritos} contacto(s) inscritos, {omitidos} omitidos (ya inscritos o no elegibles).',
                    })

                if action == 'cancelar_inscripcion':
                    inscripcion = InscripcionSecuencia.objects.get(pk=int(request.POST['id']), status=True)
                    ok = cancelar_manual(inscripcion)
                    if not ok:
                        return JsonResponse({'error': True, 'message': 'La inscripción ya no está activa.'})
                    return JsonResponse({'error': False, 'message': 'Inscripción cancelada.'})

        except SecuenciaWhatsApp.DoesNotExist:
            return JsonResponse({'error': True, 'message': 'Secuencia no encontrada.'})
        except Contacto.DoesNotExist:
            return JsonResponse({'error': True, 'message': 'Contacto no encontrado.'})
        except ValueError as ex:
            return JsonResponse({'error': True, 'message': str(ex)})
        except Exception as ex:
            return JsonResponse({'error': True, 'message': f'Error: {ex}'})

    action_get = request.GET.get('action')

    if action_get == 'pasos':
        secuencia = SecuenciaWhatsApp.objects.get(pk=int(request.GET['id']), status=True)
        pasos = list(secuencia.pasos_activos().values('id', 'orden', 'espera_horas', 'mensaje'))
        return JsonResponse({'error': False, 'pasos': pasos})

    if action_get == 'inscripciones':
        secuencia = SecuenciaWhatsApp.objects.get(pk=int(request.GET['id']), status=True)
        inscripciones = (secuencia.inscripciones.filter(status=True)
                         .select_related('contacto')
                         .order_by('-id')[:200])
        filas = [{
            'id': i.id,
            'contacto': i.contacto.contacto_nombre or i.contacto.from_number,
            'numero': i.contacto.from_number,
            'estado': i.get_estado_display(),
            'estado_code': i.estado,
            'paso_actual': i.paso_actual,
            'proximo_envio': i.proximo_envio.strftime('%d/%m/%Y %H:%M') if i.proximo_envio else '—',
        } for i in inscripciones]
        return JsonResponse({'error': False, 'inscripciones': filas})

    if action_get == 'buscar_contactos':
        criterio = (request.GET.get('criterio') or '').strip()
        if len(criterio) < 3:
            return JsonResponse({'error': False, 'contactos': []})
        contactos = (Contacto.objects
                     .filter(status=True, opt_out=False, whatsapp_invalido=False)
                     .filter(Q(contacto_nombre__icontains=criterio) | Q(contacto_numero__icontains=criterio))
                     .select_related('sesion')[:10])
        filas = [{
            'id': c.id,
            'nombre': c.contacto_nombre or '(sin nombre)',
            'numero': c.contacto_numero,
            'sesion': c.sesion.nombre or c.sesion.session_id,
        } for c in contactos]
        return JsonResponse({'error': False, 'contactos': filas})

    criterio = (request.GET.get('criterio') or '').strip()
    qs = SecuenciaWhatsApp.objects.filter(status=True).annotate(
        total_pasos=Count('pasos', filter=Q(pasos__status=True), distinct=True),
        activas=Count('inscripciones', filter=Q(inscripciones__estado='activa', inscripciones__status=True), distinct=True),
        completadas=Count('inscripciones', filter=Q(inscripciones__estado='completada', inscripciones__status=True), distinct=True),
    )
    url_vars = ''
    if criterio:
        qs = qs.filter(Q(nombre__icontains=criterio) | Q(descripcion__icontains=criterio))
        data['criterio'] = criterio
        url_vars += f'&criterio={criterio}'
    listado = qs.order_by('nombre')
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    data['etiquetas_disponibles'] = EtiquetaContacto.objects.filter(
        status=True, usuario_creacion=request.user,
    ).order_by('nombre')
    data['segmentos_disponibles'] = SegmentoContacto.objects.filter(status=True).order_by('nombre')
    paginador(request, listado, 50, data, url_vars)
    return render(request, 'whatsapp/secuencias/listado.html', data)
