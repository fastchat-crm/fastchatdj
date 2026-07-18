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
    """Primera empresa que tenga planes cargados (Vida Buena en staging)."""
    return Plan.objects.filter(status=True).values_list('empresa_id', flat=True).first()


def cotizador_view(request):
    empresa_id = request.GET.get('empresa_id') or _empresa_default_id()
    return render(request, 'cotizador/cotizador.html', {'empresa_id': empresa_id})


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
