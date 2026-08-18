"""Evaluación de salud por canal — WhatsApp, Instagram, Facebook, TikTok e IA.

Corrida de solo lectura: no envía mensajes ni gasta tokens. Consulta el estado
real de cada canal contra su proveedor y cruza la configuración con lo que pasó
de verdad en la base.

    python manage.py shell < scripts/evaluar_canales.py

Qué revisa por canal:

- **Sesiones**: cuántas hay, cuántas conectadas y cuáles están en error.
- **Credenciales**: si el token está presente y si el webhook fue verificado.
  Una sesión "conectada" con el webhook sin verificar recibe cero eventos.
- **Tráfico real**: mensajes y conversaciones de los últimos 7 días. Es lo que
  distingue "configurado" de "funcionando".
- **Anti-baneo** (solo Baileys): cuota del día y calentamiento del gateway.

Para IA: consumo por modelo con costo, agentes sin conocimiento vectorizado y
keys caídas.
"""
from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from agents_ai.consumo import costo_usd
from crm.models import AgentesIA, ApiKeyIA, ConsumoTokenIA
from whatsapp.models import (
    ComentarioSocial,
    ConversacionWhatsApp,
    MensajeWhatsApp,
    SesionWhatsApp,
)

DIAS = 7
DESDE = timezone.now() - timedelta(days=DIAS)

CANALES = [
    ('WhatsApp Cloud API', 'meta',      'config_meta'),
    ('WhatsApp no oficial', 'baileys',  'config_baileys'),
    ('Instagram',          'instagram', 'config_instagram'),
    ('Facebook Messenger', 'messenger', 'config_messenger'),
    ('TikTok',             'tiktok',    'config_tiktok'),
]


def _linea(txt=''):
    print(txt)


def _regla(titulo):
    _linea()
    _linea('=' * 96)
    _linea(titulo)
    _linea('=' * 96)


def evaluar_canal(nombre, proveedor, attr_config):
    sesiones = list(
        SesionWhatsApp.objects.filter(status=True, proveedor=proveedor)
        .select_related(attr_config)
    )
    if not sesiones:
        _linea('%-22s  sin sesiones' % nombre)
        return

    conectadas = sum(1 for s in sesiones if s.estado == 'conectado')
    en_error = [s for s in sesiones if s.estado == 'error']

    ids = [s.id for s in sesiones]
    msgs = MensajeWhatsApp.objects.filter(
        conversacion__contacto__sesion_id__in=ids, fecha__gte=DESDE).count()
    convs = ConversacionWhatsApp.objects.filter(
        contacto__sesion_id__in=ids, fecha_registro__gte=DESDE).count()

    # El modo de bot explica el consumo de IA: una sesion en `tradicional` no
    # llama al LLM ni una vez por mas trafico que tenga, y sin este dato el
    # reporte parece decir que la IA esta rota.
    modos = {}
    for s in sesiones:
        modos[s.modo_bot or '?'] = modos.get(s.modo_bot or '?', 0) + 1
    detalle_modo = ', '.join('%s x%d' % (m, n) for m, n in sorted(modos.items()))

    _linea('%-22s  %d sesion(es) · %d conectada(s) · %d msg / %d conv en %dd · modo: %s'
           % (nombre, len(sesiones), conectadas, msgs, convs, DIAS, detalle_modo))

    for s in sesiones:
        cfg = getattr(s, attr_config, None)
        avisos = []
        if cfg is None:
            avisos.append('SIN configuración')
        else:
            if hasattr(cfg, 'access_token') and not (cfg.access_token or '').strip():
                avisos.append('sin token')
            # Un webhook sin verificar no recibe un solo evento, por mas que la
            # sesion figure conectada.
            if hasattr(cfg, 'webhook_verificado_en') and not cfg.webhook_verificado_en:
                avisos.append('WEBHOOK SIN VERIFICAR')
            if getattr(cfg, 'error_mensaje', None):
                avisos.append('error: %s' % str(cfg.error_mensaje)[:50])
        if not s.activo:
            avisos.append('suspendida')
        if s.estado != 'conectado':
            avisos.append('estado=%s' % s.estado)

        msgs_s = MensajeWhatsApp.objects.filter(
            conversacion__contacto__sesion=s, fecha__gte=DESDE).count()
        if avisos or msgs_s == 0:
            _linea('    %-28s %4d msg  %s' % (
                (s.nombre or s.numero or '?')[:28], msgs_s,
                ' · '.join(avisos) or 'sin tráfico en %dd' % DIAS))

    if en_error:
        _linea('    en error: %s' % ', '.join((s.nombre or '?')[:20] for s in en_error))


def evaluar_comentarios():
    filas = (ComentarioSocial.objects.filter(status=True, fecha_registro__gte=DESDE)
             .values('canal').annotate(n=Count('id')).order_by('-n'))
    if not filas:
        _linea('sin comentarios en %d días' % DIAS)
        return
    for f in filas:
        pend = ComentarioSocial.objects.filter(
            status=True, canal=f['canal'], estado='nuevo').count()
        _linea('  %-12s %4d en %dd · %d sin atender' % (f['canal'], f['n'], DIAS, pend))


def evaluar_antiban():
    from whatsapp.services import WhatsAppService
    svc = WhatsAppService()
    sesiones = SesionWhatsApp.objects.filter(status=True, proveedor='baileys')
    if not sesiones:
        _linea('sin sesiones Baileys')
        return
    for s in sesiones:
        res = svc.get_antiban_estado(s.session_id)
        if not res.get('success'):
            _linea('  %-26s no se pudo leer: %s' % (
                (s.nombre or '?')[:26], str(res.get('error'))[:50]))
            continue
        a = res.get('antiban') or {}
        # La salud de la lista es el dato que anticipa un baneo: cuando sube,
        # todavía se puede depurar la lista; cuando llega el 403 ya es tarde.
        salud = a.get('saludLista') or {}
        aviso_lista = ''
        if salud.get('muestras'):
            aviso_lista = ' · lista %d%% inválidos (%d intentos)%s' % (
                round((salud.get('ratio') or 0) * 100), salud['muestras'],
                ' LISTA SUCIA — envíos detenidos' if salud.get('sucia') else '')
        _linea('  %-26s dia %s · %s/%s enviados · frios %s/%s%s%s' % (
            (s.nombre or '?')[:26], a.get('diasVinculada'),
            a.get('enviadosHoy'), a.get('cuotaDiaria'),
            a.get('contactosFriosHoy'), a.get('cuotaContactosFrios'),
            aviso_lista,
            ' · BLOQUEADA' if a.get('bloqueada') else ''))


def evaluar_ia():
    _linea('Consumo por modelo (histórico):')
    filas = (ConsumoTokenIA.objects.values('modelo')
             .annotate(n=Count('id'), e=Sum('tokens_entrada'),
                       s=Sum('tokens_salida'), t=Sum('tokens_total'))
             .order_by('-t'))
    total = 0.0
    for f in filas:
        c = costo_usd(f['modelo'] or '', f['e'] or 0, f['s'] or 0)
        total += c
        _linea('  %-24s %5d llamadas %10d tokens  USD %.4f'
               % (f['modelo'] or '(sin modelo)', f['n'], f['t'] or 0, c))
    _linea('  %-24s %36s USD %.4f' % ('TOTAL', '', total))

    recientes = (ConsumoTokenIA.objects.filter(fecha__gte=DESDE)
                 .aggregate(t=Sum('tokens_total'), n=Count('id')))
    _linea('  últimos %dd: %s llamadas · %s tokens'
           % (DIAS, recientes['n'] or 0, recientes['t'] or 0))

    # Cero consumo con trafico alto casi siempre es el modo de bot, no una falla.
    # Los valores reales son 'ninguno' | 'tradicional' | 'ia' | 'hibrido'.
    MODOS_CON_IA = ('ia', 'hibrido')
    if not recientes['n']:
        con_ia = list(SesionWhatsApp.objects.filter(
            status=True, activo=True, modo_bot__in=MODOS_CON_IA))
        sin_ia = list(SesionWhatsApp.objects.filter(
            status=True, activo=True).exclude(modo_bot__in=MODOS_CON_IA))
        if not con_ia:
            _linea('  sin consumo porque ninguna sesión activa usa IA:')
        else:
            _linea('  %d sesión(es) en modo IA pero sin consumo — o no tuvieron tráfico, '
                   'o el flujo resolvió todo antes de llamar al LLM:' % len(con_ia))
            for s in con_ia:
                _linea('    %-26s modo=%-12s (IA activa)' % ((s.nombre or '?')[:26], s.modo_bot))
        for s in sin_ia:
            _linea('    %-26s modo=%-12s (no llama al LLM)' % ((s.nombre or '?')[:26], s.modo_bot))

    _linea()
    _linea('Agentes:')
    from agents_ai.rag import weaviate as wv
    for a in AgentesIA.objects.filter(status=True).order_by('nombre'):
        keys = a.apikey.filter(estado=True, status=True).count()
        try:
            frag = wv.contar(a.id)
        except Exception:
            frag = None
        avisos = []
        if not keys:
            avisos.append('SIN KEY ACTIVA')
        if frag == 0:
            avisos.append('sin conocimiento vectorizado')
        if avisos:
            _linea('  %-26s %s' % (a.nombre[:26], ' · '.join(avisos)))
    _linea('  (los agentes que no aparecen están correctos)')

    caidas = ApiKeyIA.objects.filter(status=True, estado=False)
    if caidas:
        _linea()
        _linea('Keys caídas: %s' % ', '.join(
            '%s/%s' % (k.get_proveedor_display(), k.alias or k.id) for k in caidas))


_regla('EVALUACIÓN DE CANALES · %s · ventana %d días'
       % (timezone.now().strftime('%Y-%m-%d %H:%M'), DIAS))
for nombre, proveedor, attr in CANALES:
    evaluar_canal(nombre, proveedor, attr)

_regla('COMENTARIOS SOCIALES')
evaluar_comentarios()

_regla('ANTI-BANEO (gateway Baileys)')
evaluar_antiban()

_regla('INTELIGENCIA ARTIFICIAL')
evaluar_ia()
_linea()
