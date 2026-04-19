"""Vista de campañas (broadcasts).

Funcionalidad:
- Listado con filtros (criterio/nombre, sesión, estado, tipo) estilo plantillas.
- Crear/programar/pausar/cancelar campañas.
- Soporta deep-link desde /whatsapp/sesiones/ pasando ?sesion_id=<id>&action=add.
"""
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from core.funciones import addData, paginador, secure_module, log
from .models import (
    Campana, EnvioCampana, SesionWhatsApp, EtiquetaContacto, PlantillaWhatsApp,
    TIPOS_CAMPANA, ESTADOS_CAMPANA,
)


def _sesiones_del_usuario(user):
    """Todas las sesiones activas del usuario (cualquier proveedor).
    Las campañas pueden correr sobre Baileys, Meta, IG, Messenger."""
    return SesionWhatsApp.objects.filter(
        usuario=user, status=True,
    ).order_by('nombre')


@login_required
@secure_module
def campanasView(request):
    data = {
        'titulo': 'Campañas',
        'descripcion': 'Envío masivo segmentado de mensajes WhatsApp / IG / Messenger',
        'ruta': request.path,
    }
    addData(request, data)

    if request.method == 'POST':
        return _manejar_post(request)

    # ===== GET =====
    action = request.GET.get('action')
    data['action'] = action

    # Deep-link desde sesiones: preseleccionar sesion y abrir modal de creación
    sesion_preseleccionada = None
    sesion_id_param = request.GET.get('sesion_id') or request.GET.get('sesion')
    if sesion_id_param:
        sesion_preseleccionada = SesionWhatsApp.objects.filter(
            id=sesion_id_param, usuario=request.user, status=True,
        ).first()

    # Detalle de una campaña
    if action == 'detalle':
        pk = request.GET.get('pk')
        camp = Campana.objects.filter(
            id=pk, sesion__usuario=request.user,
        ).select_related('sesion', 'plantilla').first()
        if not camp:
            return render(request, 'whatsapp/campanas/listado.html', data)
        data['campana'] = camp
        data['envios'] = camp.envios.select_related('contacto').order_by(
            '-fecha_envio', '-id'
        )[:200]
        return render(request, 'whatsapp/campanas/detalle.html', data)

    # ===== LISTADO CON FILTROS =====
    filtros = Q(sesion__usuario=request.user, status=True)

    criterio = (request.GET.get('criterio') or '').strip()
    sesion_filtro = request.GET.get('sesion') or ''
    estado_filtro = request.GET.get('estado') or ''
    tipo_filtro = request.GET.get('tipo') or ''

    url_vars = ''
    if criterio:
        filtros &= (
            Q(nombre__icontains=criterio)
            | Q(descripcion__icontains=criterio)
            | Q(mensaje_texto__icontains=criterio)
        )
        data['criterio'] = criterio
        url_vars += f'&criterio={criterio}'
    if sesion_filtro:
        filtros &= Q(sesion_id=sesion_filtro)
        try:
            data['sesion_sel'] = int(sesion_filtro)
        except (TypeError, ValueError):
            pass
        url_vars += f'&sesion={sesion_filtro}'
    if estado_filtro:
        filtros &= Q(estado=estado_filtro)
        data['estado_sel'] = estado_filtro
        url_vars += f'&estado={estado_filtro}'
    if tipo_filtro:
        filtros &= Q(tipo=tipo_filtro)
        data['tipo_sel'] = tipo_filtro
        url_vars += f'&tipo={tipo_filtro}'

    listado = Campana.objects.filter(filtros).select_related(
        'sesion', 'plantilla',
    ).order_by('-fecha_registro')

    data['url_vars'] = url_vars
    data['list_count'] = listado.count()
    data['sesiones'] = _sesiones_del_usuario(request.user)
    data['etiquetas'] = EtiquetaContacto.objects.filter(
        status=True, usuario_creacion=request.user,
    )
    data['plantillas'] = PlantillaWhatsApp.objects.filter(
        status=True, estado_meta='APPROVED',
        config_meta__sesion__usuario=request.user,
    ).select_related('config_meta', 'config_meta__sesion')
    data['tipos_campana'] = TIPOS_CAMPANA
    data['estados_campana'] = ESTADOS_CAMPANA
    data['sesion_preseleccionada'] = sesion_preseleccionada
    data['abrir_modal_add'] = bool(action == 'add' and sesion_preseleccionada)

    paginador(request, listado, 20, data, url_vars)
    return render(request, 'whatsapp/campanas/listado.html', data)


def _manejar_post(request):
    action = request.POST.get('action')
    try:
        with transaction.atomic():
            if action == 'add':
                sesion = SesionWhatsApp.objects.filter(
                    pk=int(request.POST['sesion']),
                    usuario=request.user, status=True,
                ).first()
                if not sesion:
                    return JsonResponse({'error': True, 'message': 'Sesión no encontrada.'})
                camp = Campana.objects.create(
                    nombre=request.POST['nombre'],
                    descripcion=request.POST.get('descripcion', ''),
                    sesion=sesion,
                    tipo=request.POST.get('tipo', 'texto'),
                    mensaje_texto=request.POST.get('mensaje_texto', ''),
                    plantilla_id=int(request.POST['plantilla_id']) if request.POST.get('plantilla_id') else None,
                    throttle_por_minuto=int(request.POST.get('throttle_por_minuto', 20) or 20),
                    canales=request.POST.getlist('canales[]') or [],
                    estado='borrador',
                    usuario_creacion=request.user,
                )
                if request.POST.getlist('etiquetas_incluir[]'):
                    camp.etiquetas_incluir.set(request.POST.getlist('etiquetas_incluir[]'))
                if request.POST.getlist('etiquetas_excluir[]'):
                    camp.etiquetas_excluir.set(request.POST.getlist('etiquetas_excluir[]'))
                if request.FILES.get('archivo'):
                    camp.archivo = request.FILES['archivo']
                    camp.save(update_fields=['archivo'])
                log(f'Campaña {camp.nombre} creada', request, 'add', obj=camp.id)
                return JsonResponse({'error': False, 'campana_id': camp.id, 'reload': True})

            if action == 'programar':
                pk = int(request.POST['id'])
                camp = Campana.objects.filter(pk=pk, sesion__usuario=request.user).first()
                if not camp:
                    return JsonResponse({'error': True, 'message': 'Campaña no encontrada.'})
                fecha = request.POST.get('programada_para')
                if fecha:
                    camp.programada_para = fecha
                camp.estado = 'programada'
                camp.save(update_fields=['estado', 'programada_para'])
                return JsonResponse({'error': False, 'message': 'Campaña programada.'})

            if action == 'enviar_ahora':
                pk = int(request.POST['id'])
                camp = Campana.objects.filter(pk=pk, sesion__usuario=request.user).first()
                if not camp:
                    return JsonResponse({'error': True, 'message': 'Campaña no encontrada.'})
                camp.estado = 'programada'
                camp.programada_para = timezone.now()
                camp.save(update_fields=['estado', 'programada_para'])
                return JsonResponse({
                    'error': False,
                    'message': 'Campaña encolada. El cron la despachará en el próximo tick.',
                })

            if action == 'pausar':
                Campana.objects.filter(
                    pk=int(request.POST['id']), sesion__usuario=request.user,
                ).update(estado='pausada')
                return JsonResponse({'error': False})

            if action == 'reanudar':
                Campana.objects.filter(
                    pk=int(request.POST['id']), sesion__usuario=request.user,
                    estado='pausada',
                ).update(estado='enviando')
                return JsonResponse({'error': False})

            if action == 'cancelar':
                Campana.objects.filter(
                    pk=int(request.POST['id']), sesion__usuario=request.user,
                ).update(estado='cancelada')
                return JsonResponse({'error': False})

            if action == 'eliminar':
                Campana.objects.filter(
                    pk=int(request.POST['id']), sesion__usuario=request.user,
                ).update(status=False)
                return JsonResponse({'error': False})

            return JsonResponse({'error': True, 'message': f'Acción desconocida: {action}'})

    except Exception as ex:
        return JsonResponse({'error': True, 'message': str(ex)})
