import os
import sys
from datetime import timedelta

from django.core.wsgi import get_wsgi_application
from django.db.models import F
from django.utils import timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')

application = get_wsgi_application()

from django.core.cache import cache

from core.funciones import logCron
from whatsapp.models import ConversacionWhatsApp, InscripcionSecuencia
from whatsapp.services import get_whatsapp_service


MAX_INTENTOS = 3


def _enviar_paso(inscripcion, paso):
    contacto = inscripcion.contacto
    sesion = contacto.sesion
    if not sesion or not sesion.activo:
        return False, 'Sesión inactiva', False
    conversacion_id = None
    if sesion.proveedor == 'meta':
        if cache.get(f'seq_meta_bloqueado_{inscripcion.id}'):
            return False, 'Ventana 24h Meta bloqueada (backoff vigente)', True
        conv = ConversacionWhatsApp.objects.filter(contacto=contacto).order_by('-id').first()
        conversacion_id = conv.id if conv else None
    service = get_whatsapp_service(sesion)
    response = service.send_text_message(
        sesion.session_id, contacto.from_number, paso.mensaje,
        simularEscritura=True, conversacion_id=conversacion_id,
    )
    if not response.get('success', False):
        if response.get('requiere_plantilla'):
            cache.set(f'seq_meta_bloqueado_{inscripcion.id}', 1, 6 * 3600)
            return False, 'Ventana 24h Meta vencida — backoff 6h', True
        return False, response.get('error') or response.get('message') or 'Falló el envío', False
    return True, 'OK', False


def main():
    ahora = timezone.now()
    pendientes = (InscripcionSecuencia.objects
                  .filter(status=True, estado='activa',
                          proximo_envio__lte=ahora,
                          intentos__lt=MAX_INTENTOS,
                          secuencia__status=True, secuencia__activa=True,
                          contacto__opt_out=False,
                          contacto__whatsapp_invalido=False,
                          contacto__sesion__activo=True,
                          contacto__sesion__proveedor__in=('baileys', 'meta'))
                  .select_related('secuencia', 'contacto__sesion'))
    enviados = 0
    fallidos = 0
    completadas = 0
    for inscripcion in pendientes:
        try:
            pasos = list(inscripcion.secuencia.pasos_activos())
            if inscripcion.paso_actual >= len(pasos):
                InscripcionSecuencia.objects.filter(pk=inscripcion.pk, estado='activa').update(
                    estado='completada', finalizada_en=ahora, proximo_envio=None,
                )
                completadas += 1
                continue
            paso = pasos[inscripcion.paso_actual]
            # Claim atómico ANTES de enviar: dos crons concurrentes no duplican.
            claimed = InscripcionSecuencia.objects.filter(
                pk=inscripcion.pk, estado='activa', paso_actual=inscripcion.paso_actual,
            ).update(paso_actual=inscripcion.paso_actual + 1)
            if not claimed:
                continue
            ok, msg, sin_penalizar = _enviar_paso(inscripcion, paso)
            if ok:
                enviados += 1
                siguiente_idx = inscripcion.paso_actual + 1
                if siguiente_idx >= len(pasos):
                    InscripcionSecuencia.objects.filter(pk=inscripcion.pk).update(
                        estado='completada', finalizada_en=ahora, proximo_envio=None, intentos=0,
                    )
                    completadas += 1
                else:
                    siguiente = pasos[siguiente_idx]
                    InscripcionSecuencia.objects.filter(pk=inscripcion.pk).update(
                        proximo_envio=ahora + timedelta(hours=siguiente.espera_horas), intentos=0,
                    )
                logCron('Secuencias', f'Paso {paso.orden} de "{inscripcion.secuencia.nombre}" enviado a contacto {inscripcion.contacto_id}', True)
            else:
                # Revertir el claim; el paso queda pendiente para el próximo tick.
                if sin_penalizar:
                    InscripcionSecuencia.objects.filter(pk=inscripcion.pk).update(
                        paso_actual=F('paso_actual') - 1,
                    )
                else:
                    fallidos += 1
                    InscripcionSecuencia.objects.filter(pk=inscripcion.pk).update(
                        paso_actual=F('paso_actual') - 1, intentos=F('intentos') + 1,
                    )
                    if inscripcion.intentos + 1 >= MAX_INTENTOS:
                        InscripcionSecuencia.objects.filter(pk=inscripcion.pk).update(
                            estado='error', finalizada_en=ahora,
                        )
                logCron('Secuencias', f'Falló paso {paso.orden} de "{inscripcion.secuencia.nombre}" para contacto {inscripcion.contacto_id}: {msg}', False)
        except Exception as ex:
            fallidos += 1
            logCron('Secuencias', f'Excepción en inscripción {inscripcion.id}: {ex}', False)
    logCron('Secuencias', f'Ejecución completada. Enviados={enviados}, fallidos={fallidos}, completadas={completadas}', True)


if __name__ == '__main__':
    main()
