"""Verificación y emisión de alertas de consumo de tokens por API key."""
from datetime import date, timedelta

from django.db.models import Sum
from django.utils import timezone


def verificar_alerta_consumo(apikey, tokens_nuevos: int = 0) -> None:
    """
    Revisa si el consumo diario o mensual de la API key superó los umbrales
    configurados en AlertaConsumoIA y emite notificaciones si corresponde.

    Llámala justo después de crear un ConsumoTokenIA.
    Silencia cualquier excepción para no interrumpir el flujo de mensajes.
    """
    try:
        _verificar(apikey)
    except Exception:
        pass


def _verificar(apikey) -> None:
    from crm.models import AlertaConsumoIA, ConsumoTokenIA
    from core.funciones import notificacion

    try:
        alerta = apikey.alerta_consumo
    except AlertaConsumoIA.DoesNotExist:
        return  # Sin configuración → nada que hacer

    destinatarios = list(alerta.notificar_a.filter(is_active=True))
    if not destinatarios:
        return

    hoy = timezone.now().date()
    inicio_mes = hoy.replace(day=1)

    base_qs = ConsumoTokenIA.objects.filter(apikey=apikey)

    # ── Alerta diaria ─────────────────────────────────────────────────────
    if alerta.umbral_diario > 0 and alerta.ultimo_aviso_diario != hoy:
        total_hoy = (
            base_qs.filter(fecha__date=hoy)
            .aggregate(t=Sum('tokens_total'))['t'] or 0
        )
        if total_hoy >= alerta.umbral_diario:
            _enviar_alertas(
                destinatarios=destinatarios,
                titulo=f'⚠️ Límite diario de tokens alcanzado — {apikey.alias or apikey}',
                cuerpo=(
                    f'La API key <strong>{apikey.alias or apikey}</strong> consumió '
                    f'<strong>{total_hoy:,} tokens</strong> hoy, superando el umbral '
                    f'configurado de <strong>{alerta.umbral_diario:,} tokens</strong>.'
                ),
                url='/crm/entrenamiento/',
                notificacion_fn=notificacion,
            )
            alerta.ultimo_aviso_diario = hoy
            alerta.save(update_fields=['ultimo_aviso_diario'])

    # ── Alerta mensual ────────────────────────────────────────────────────
    if alerta.umbral_mensual > 0 and alerta.ultimo_aviso_mensual != hoy:
        total_mes = (
            base_qs.filter(fecha__date__gte=inicio_mes)
            .aggregate(t=Sum('tokens_total'))['t'] or 0
        )
        if total_mes >= alerta.umbral_mensual:
            _enviar_alertas(
                destinatarios=destinatarios,
                titulo=f'🚨 Límite mensual de tokens alcanzado — {apikey.alias or apikey}',
                cuerpo=(
                    f'La API key <strong>{apikey.alias or apikey}</strong> consumió '
                    f'<strong>{total_mes:,} tokens</strong> este mes, superando el umbral '
                    f'configurado de <strong>{alerta.umbral_mensual:,} tokens</strong>.'
                ),
                url='/crm/entrenamiento/',
                notificacion_fn=notificacion,
            )
            alerta.ultimo_aviso_mensual = hoy
            alerta.save(update_fields=['ultimo_aviso_mensual'])


def _enviar_alertas(destinatarios, titulo, cuerpo, url, notificacion_fn) -> None:
    from django.utils.timezone import now
    from datetime import timedelta
    from seguridad.models import Notificacion

    # Evitar duplicar notificaciones si ya existe una con el mismo título en las últimas 12 h
    hace_12h = now() - timedelta(hours=12)
    ya_enviado = Notificacion.objects.filter(
        titulo=titulo,
        fecha_registro__gte=hace_12h
    ).exists()
    if ya_enviado:
        return

    for usuario in destinatarios:
        notificacion_fn(
            titulo=titulo,
            cuerpo=cuerpo,
            destinatario=usuario,
            url=url,
            prioridad=1,   # Alta
            tipo=4,        # Error / Alerta
        )
