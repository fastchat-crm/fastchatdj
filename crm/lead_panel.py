"""Captura de leads del chat web (cotizador) hacia el CRM del panel.

Interoperabilidad: un lead que conversa en el widget del cotizador y deja su
correo aterriza en el MISMO panel que los leads de WhatsApp — como Contacto y
como tarjeta en el Pipeline de ventas (etapa "Nuevo Lead") — para que el equipo
le dé seguimiento.

Se reusa la infraestructura existente (Contacto / ConversacionWhatsApp /
ConversacionEnPipeline). NO se crea ningún modelo ni migración. El acoplamiento a
WhatsApp se resuelve con una "sesión web" dedicada por empresa:

  - proveedor='meta' + estado='conectado'  -> el cron de reconexión (solo toca
    baileys en estado desconectado/error) NUNCA la toca.
  - usuario = dueño de la empresa (PerfilNegocioIA.usuario) -> los contactos y
    tarjetas aparecen en SU panel (Contactos y Pipeline filtran por usuario).
  - la conversación se crea con expiración lejana -> el cron de despedida (que
    solo actúa sobre conversaciones vencidas) no intenta enviar WhatsApp.

Idempotente por session_id del widget: reingresos del mismo chat actualizan el
mismo contacto/tarjeta en vez de duplicar.
"""
import logging
import re
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Teléfono EC: 09######## o +5939######## (tolerante a espacios/guiones)
_TEL_RE = re.compile(r"(?:\+?593|0)\s?9(?:[\s-]?\d){8}")


def detectar_email(texto: str) -> str:
    m = _EMAIL_RE.search(texto or '')
    return m.group(0).strip() if m else ''


def detectar_telefono(texto: str) -> str:
    m = _TEL_RE.search((texto or '').replace(' ', '').replace('-', ''))
    return m.group(0).strip() if m else ''


def _sesion_web(empresa, agente_id=None):
    """Get/crea la sesión web dedicada del cotizador para una empresa.
    Devuelve None si la empresa no tiene dueño (sin dueño no se vería en panel)."""
    from whatsapp.models import SesionWhatsApp
    if not getattr(empresa, 'usuario_id', None):
        return None
    sid = f"web-cotizador-emp{empresa.id}"
    ses, creada = SesionWhatsApp.objects.get_or_create(
        session_id=sid,
        defaults={
            'nombre': 'Cotizador Web',
            'numero': '',
            'estado': 'conectado',
            'proveedor': 'meta',
            'activo': True,
            'usuario_id': empresa.usuario_id,
            'agente_ia_id': agente_id,
        },
    )
    if not creada and agente_id and not ses.agente_ia_id:
        ses.agente_ia_id = agente_id
        ses.save(update_fields=['agente_ia'])
    return ses


def _nota_lead(datos: dict) -> str:
    filas = [
        ('Origen', 'Cotizador web'),
        ('Nombre', datos.get('nombre')),
        ('Cédula', datos.get('cedula')),
        ('Edad', datos.get('edad')),
        ('Género', datos.get('genero')),
        ('Email', datos.get('email')),
        ('Teléfono', datos.get('telefono')),
        ('Plan de interés', datos.get('plan_interes')),
    ]
    return "\n".join(f"{k}: {v}" for k, v in filas if v)


def registrar_lead(agente, session_id: str, **datos):
    """Crea/actualiza el lead del cotizador en el panel (Contacto + Pipeline).

    Idempotente por session_id. Nunca lanza (degrada silencioso). Devuelve el
    Contacto o None.
    """
    try:
        from whatsapp.models import (
            Contacto, ConversacionWhatsApp, ConversacionEnPipeline,
            PipelineVenta, EtapaPipeline, PerfilContacto,
        )
        empresa = getattr(agente, 'perfil', None)
        if not empresa:
            return None
        ses = _sesion_web(empresa, getattr(agente, 'id', None))
        if not ses:
            logger.info("Lead cotizador sin dueño de empresa (perfil %s); no se capta al panel",
                        getattr(empresa, 'id', '?'))
            return None

        telefono = (datos.get('telefono') or '').strip()
        nombre = (datos.get('nombre') or '').strip()
        numero_key = (telefono or f"web:{session_id}")[:50]

        contacto, creado = Contacto.objects.get_or_create(
            sesion=ses, contacto_numero=numero_key,
            defaults={
                'contacto_nombre': nombre or 'Lead cotizador',
                'numero_telefono': telefono[:50],
                'canal': 'otro',
                'estado': 'activo',
            },
        )

        cambios = []
        if nombre and (contacto.contacto_nombre or '') in ('', 'Lead cotizador'):
            contacto.contacto_nombre = nombre[:255]; cambios.append('contacto_nombre')
        if telefono and not contacto.numero_telefono:
            contacto.numero_telefono = telefono[:50]; cambios.append('numero_telefono')
        _msg = (datos.get('mensaje') or '').strip()
        if _msg:
            contacto.ultimo_mensaje = _msg[:500]
            contacto.fecha_ultimo_mensaje = timezone.now()
            cambios += ['ultimo_mensaje', 'fecha_ultimo_mensaje']
        if cambios:
            contacto.save(update_fields=cambios)

        # Datos del lead → PerfilContacto.intereses_json (campo libre)
        perfil_c, _ = PerfilContacto.objects.get_or_create(contacto=contacto)
        intereses = dict(perfil_c.intereses_json or {})
        intereses.setdefault('origen', 'cotizador_web')
        for k in ('email', 'cedula', 'edad', 'genero', 'plan_interes'):
            v = datos.get(k)
            if v:
                intereses[k] = v
        perfil_c.intereses_json = intereses
        perfil_c.save(update_fields=['intereses_json'])

        # Conversación (soporte para la tarjeta de pipeline). Expira lejano para
        # que el cron de despedida no intente enviar WhatsApp a un lead web.
        conv = contacto.conversaciones.order_by('-id').first()
        if not conv:
            conv = ConversacionWhatsApp.objects.create(
                contacto=contacto,
                fecha_hora_expira=timezone.now() + timedelta(days=3650),
                origen_canal='otro',
            )

        # Tarjeta en el pipeline por defecto, primera etapa ("Nuevo Lead")
        pipe = (PipelineVenta.objects.filter(es_default=True, status=True).first()
                or PipelineVenta.objects.filter(status=True).first())
        if pipe:
            etapa = (EtapaPipeline.objects.filter(pipeline=pipe, status=True)
                     .order_by('orden').first())
            if etapa:
                nota = _nota_lead({**datos, 'nombre': contacto.contacto_nombre})
                try:
                    valor = float(datos.get('valor_estimado') or 0)
                except (TypeError, ValueError):
                    valor = 0
                card, card_creada = ConversacionEnPipeline.objects.get_or_create(
                    conversacion=conv, etapa=etapa,
                    defaults={'valor_estimado': valor, 'moneda': 'USD', 'nota': nota},
                )
                if not card_creada:
                    upd = []
                    if nota and nota != card.nota:
                        card.nota = nota; upd.append('nota')
                    if valor and float(card.valor_estimado or 0) == 0:
                        card.valor_estimado = valor; upd.append('valor_estimado')
                    if upd:
                        card.save(update_fields=upd)

        logger.info("Lead cotizador captado al panel: contacto=%s (nuevo=%s) sesion_web=%s",
                    contacto.id, creado, ses.id)
        return contacto
    except Exception as exc:
        logger.exception("registrar_lead cotizador falló: %s", exc)
        return None
