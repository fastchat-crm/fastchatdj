"""Health check liviano para balanceadores / monitoreo.

GET /health/ → 200 si BD (y Redis cuando aplica) responden; 503 si algo falla.
No requiere autenticación. No expone datos sensibles, solo flags de estado.
"""
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def health_view(request):
    estado = {'db': False, 'redis': None}

    try:
        with connection.cursor() as cur:
            cur.execute('SELECT 1')
            cur.fetchone()
        estado['db'] = True
    except Exception as ex:
        estado['db_error'] = str(ex)[:200]

    if getattr(settings, 'CACHES_REDIS', None):
        try:
            import redis
            cliente = redis.Redis(
                host=settings.REDIS_HOST,
                port=int(settings.REDIS_PORT),
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            cliente.ping()
            estado['redis'] = True
        except Exception as ex:
            estado['redis'] = False
            estado['redis_error'] = str(ex)[:200]

    ok = bool(estado['db']) and estado['redis'] is not False
    return JsonResponse({'ok': ok, **estado}, status=200 if ok else 503)
