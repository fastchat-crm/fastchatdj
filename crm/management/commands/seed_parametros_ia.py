"""Siembra los Parámetros IA (tabla ParametroSistema) y registra el módulo del menú.

Idempotente: crea las filas que falten y actualiza sus metadatos (etiqueta,
descripción, tipo, unidad, orden, valor_default), pero NUNCA pisa el `valor`
que un administrador haya editado en /crm/parametros-ia/.

Uso en producción:
    python manage.py seed_parametros_ia
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from seguridad.models import ParametroSistema, Modulo

PARAMETROS = [
    # (clave, grupo, tipo, valor_default, unidad, orden, etiqueta, descripcion)
    ('faqs_en_prompt', 'comportamiento_ia', 'entero', '5', 'FAQs', 10,
     'FAQs incluidas en el prompt', 'Cantidad de preguntas frecuentes que se inyectan al contexto.'),
    ('cfg_faiss_k', 'comportamiento_ia', 'entero', '5', 'chunks', 20,
     'Chunks RAG a recuperar (k)', 'Cuántos fragmentos relevantes se recuperan del conocimiento.'),
    ('cfg_faiss_fetch_k', 'comportamiento_ia', 'entero', '20', 'chunks', 30,
     'Candidatos pre-MMR (fetch_k)', 'Candidatos que se evalúan antes de diversificar (MMR).'),
    ('cfg_max_context_chars', 'comportamiento_ia', 'entero', '4000', 'chars', 40,
     'Techo de contexto RAG (específica)', 'Máximo de caracteres de contexto recuperado en consultas específicas.'),
    ('cfg_max_static_chars', 'comportamiento_ia', 'entero', '1200', 'chars', 50,
     'Suplemento de contexto estático', 'Caracteres de contexto estático que acompañan al RAG.'),
    ('cfg_history_turns', 'comportamiento_ia', 'entero', '5', 'turnos', 60,
     'Turnos de historial', 'Cuántos turnos recientes se conservan para continuidad.'),
    ('cfg_user_snippet', 'comportamiento_ia', 'entero', '150', 'chars', 70,
     'Chars por mensaje de usuario', 'Recorte de cada mensaje del cliente en el historial.'),
    ('cfg_ai_snippet', 'comportamiento_ia', 'entero', '400', 'chars', 80,
     'Chars por respuesta IA', 'Recorte de cada respuesta del bot en el historial.'),
    ('cfg_max_output_tokens', 'comportamiento_ia', 'entero', '3000', 'tokens', 90,
     'Techo de salida (consulta amplia)', 'Máximo de tokens de salida en consultas amplias (menú/catálogo).'),
    ('cfg_topic_anchor_chars', 'comportamiento_ia', 'entero', '180', 'chars', 100,
     'Ancla de tema', 'Caracteres del primer mensaje sustantivo usados como ancla semántica.'),
    ('cfg_umbral_distancia', 'comportamiento_ia', 'decimal', '1.4', '', 110,
     'Umbral de distancia de relevancia', 'Distancia máxima para considerar relevante un fragmento (menor = más estricto).'),
    ('cfg_max_static_amplia', 'comportamiento_ia', 'entero', '12000', 'chars', 120,
     'Techo de estático (amplia)', 'Máximo de contexto estático en consultas amplias.'),
    ('memoria_rag_activa', 'comportamiento_ia', 'booleano', 'true', '', 130,
     'Memoria RAG por agente', 'Si el agente aprende de conversaciones previas.'),

    ('tope_tokens_diario', 'limites', 'entero', '0', 'tokens', 10,
     'Tope de tokens por día', 'Máximo de tokens IA consumidos por día en toda la plataforma. 0 = sin tope.'),
    ('tope_tokens_mensual', 'limites', 'entero', '0', 'tokens', 20,
     'Tope de tokens por mes', 'Máximo de tokens IA consumidos por mes en toda la plataforma. 0 = sin tope.'),
    ('anti_rafaga_mensajes_minuto', 'limites', 'entero', '0', 'msgs/min', 30,
     'Anti-ráfaga por conversación', 'Máximo de respuestas IA por minuto en una misma conversación. 0 = sin tope.'),
    ('alerta_saldo_bajo_tokens', 'limites', 'entero', '0', 'tokens', 40,
     'Aviso de consumo alto', 'Emite un aviso cuando el consumo mensual supera este umbral. 0 = sin aviso.'),
]

MODULO_URL = '/crm/parametros-ia/'
MODULO_NOMBRE = 'Parámetros IA'


class Command(BaseCommand):
    help = 'Siembra los Parámetros IA (ParametroSistema) y registra el módulo del menú.'

    @transaction.atomic
    def handle(self, *args, **options):
        creados = actualizados = 0
        for clave, grupo, tipo, valor_default, unidad, orden, etiqueta, descripcion in PARAMETROS:
            fila = ParametroSistema.objects.filter(clave=clave).first()
            if fila is None:
                fila = ParametroSistema(clave=clave)
                creados += 1
            else:
                actualizados += 1
            fila.grupo = grupo
            fila.tipo = tipo
            fila.valor_default = valor_default
            fila.unidad = unidad
            fila.orden = orden
            fila.etiqueta = etiqueta
            fila.descripcion = descripcion
            fila.editable = True
            fila.status = True
            fila.save()

        modulo, creado_mod = Modulo.objects.get_or_create(
            url=MODULO_URL, defaults={'nombre': MODULO_NOMBRE, 'orden': 0}
        )
        if not creado_mod and modulo.nombre != MODULO_NOMBRE:
            modulo.nombre = MODULO_NOMBRE
            modulo.save()

        self.stdout.write(self.style.SUCCESS(
            'Parámetros IA: {} creados, {} actualizados. Módulo "{}" {}.'.format(
                creados, actualizados, MODULO_URL,
                'creado' if creado_mod else 'ya existía',
            )
        ))
