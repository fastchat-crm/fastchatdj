"""Evaluador de segmentos guardados — condiciones JSON → queryset de Contacto.

Lo usan la vista (`view_segmentos.py`), la audiencia de campañas
(`cron_jobs/ejecutar_campanas.py`) y la inscripción masiva en secuencias
(`view_secuencias.py`).
"""
import logging
from datetime import timedelta

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

logger = logging.getLogger(__name__)

OPERADORES_CAMPO = ('igual', 'contiene', 'vacio', 'no_vacio')


def queryset_segmento(segmento, sesion=None):
    """Devuelve el queryset de contactos que cumplen las condiciones del segmento.

    `sesion`: si se pasa, restringe a los contactos de esa sesión (las campañas
    envían desde una sesión concreta). Siempre excluye opt-out y números inválidos.
    """
    from .models import Contacto, ValorCampoContacto
    cond = segmento.condiciones or {}

    qs = Contacto.objects.filter(status=True, opt_out=False, whatsapp_invalido=False)
    if sesion is not None:
        qs = qs.filter(sesion=sesion)

    etiquetas_in = [int(x) for x in cond.get('etiquetas_incluir') or []]
    if etiquetas_in:
        if (cond.get('modo_etiquetas') or 'any') == 'all':
            for et_id in etiquetas_in:
                qs = qs.filter(etiquetas__id=et_id)
        else:
            qs = qs.filter(etiquetas__id__in=etiquetas_in)

    etiquetas_out = [int(x) for x in cond.get('etiquetas_excluir') or []]
    if etiquetas_out:
        qs = qs.exclude(etiquetas__id__in=etiquetas_out)

    canales = cond.get('canales') or []
    if canales:
        qs = qs.filter(canal__in=canales)

    for regla in cond.get('campos') or []:
        try:
            campo_id = int(regla.get('campo_id'))
        except (TypeError, ValueError):
            continue
        operador = regla.get('operador') or 'igual'
        valor = (regla.get('valor') or '').strip()
        sub = ValorCampoContacto.objects.filter(
            contacto=OuterRef('pk'), campo_id=campo_id, status=True,
        )
        if operador == 'igual':
            qs = qs.filter(Exists(sub.filter(valor__iexact=valor)))
        elif operador == 'contiene':
            qs = qs.filter(Exists(sub.filter(valor__icontains=valor)))
        elif operador == 'no_vacio':
            qs = qs.filter(Exists(sub.exclude(valor='')))
        elif operador == 'vacio':
            qs = qs.exclude(Exists(sub.exclude(valor='')))

    actividad = cond.get('actividad') or {}
    tipo_act = actividad.get('tipo')
    try:
        dias = int(actividad.get('dias') or 0)
    except (TypeError, ValueError):
        dias = 0
    if tipo_act in ('con_actividad', 'sin_actividad') and dias > 0:
        corte = timezone.now() - timedelta(days=dias)
        if tipo_act == 'con_actividad':
            qs = qs.filter(fecha_ultimo_mensaje__gte=corte)
        else:
            qs = qs.filter(Q(fecha_ultimo_mensaje__lt=corte) | Q(fecha_ultimo_mensaje__isnull=True))

    return qs.distinct()


def validar_condiciones(cond):
    """Valida la estructura de condiciones. Devuelve (ok, mensaje)."""
    if not isinstance(cond, dict):
        return False, 'Las condiciones deben ser un objeto.'
    if (cond.get('modo_etiquetas') or 'any') not in ('any', 'all'):
        return False, 'Modo de etiquetas inválido.'
    for regla in cond.get('campos') or []:
        if (regla.get('operador') or 'igual') not in OPERADORES_CAMPO:
            return False, 'Operador de campo inválido.'
        if not regla.get('campo_id'):
            return False, 'Cada regla de campo necesita un campo.'
        if regla.get('operador') in ('igual', 'contiene') and not (regla.get('valor') or '').strip():
            return False, 'Las reglas "igual" y "contiene" necesitan un valor.'
    actividad = cond.get('actividad') or {}
    if actividad:
        if actividad.get('tipo') not in ('con_actividad', 'sin_actividad'):
            return False, 'Tipo de actividad inválido.'
        try:
            if int(actividad.get('dias') or 0) < 1:
                return False, 'La actividad necesita una cantidad de días (mínimo 1).'
        except (TypeError, ValueError):
            return False, 'Los días de actividad deben ser un número.'
    tiene_algo = any([
        cond.get('etiquetas_incluir'), cond.get('etiquetas_excluir'),
        cond.get('canales'), cond.get('campos'), actividad,
    ])
    if not tiene_algo:
        return False, 'El segmento necesita al menos una condición.'
    return True, ''
