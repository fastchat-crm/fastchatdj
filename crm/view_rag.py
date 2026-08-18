from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404

from core.funciones import addData, secure_module, log
from .models import RagColeccion, RagFuente, PerfilNegocioIA, ApiKeyIA


def _perfil_de(request):
    perfil = PerfilNegocioIA.objects.filter(usuario=request.user).first()
    if not perfil:
        perfil = PerfilNegocioIA.objects.create(usuario=request.user)
    return perfil


def _coleccion_de(request, pk):
    return get_object_or_404(
        RagColeccion, pk=int(pk), perfil__usuario=request.user, status=True,
    )


@login_required
@secure_module
def ragColeccionView(request):
    data = {
        'titulo': 'Conocimiento RAG',
        'descripcion': 'Colecciones de conocimiento por sesión: sube fuentes, indexa y asigna a tus números.',
        'modulo': 'CRM',
        'ruta': request.path,
        'fecha': str(date.today()),
    }
    addData(request, data)
    perfil = _perfil_de(request)

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            with transaction.atomic():
                if action == 'add_coleccion':
                    nombre = (request.POST.get('nombre') or '').strip()
                    if not nombre:
                        return JsonResponse({'error': True, 'message': 'El nombre es obligatorio.'})
                    apikey = None
                    if request.POST.get('apikey_id'):
                        apikey = ApiKeyIA.objects.filter(
                            pk=int(request.POST['apikey_id']), perfil=perfil, status=True,
                        ).first()
                    coleccion = RagColeccion(
                        perfil=perfil,
                        nombre=nombre[:150],
                        descripcion=(request.POST.get('descripcion') or '').strip(),
                        apikey=apikey,
                    )
                    coleccion.save(request)
                    log(f"Colección RAG creada: {coleccion.nombre}", request, "add", obj=coleccion.id)
                    return JsonResponse({'error': False, 'message': 'Colección creada.', 'id': coleccion.id})

                elif action == 'change_coleccion':
                    coleccion = _coleccion_de(request, request.POST['id'])
                    nombre = (request.POST.get('nombre') or '').strip()
                    if not nombre:
                        return JsonResponse({'error': True, 'message': 'El nombre es obligatorio.'})
                    coleccion.nombre = nombre[:150]
                    coleccion.descripcion = (request.POST.get('descripcion') or '').strip()
                    if request.POST.get('apikey_id'):
                        coleccion.apikey = ApiKeyIA.objects.filter(
                            pk=int(request.POST['apikey_id']), perfil=perfil, status=True,
                        ).first()
                    else:
                        coleccion.apikey = None
                    coleccion.save(request)
                    log(f"Colección RAG editada: {coleccion.nombre}", request, "change", obj=coleccion.id)
                    return JsonResponse({'error': False, 'message': 'Colección actualizada.'})

                elif action == 'delete_coleccion':
                    coleccion = _coleccion_de(request, request.POST['id'])
                    coleccion.status = False
                    coleccion.save(request)
                    coleccion.sesiones.update(rag_coleccion=None)
                    log(f"Colección RAG eliminada: {coleccion.nombre}", request, "del", obj=coleccion.id)
                    return JsonResponse({'error': False, 'message': 'Colección eliminada.'})

                elif action == 'add_fuente':
                    coleccion = _coleccion_de(request, request.POST['coleccion_id'])
                    tipo = int(request.POST.get('tipo') or 2)
                    fuente = RagFuente(
                        coleccion=coleccion,
                        tipo=tipo,
                        titulo=(request.POST.get('titulo') or '').strip()[:200],
                        enlace=(request.POST.get('enlace') or '').strip() if tipo == 1 else '',
                        texto=(request.POST.get('texto') or '').strip() if tipo == 3 else '',
                    )
                    if tipo == 2:
                        archivo = request.FILES.get('archivo')
                        if not archivo:
                            return JsonResponse({'error': True, 'message': 'Adjunta un archivo.'})
                        fuente.archivo = archivo
                    if tipo == 1 and not fuente.enlace:
                        return JsonResponse({'error': True, 'message': 'El enlace es obligatorio.'})
                    if tipo == 3 and not fuente.texto:
                        return JsonResponse({'error': True, 'message': 'El texto es obligatorio.'})
                    try:
                        fuente.full_clean(exclude=['coleccion'])
                    except ValidationError as ve:
                        return JsonResponse({'error': True, 'message': '; '.join(
                            f'{k}: {v[0]}' for k, v in ve.message_dict.items())})
                    fuente.save(request)
                    log(f"Fuente RAG agregada a {coleccion.nombre}: {fuente.nombre_visible()}",
                        request, "add", obj=coleccion.id)
                    return JsonResponse({'error': False, 'message': 'Fuente agregada. Indexa la colección para activarla.'})

                elif action == 'delete_fuente':
                    fuente = get_object_or_404(
                        RagFuente, pk=int(request.POST['id']),
                        coleccion__perfil__usuario=request.user, status=True,
                    )
                    fuente.status = False
                    fuente.save(request)
                    log(f"Fuente RAG eliminada: {fuente.nombre_visible()}", request, "del", obj=fuente.coleccion_id)
                    return JsonResponse({'error': False, 'message': 'Fuente eliminada. Reindexa para actualizar el índice.'})

                elif action == 'indexar':
                    coleccion = _coleccion_de(request, request.POST['id'])
                    rebuild = request.POST.get('rebuild') == '1'
                    from agents_ai.rag.colecciones import indexar_coleccion
                    resultado = indexar_coleccion(coleccion, solo_pendientes=not rebuild)
                    if not resultado['error']:
                        log(f"Colección RAG indexada: {coleccion.nombre} "
                            f"({resultado['indexadas']} fuentes, {resultado['total_chunks']} chunks)",
                            request, "change", obj=coleccion.id)
                    return JsonResponse(resultado)

                elif action == 'asignar_sesion':
                    from whatsapp.models import SesionWhatsApp
                    sesion = get_object_or_404(
                        SesionWhatsApp, pk=int(request.POST['sesion_id']),
                        usuario=request.user, status=True,
                    )
                    coleccion_id = request.POST.get('coleccion_id')
                    if coleccion_id:
                        sesion.rag_coleccion = _coleccion_de(request, coleccion_id)
                        mensaje = f'Sesión {sesion.nombre or sesion.numero} vinculada a "{sesion.rag_coleccion.nombre}".'
                    else:
                        sesion.rag_coleccion = None
                        mensaje = f'Sesión {sesion.nombre or sesion.numero} sin colección RAG.'
                    sesion.save(request)
                    log(mensaje, request, "change", obj=sesion.id)
                    return JsonResponse({'error': False, 'message': mensaje})

                elif action == 'probar_consulta':
                    coleccion = _coleccion_de(request, request.POST['id'])
                    pregunta = (request.POST.get('pregunta') or '').strip()
                    if not pregunta:
                        return JsonResponse({'error': True, 'message': 'Escribe una pregunta de prueba.'})
                    from agents_ai.rag.colecciones import consultar_coleccion
                    resultados = consultar_coleccion(coleccion, pregunta)
                    return JsonResponse({'error': False, 'resultados': resultados})

                return JsonResponse({'error': True, 'message': f'Acción desconocida: {action}'})
        except Exception as ex:
            return JsonResponse({'error': True, 'message': f'Error: {str(ex)[:300]}'})

    if request.GET.get('action') == 'fuentes':
        coleccion = _coleccion_de(request, request.GET['id'])
        fuentes = [{
            'id': f.id,
            'titulo': f.nombre_visible(),
            'tipo': f.get_tipo_display(),
            'estado': f.estado,
            'error': f.error_detalle,
            'chunks': f.chunks,
        } for f in coleccion.fuentes_activas()]
        return JsonResponse({'error': False, 'fuentes': fuentes, 'nombre': coleccion.nombre})

    from whatsapp.models import SesionWhatsApp
    colecciones = (
        RagColeccion.objects.filter(perfil=perfil, status=True)
        .select_related('apikey')
        .annotate(
            n_fuentes=Count('fuentes', filter=Q(fuentes__status=True), distinct=True),
            n_pendientes=Count('fuentes', filter=Q(fuentes__status=True, fuentes__estado='pendiente'), distinct=True),
            n_errores=Count('fuentes', filter=Q(fuentes__status=True, fuentes__estado='error'), distinct=True),
            n_sesiones=Count('sesiones', filter=Q(sesiones__status=True), distinct=True),
        )
        .order_by('-fecha_registro')
    )
    data['colecciones'] = colecciones
    data['apikeys'] = ApiKeyIA.objects.filter(perfil=perfil, status=True, estado=True)
    data['sesiones_usuario'] = SesionWhatsApp.objects.filter(
        usuario=request.user, status=True,
    ).select_related('rag_coleccion').order_by('nombre')
    return render(request, 'crm/rag/listado.html', data)
