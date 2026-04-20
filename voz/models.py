"""Modelos de llamadas de voz con IA.

Paralelo conceptual a whatsapp.ConversacionWhatsApp / MensajeWhatsApp pero
para transporte telefonico (Twilio/Jambonz/etc). Deliberadamente ligero por
ahora: el proveedor concreto se guarda en campo libre y el stream_sid
identifica la sesion en el transporte.
"""
from django.db import models

from core.custom_models import ModeloBase


PROVEEDOR_VOZ_CHOICES = (
    ('twilio', 'Twilio'),
    ('jambonz', 'Jambonz'),
    ('webrtc', 'WebRTC (demo)'),
)

ESTADO_LLAMADA_CHOICES = (
    ('iniciando', 'Iniciando'),
    ('en_curso', 'En curso'),
    ('finalizada', 'Finalizada'),
    ('fallida', 'Fallida'),
)


class LlamadaVoz(ModeloBase):
    proveedor = models.CharField(max_length=20, choices=PROVEEDOR_VOZ_CHOICES, default='twilio')
    stream_sid = models.CharField(max_length=80, blank=True, null=True, db_index=True,
                                  help_text='Identificador del stream en el proveedor (Twilio streamSid, etc).')
    call_sid = models.CharField(max_length=80, blank=True, null=True, db_index=True,
                                help_text='Identificador de la llamada en el proveedor.')
    numero_origen = models.CharField(max_length=30, blank=True, null=True)
    numero_destino = models.CharField(max_length=30, blank=True, null=True)
    estado = models.CharField(max_length=15, choices=ESTADO_LLAMADA_CHOICES, default='iniciando')
    fecha_inicio = models.DateTimeField(auto_now_add=True)
    fecha_fin = models.DateTimeField(blank=True, null=True)
    duracion_segundos = models.IntegerField(default=0)
    agente_ia = models.ForeignKey('crm.AgentesIA', on_delete=models.SET_NULL,
                                  blank=True, null=True, related_name='llamadas_voz')
    contacto = models.ForeignKey('whatsapp.Contacto', on_delete=models.SET_NULL,
                                 blank=True, null=True, related_name='llamadas_voz')
    notas = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = 'Llamada de voz'
        verbose_name_plural = 'Llamadas de voz'
        ordering = ['-fecha_inicio']

    def __str__(self):
        return f'Llamada {self.id} {self.numero_origen or "?"} [{self.estado}]'


ROL_CHOICES = (
    ('cliente', 'Cliente'),
    ('ia', 'IA'),
    ('sistema', 'Sistema'),
)


class MensajeVoz(ModeloBase):
    llamada = models.ForeignKey(LlamadaVoz, on_delete=models.CASCADE, related_name='mensajes')
    rol = models.CharField(max_length=10, choices=ROL_CHOICES)
    texto = models.TextField()
    audio = models.FileField(upload_to='voz/audio/%Y/%m/', blank=True, null=True,
                             help_text='Opcional: wav del turno (para replay/debug).')
    latencia_ms = models.IntegerField(default=0, help_text='Latencia STT+LLM+TTS del turno.')
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Mensaje de voz'
        verbose_name_plural = 'Mensajes de voz'
        ordering = ['fecha']

    def __str__(self):
        return f'[{self.rol}] {self.texto[:40]}'
