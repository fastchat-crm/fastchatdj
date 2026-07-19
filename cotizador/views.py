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
