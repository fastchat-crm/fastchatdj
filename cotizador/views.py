"""
Vistas del cotizador médico web.

- `cotizador_view`: página pública con las tarjetas comparativas.
- `api_cotizar`: endpoint JSON que devuelve los planes con primas (Básico/Plus)
  calculadas por el motor tarifario, para una edad/género (o lista de integrantes).
- `api_cliente_cedula`: proxy a la API de Vida Nueva para autocompletar por cédula.

El cotizador, el chatbot y (a futuro) WhatsApp comparten el MISMO motor tarifario.
"""
import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from crm.models import PerfilNegocioIA
from .models import Plan
from . import motor_tarifario as M


def _empresa_default_id():
    """Empresa por defecto del cotizador: la primera (por id) que tenga planes
    cargados y ademas un agente IA activo, para que cotizador + chatbot queden
    ambos operativos. Si ninguna tiene agente, cae a la primera con planes."""
    from crm.models import AgentesIA
    empresas = list(
        Plan.objects.filter(status=True).order_by('empresa_id')
        .values_list('empresa_id', flat=True).distinct()
    )
    if not empresas:
        return None
    con_agente = set(
        AgentesIA.objects.filter(status=True, perfil_id__in=empresas)
        .values_list('perfil_id', flat=True)
    )
    for eid in empresas:
        if eid in con_agente:
            return eid
    return empresas[0]


def _agente_cotizador(empresa_id, agente_id=None):
    """Resuelve el agente del chatbot del cotizador.

    - `agente_id` explicito (via ?agente_id=): permite que cada cliente monte su
      propio cotizador apuntando a su agente (escalabilidad multi-cliente).
    - Por defecto: el agente de la empresa que tenga una herramienta 'cotizar*'
      (el que sabe cotizar). Si no hay, el primer agente activo de la empresa.
    """
    from crm.models import AgentesIA
    qs = AgentesIA.objects.filter(status=True)
    if agente_id:
        return qs.filter(pk=agente_id).first()
    if not empresa_id:
        return None
    agente = (qs.filter(perfil_id=empresa_id, herramientas__nombre__istartswith='cotizar',
                        herramientas__status=True)
              .distinct().order_by('id').first())
    return agente or qs.filter(perfil_id=empresa_id).order_by('id').first()


def cotizador_view(request):
    from crm.chat_widget import generar_embed_key
    empresa_id = request.GET.get('empresa_id') or _empresa_default_id()
    agente = _agente_cotizador(empresa_id, request.GET.get('agente_id'))
    return render(request, 'cotizador/cotizador.html', {
        'empresa_id': empresa_id,
        'chat_embed_key': generar_embed_key(agente.id) if agente else '',
    })


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_cotizar(request):
    """Devuelve los planes de la empresa con prima Básico/Plus para los integrantes.

    Body/params: edad, genero ('M'/'F'), [empresa_id], o integrantes=[{edad,genero},...].
    """
    if request.method == "POST":
        try:
            data = json.loads(request.body or "{}")
        except ValueError:
            data = {}
    else:
        data = request.GET

    empresa_id = data.get("empresa_id") or _empresa_default_id()
    if not empresa_id:
        return JsonResponse({"error": "No hay planes cargados."}, status=404)

    integrantes = data.get("integrantes")
    if not integrantes:
        edad = data.get("edad")
        if edad in (None, ""):
            return JsonResponse({"error": "Falta edad (o integrantes)."}, status=400)
        integrantes = [{"edad": int(edad), "genero": (data.get("genero") or "M")}]

    try:
        empresa = PerfilNegocioIA.objects.get(id=empresa_id)
    except PerfilNegocioIA.DoesNotExist:
        return JsonResponse({"error": "Empresa no encontrada."}, status=404)

    planes_out = []
    for plan in Plan.objects.filter(empresa=empresa, status=True).order_by('orden', 'nombre_comercial'):
        item = {
            "plan": plan.nombre_comercial,
            "codigo": plan.codigo,
            "suma_asegurada": str(plan.suma_asegurada or ''),
            "modalidad": plan.get_modalidad_display() if plan.modalidad else '',
            "tipo_cobertura": plan.get_tipo_cobertura_display() if plan.tipo_cobertura else '',
            "nivel_referencia": plan.nivel_referencia or '',
            "deducible": str(plan.deducible_anual or 0),
        }
        for var in ("basico", "plus"):
            try:
                r = M.cotizar(plan, integrantes, var)
                item[f"prima_{var}"] = str(r.prima_total)
            except M.TarifaNoEncontrada:
                item[f"prima_{var}"] = None
        item["coberturas"] = list(
            plan.coberturas.filter(status=True)
            .order_by('orden')
            .values("categoria", "concepto", "valor")[:10]
        )
        planes_out.append(item)

    return JsonResponse({
        "empresa_id": empresa.id,
        "integrantes": integrantes,
        "planes": planes_out,
    })


def _normalizar_cliente(d: dict, fuente: str) -> dict | None:
    """Normaliza la respuesta de cualquier API de cédula a {ok, fuente, data{...}}."""
    base = d.get("data") if isinstance(d.get("data"), dict) else d
    edad = base.get("edad") or base.get("driverAge")
    if not edad:
        return None
    sexo = (base.get("sexo") or base.get("gender") or "M").upper()[:1]
    return {"ok": True, "fuente": fuente, "data": {
        "edad": edad, "sexo": sexo,
        "nombres": base.get("nombres", ""), "apellidos": base.get("apellidos", ""),
        "fecha_nacimiento": base.get("fecha_nacimiento", ""),
        "email": base.get("email", ""), "telefono": base.get("telefono", ""),
    }}


@require_http_methods(["GET"])
def api_cliente_cedula(request, cedula):
    """Consulta cédula. Intenta primero el endpoint de Broktech (preferido por el
    cliente) y, si falla/no responde, usa Cotimédica como respaldo. Normaliza la
    salida a {ok, fuente, data{edad,sexo,nombres,...}}.
    """
    import os
    import requests
    from requests.auth import HTTPBasicAuth

    # 1) Broktech (preferido). Credenciales en env; si su server vuelve a responder
    #    JSON correcto, se usará automáticamente.
    user = os.environ.get("VIDANUEVA_USER", "broktech")
    pwd = os.environ.get("VIDANUEVA_PASS", "")
    if pwd:
        try:
            r = requests.post(
                "https://broktech.com.ec/endpoints/vidanueva/cliente-cedula/",
                json={"cedula": cedula}, auth=HTTPBasicAuth(user, pwd),
                headers={"Content-Type": "application/json"}, timeout=20,
            )
            if r.status_code == 200 and "json" in (r.headers.get("content-type", "")):
                norm = _normalizar_cliente(r.json(), "broktech")
                if norm:
                    return JsonResponse(norm)
        except Exception:
            pass

    # 2) Cotimédica (respaldo — la que usa el chatbot).
    try:
        r = requests.get(
            "https://fguerrero.mgaseguros.ec/cotimedica-api/v1/",
            params={"cedula": cedula, "action": "cliente"}, timeout=25,
        )
        norm = _normalizar_cliente(r.json(), "cotimedica")
        if norm:
            return JsonResponse(norm)
        return JsonResponse(r.json(), status=r.status_code, safe=False)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=502)


def documentacion_view(request):
    """Página estática que explica cómo funciona el cotizador y qué tecnologías usa."""
    return render(request, 'cotizador/documentacion.html')


# ===========================================================================
# TRAZA / OBSERVABILIDAD DE CONSUMO IA
# Muestra por cada request al LLM: qué prompt se ejecutó, tokens in/out,
# modelo, origen y COSTO en USD (crm.costos_ia). Más totales día/mes.
# ===========================================================================
def traza_view(request):
    """Página HTML de la traza de consumo (tabla + totales, auto-refresh vía api_traza)."""
    return render(request, 'cotizador/traza.html')


def api_traza(request):
    """JSON con los últimos consumos de tokens + costo USD y totales día/mes."""
    from django.conf import settings
    from django.utils import timezone
    from crm.models import ConsumoTokenIA
    from crm import costos_ia

    limite = int(request.GET.get('limit') or 60)
    limite = max(1, min(limite, 200))

    ahora = timezone.now()
    if settings.USE_TZ:
        ahora = timezone.localtime(ahora)
    hoy = ahora.date()
    inicio_mes = hoy.replace(day=1)

    def _fmt_fecha(dt):
        if settings.USE_TZ and timezone.is_aware(dt):
            dt = timezone.localtime(dt)
        return dt.strftime('%Y-%m-%d %H:%M:%S')

    # Últimos N registros (detalle)
    qs = (ConsumoTokenIA.objects
          .select_related('agente', 'apikey')
          .order_by('-fecha')[:limite])
    filas = []
    for c in qs:
        costo = costos_ia.costo_desde_consumo(c)
        costo_ref = costos_ia.costo_referencia_usd(c.tokens_entrada, c.tokens_salida)
        filas.append({
            'id': c.id,
            'fecha': _fmt_fecha(c.fecha),
            'origen': c.get_origen_display() if c.origen else (c.origen or '—'),
            'origen_key': c.origen or '',
            'modelo': c.modelo or '—',
            'agente': c.agente.nombre if c.agente_id else '—',
            'prompt_preview': c.prompt_preview or '',
            'tokens_in': c.tokens_entrada,
            'tokens_out': c.tokens_salida,
            'tokens_total': c.tokens_total,
            'costo_usd': round(costo, 6),
            'costo_ref_usd': round(costo_ref, 6),
            'incluido': costos_ia.en_suscripcion(c.modelo) or costos_ia.es_local(c.modelo),
        })

    # Totales del día y del mes (iterando; costo depende del modelo por fila)
    def _acumular(desde):
        tot = {'requests': 0, 'tokens': 0, 'costo': 0.0, 'costo_ref': 0.0, 'por_modelo': {}, 'por_origen': {}}
        for c in ConsumoTokenIA.objects.filter(fecha__date__gte=desde).only(
                'modelo', 'origen', 'tokens_entrada', 'tokens_salida', 'tokens_total'):
            costo = costos_ia.costo_desde_consumo(c)
            costo_ref = costos_ia.costo_referencia_usd(c.tokens_entrada, c.tokens_salida)
            tot['requests'] += 1
            tot['tokens'] += c.tokens_total or 0
            tot['costo'] += costo
            tot['costo_ref'] += costo_ref
            m = c.modelo or '—'
            o = c.get_origen_display() if c.origen else '—'
            pm = tot['por_modelo'].setdefault(m, {'tokens': 0, 'costo': 0.0, 'costo_ref': 0.0, 'requests': 0})
            pm['tokens'] += c.tokens_total or 0; pm['costo'] += costo; pm['costo_ref'] += costo_ref; pm['requests'] += 1
            po = tot['por_origen'].setdefault(o, {'tokens': 0, 'costo': 0.0, 'costo_ref': 0.0, 'requests': 0})
            po['tokens'] += c.tokens_total or 0; po['costo'] += costo; po['costo_ref'] += costo_ref; po['requests'] += 1
        tot['costo'] = round(tot['costo'], 6)
        tot['costo_ref'] = round(tot['costo_ref'], 6)
        for d in (tot['por_modelo'], tot['por_origen']):
            for v in d.values():
                v['costo'] = round(v['costo'], 6)
                v['costo_ref'] = round(v['costo_ref'], 6)
        return tot

    mes = _acumular(inicio_mes)
    hoy_t = _acumular(hoy)
    suscripcion = float(getattr(costos_ia, 'SUSCRIPCION_MENSUAL_USD', 0.0) or 0.0)
    amortizado = round(suscripcion / mes['requests'], 6) if mes['requests'] else 0.0
    ahorro_mes = round(mes['costo_ref'] - suscripcion, 6)  # equivalente nube - lo que pagas fijo

    return JsonResponse({
        'ok': True,
        'generado': ahora.strftime('%Y-%m-%d %H:%M:%S'),
        'facturacion': {
            'tipo': 'suscripcion_fija',
            'suscripcion_mensual_usd': round(suscripcion, 2),
            'costo_amortizado_por_request_usd': amortizado,
            'equivalente_nube_mes_usd': mes['costo_ref'],
            'ahorro_vs_nube_mes_usd': ahorro_mes,
            'modelo_referencia': getattr(costos_ia, 'MODELO_REFERENCIA', ''),
        },
        'hoy': hoy_t,
        'mes': mes,
        'ultimos': filas,
    })


def api_traza_detalle(request, cid):
    """Detalle COMPLETO de un request de consumo: qué enviamos (mensaje + prompt
    ensamblado), qué retornó el LLM, tokens y costo."""
    from django.conf import settings
    from django.utils import timezone
    from crm.models import ConsumoTokenIA
    from crm import costos_ia

    try:
        c = ConsumoTokenIA.objects.select_related('agente', 'apikey', 'conversacion').get(pk=cid)
    except ConsumoTokenIA.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'No encontrado'}, status=404)

    f = c.fecha
    if settings.USE_TZ and timezone.is_aware(f):
        f = timezone.localtime(f)

    proveedor_map = {2: 'Gemini', 3: 'OpenAI', 4: 'Claude', 5: 'Ollama'}
    prov = ''
    try:
        prov = proveedor_map.get(getattr(c.apikey, 'proveedor', None), '')
    except Exception:
        prov = ''

    return JsonResponse({
        'ok': True,
        'id': c.id,
        'fecha': f.strftime('%Y-%m-%d %H:%M:%S'),
        'origen': c.get_origen_display() if c.origen else (c.origen or '—'),
        'modelo': c.modelo or '—',
        'proveedor': prov or '—',
        'agente': c.agente.nombre if c.agente_id else '—',
        'conversacion': str(c.conversacion) if c.conversacion_id else '',
        'tokens_in': c.tokens_entrada,
        'tokens_out': c.tokens_salida,
        'tokens_total': c.tokens_total,
        'costo_usd': round(costos_ia.costo_desde_consumo(c), 6),
        'costo_ref_usd': round(costos_ia.costo_referencia_usd(c.tokens_entrada, c.tokens_salida), 6),
        'incluido': costos_ia.en_suscripcion(c.modelo) or costos_ia.es_local(c.modelo),
        # Lo "todito":
        'mensaje_usuario': c.mensaje_usuario or '',
        'prompt_preview': c.prompt_preview or '',
        'prompt_full': c.prompt_full or '',
        'respuesta_full': c.respuesta_full or '',
        'tiene_full': bool(c.prompt_full or c.respuesta_full),
    })
