"""Wizard de creación rápida de un agente IA en 3 pasos.

Pensado para usuarios nuevos que no saben por dónde empezar. Llena lo
mínimo indispensable y delega los detalles avanzados al form completo
post-creación.

Pasos:
    1. Nombre + personalidad_preset (radio cards).
    2. Contexto del negocio (textarea libre — se guarda como contexto_estatico).
    3. ApiKey (selección o creación rápida) y crear.
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render

from core.constantes import PERSONALIDAD_PRESETS
from core.funciones import addData, secure_module
from crm.models import AgentesIA, ApiKeyIA, PerfilNegocioIA

logger = logging.getLogger(__name__)


@login_required
@secure_module
def agente_wizard_view(request):
    """GET: render wizard.  POST: crea el agente y redirige al form completo."""
    perfil = PerfilNegocioIA.objects.filter(usuario=request.user).first()
    if not perfil:
        messages.error(request, 'Configurá tu perfil de empresa antes de crear un agente.')
        return redirect('/crm/perfil_empresa/')

    if request.method == 'POST':
        nombre = (request.POST.get('nombre') or '').strip()
        preset = (request.POST.get('personalidad_preset') or 'amable').strip()
        contexto = (request.POST.get('contexto_negocio') or '').strip()
        apikey_id = request.POST.get('apikey_id') or ''

        errores = {}
        if not nombre:
            errores['nombre'] = 'Ponele un nombre al agente.'
        if preset not in PERSONALIDAD_PRESETS:
            errores['personalidad_preset'] = 'Elegí una personalidad válida.'
        apikey_obj = None
        if apikey_id:
            apikey_obj = ApiKeyIA.objects.filter(pk=apikey_id, status=True).first()
            if not apikey_obj:
                errores['apikey'] = 'La API Key seleccionada no existe.'
        else:
            errores['apikey'] = 'Necesitás al menos una API Key para que el agente responda.'

        if errores:
            return JsonResponse({'result': False, 'errores': errores}, status=400)

        # `descripcion` es required en el modelo. Si el usuario no la dio,
        # generamos una a partir del nombre — el preset llena el resto.
        descripcion = (request.POST.get('descripcion') or '').strip()
        if not descripcion:
            descripcion = f'Agente {nombre} listo para atender clientes por WhatsApp.'

        agente = AgentesIA(
            perfil=perfil,
            nombre=nombre,
            descripcion=descripcion,
            personalidad_preset=preset,
            # contexto_estatico = texto libre del paso 2 (se inyecta directo al
            # prompt, sin embeddings — ideal para FAQs cortas/menús/políticas).
            contexto_estatico=contexto or None,
        )
        # save() del modelo aplica el preset y rellena los 5 campos persona.
        agente.save()
        agente.apikey.add(apikey_obj)

        # Provisiona el tenant RAG del agente e indexa el conocimiento inicial
        # (contexto_estatico). No fatal — el agente queda creado igual.
        try:
            from agents_ai import indexador_conocimiento as _idx
            _idx.provisionar_e_indexar_inicial(agente)
        except Exception as exc:
            logger.warning('Provisión/indexado RAG del agente %s falló: %s', agente.id, exc)

        return JsonResponse({
            'result': True,
            'agente_id': agente.id,
            'redirect': f'/crm/entrenamiento/?action=procedimiento&id={agente.id}',
            'mensaje': f'Listo, {nombre} creado. Te llevamos al editor para que termines de afinarlo.',
        })

    # GET — render wizard
    apikeys = list(ApiKeyIA.objects.filter(perfil=perfil, status=True).values('id', 'alias', 'proveedor'))
    data = {
        'titulo': 'Crear Agente IA — modo rápido',
        'personalidad_presets': PERSONALIDAD_PRESETS,
        'apikeys': apikeys,
    }
    addData(request, data)
    return render(request, 'crm/entrenamiento/agente/wizard.html', data)
