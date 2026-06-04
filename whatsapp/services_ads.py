"""Cliente de la Marketing API de Meta (anuncios Click-to-WhatsApp).

Lee información de la cuenta publicitaria, campañas y anuncios para poder
mostrar NOMBRES legibles (en vez de IDs crudos) y métricas de gasto/resultados
junto a las conversaciones que entraron por un anuncio CTWA.

Es de solo lectura: usa el scope `ads_read`. La conexión reutiliza el mismo
Meta Business del WhatsApp Cloud API; solo cambia que el token necesita el
permiso de anuncios y se debe conocer el `ad_account_id` (act_XXXX).

Referencia: https://developers.facebook.com/docs/marketing-api/insights
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = 'v21.0'
GRAPH_API_BASE = f'https://graph.facebook.com/{GRAPH_API_VERSION}'

TIMEOUT = 20


def _normalizar_account_id(ad_account_id: str) -> str:
    """Asegura el prefijo act_ que exige la Marketing API."""
    aid = (ad_account_id or '').strip()
    if not aid:
        return ''
    return aid if aid.startswith('act_') else f'act_{aid}'


class MetaAdsService:
    """Wrapper de la Marketing API atado a una ConfigMeta."""

    def __init__(self, config_meta):
        self.config = config_meta
        self.ad_account_id = _normalizar_account_id(getattr(config_meta, 'ad_account_id', ''))
        self.token = (getattr(config_meta, 'ads_access_token', '') or
                      getattr(config_meta, 'access_token', '') or '')

    @property
    def configurado(self) -> bool:
        return bool(self.ad_account_id and self.token)

    def _get(self, path: str, params: dict) -> dict:
        params = dict(params or {})
        params['access_token'] = self.token
        url = f'{GRAPH_API_BASE}/{path}'
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT)
        except requests.RequestException as ex:
            logger.warning('Marketing API error de red: %s', ex)
            return {'error': True, 'message': f'Error de red: {ex}'}
        try:
            data = resp.json()
        except ValueError:
            return {'error': True, 'message': f'Respuesta no-JSON ({resp.status_code}).'}
        if resp.status_code >= 400 or 'error' in data:
            msg = (data.get('error') or {}).get('message') if isinstance(data, dict) else None
            return {'error': True, 'message': msg or f'HTTP {resp.status_code}', 'raw': data}
        return data

    def probar_conexion(self) -> dict:
        """Verifica que el token pueda leer la cuenta publicitaria."""
        if not self.ad_account_id:
            return {'error': True, 'message': 'Falta el ID de la cuenta publicitaria (act_XXXX).'}
        if not self.token:
            return {'error': True, 'message': 'No hay token disponible para anuncios.'}
        data = self._get(self.ad_account_id, {
            'fields': 'name,account_status,currency,amount_spent,business_name',
        })
        if data.get('error'):
            return data
        return {
            'error': False,
            'name': data.get('name'),
            'currency': data.get('currency'),
            'account_status': data.get('account_status'),
            'amount_spent': data.get('amount_spent'),
            'business_name': data.get('business_name'),
        }

    def info_anuncio(self, ad_id: str) -> dict:
        """Devuelve nombre del anuncio + adset + campaña para un ad_id."""
        if not ad_id:
            return {'error': True, 'message': 'ad_id vacío.'}
        data = self._get(str(ad_id), {
            'fields': 'name,effective_status,campaign{id,name},adset{id,name}',
        })
        if data.get('error'):
            return data
        campaign = data.get('campaign') or {}
        adset = data.get('adset') or {}
        return {
            'error': False,
            'ad_id': ad_id,
            'ad_name': data.get('name'),
            'effective_status': data.get('effective_status'),
            'campaign_id': campaign.get('id'),
            'campaign_name': campaign.get('name'),
            'adset_id': adset.get('id'),
            'adset_name': adset.get('name'),
        }

    def insights(self, date_preset: str = 'maximum', time_range: Optional[dict] = None,
                 level: str = 'ad', ad_ids: Optional[list] = None) -> dict:
        """Trae métricas de gasto/resultados de la cuenta (por anuncio por defecto).

        `time_range`: {'since': 'YYYY-MM-DD', 'until': 'YYYY-MM-DD'} (tiene
        prioridad sobre date_preset). `ad_ids`: filtra a anuncios puntuales.
        """
        if not self.ad_account_id:
            return {'error': True, 'message': 'Falta el ID de la cuenta publicitaria.'}
        params = {
            'level': level,
            'fields': 'campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,'
                      'spend,impressions,clicks,cpc,cpm,actions',
            'limit': 200,
        }
        if time_range:
            import json as _json
            params['time_range'] = _json.dumps(time_range)
        else:
            params['date_preset'] = date_preset
        if ad_ids:
            import json as _json
            params['filtering'] = _json.dumps([{
                'field': 'ad.id', 'operator': 'IN', 'value': list(ad_ids),
            }])
        data = self._get(f'{self.ad_account_id}/insights', params)
        if data.get('error'):
            return data
        return {'error': False, 'rows': data.get('data', [])}


def ads_service_para_sesion(sesion) -> Optional[MetaAdsService]:
    """Helper: devuelve el servicio de ads si la sesión es Meta y tiene config."""
    cfg = getattr(sesion, 'config_meta', None)
    if not cfg:
        return None
    return MetaAdsService(cfg)


TTL_CACHE_HORAS = 24


def resolver_anuncio(config_meta, ad_id, refrescar: bool = False):
    """Devuelve (o resuelve y cachea) los nombres de un anuncio por su ad_id.

    Cache-first: si hay una fila reciente en AnuncioMetaCache la devuelve sin
    pegarle a Meta. Si no existe (o está vencida / refrescar=True) y hay config
    de ads, consulta la Marketing API y actualiza la caché. Nunca lanza: ante
    cualquier fallo devuelve la caché previa o None.
    """
    from .models import AnuncioMetaCache
    ad_id = (ad_id or '').strip()
    if not ad_id:
        return None

    cache = AnuncioMetaCache.objects.filter(ad_id=ad_id).first()
    fresca = bool(
        cache and cache.ultima_sync and
        cache.ultima_sync > timezone.now() - timedelta(hours=TTL_CACHE_HORAS)
    )
    if cache and fresca and not refrescar:
        return cache

    if not config_meta:
        return cache

    svc = MetaAdsService(config_meta)
    if not svc.configurado:
        return cache

    info = svc.info_anuncio(ad_id)
    if info.get('error'):
        logger.info('No se pudo resolver ad_id=%s: %s', ad_id, info.get('message'))
        return cache

    defaults = {
        'ad_name': (info.get('ad_name') or '')[:300],
        'adset_id': (info.get('adset_id') or '')[:100],
        'adset_name': (info.get('adset_name') or '')[:300],
        'campaign_id': (info.get('campaign_id') or '')[:100],
        'campaign_name': (info.get('campaign_name') or '')[:300],
        'effective_status': (info.get('effective_status') or '')[:40],
        'ultima_sync': timezone.now(),
    }
    cache, _ = AnuncioMetaCache.objects.update_or_create(ad_id=ad_id, defaults=defaults)
    return cache


def nombres_de_anuncios(ad_ids) -> dict:
    """Lee SOLO de caché los nombres de una lista de ad_ids.

    Devuelve {ad_id: {'ad_name', 'campaign_name', 'campaign_id', 'adset_name'}}.
    No pega a Meta — pensado para Analytics (rápido). La caché se llena al abrir
    conversaciones.
    """
    from .models import AnuncioMetaCache
    ids = [str(a).strip() for a in (ad_ids or []) if a]
    if not ids:
        return {}
    out = {}
    for c in AnuncioMetaCache.objects.filter(ad_id__in=ids):
        out[c.ad_id] = {
            'ad_name': c.ad_name,
            'campaign_name': c.campaign_name,
            'campaign_id': c.campaign_id,
            'adset_name': c.adset_name,
        }
    return out
