"""Centro de canal — guía instructiva de módulos por canal (WhatsApp/Instagram/Facebook/TikTok).

Página de orientación: qué es cada módulo, para qué sirve, cuándo usarlo y en
qué orden conviene configurarlo. Los wrappers por canal viven en
`instagram/view_centro.py`, `facebook/view_centro.py` y `tiktok/view_centro.py`.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from core.funciones import addData, secure_module

NIVELES = {
    'esencial': ('Esencial', 'bg-danger'),
    'recomendado': ('Recomendado', 'bg-primary'),
    'avanzado': ('Avanzado', 'bg-secondary'),
}

GUIAS_CANAL = {
    'whatsapp': {
        'titulo': 'Centro WhatsApp',
        'icono': 'fa-brands fa-whatsapp',
        'descripcion': 'Guía de todos los módulos del canal WhatsApp: qué hace cada uno, cuándo usarlo y el orden recomendado para dejar tu operación funcionando.',
        'fases': [
            {
                'titulo': '1. Conexión y configuración',
                'descripcion': 'Lo primero: conectar tu número y definir cuándo atiendes.',
                'modulos': [
                    {'nombre': 'Sesiones', 'url': '/whatsapp/sesiones/', 'icono': 'fa fa-plug', 'nivel': 'esencial',
                     'para_que': 'Conectar tus números de WhatsApp: por QR (WhatsApp Web) o por la API oficial de Meta.',
                     'cuando': 'Es el punto de partida — sin sesión conectada ningún otro módulo funciona. Aquí también eliges el modo de bot (IA, flujo tradicional, híbrido o solo humanos) y asignas asesores.'},
                    {'nombre': 'Credenciales Meta', 'url': '/seguridad/credencial-meta/', 'icono': 'fa fa-key', 'nivel': 'esencial',
                     'para_que': 'Registrar las credenciales de tu Meta App (App ID, Secret, token) para usar la API oficial.',
                     'cuando': 'Solo si vas a conectar números por API oficial de Meta, Instagram o Facebook. Con QR/Baileys no hace falta.'},
                    {'nombre': 'Horarios de atención', 'url': '/whatsapp/horarios/', 'icono': 'fa fa-clock', 'nivel': 'recomendado',
                     'para_que': 'Definir franjas de atención por día, feriados y el mensaje automático fuera de horario.',
                     'cuando': 'Apenas conectes la sesión, para que los clientes que escriben de madrugada reciban respuesta y expectativa clara.'},
                ],
            },
            {
                'titulo': '2. Automatización (el bot)',
                'descripcion': 'Decide quién responde: agente IA, flujo de botones, o ambos.',
                'modulos': [
                    {'nombre': 'Entrenamiento IA', 'url': '/crm/entrenamiento/', 'icono': 'fa fa-robot', 'nivel': 'esencial',
                     'para_que': 'Crear y entrenar agentes IA: personalidad, documentos de conocimiento, FAQs, herramientas y memoria.',
                     'cuando': 'Si tu sesión usa modo IA o híbrido. Empieza con el asistente rápido (wizard) y ve puliendo con las FAQs y el auditor.'},
                    {'nombre': 'Mensajería Instantánea (flujos)', 'url': '/crm/departamentos_chatbots/', 'icono': 'fa fa-diagram-project', 'nivel': 'recomendado',
                     'para_que': 'Diseñar flujos visuales de botones y menús (estilo árbol): preguntas, validaciones, llamadas a APIs, handoff a humano y reserva de citas.',
                     'cuando': 'Para procesos estructurados (cotizadores, agendamiento, triaje por departamentos) donde quieres control total del camino.'},
                    {'nombre': 'Agenda', 'url': '/agenda/configuracion/', 'icono': 'fa fa-calendar-check', 'nivel': 'avanzado',
                     'para_que': 'Configurar recursos, servicios y horarios para que el bot agende citas solo, con recordatorios automáticos que el cliente confirma o cancela respondiendo.',
                     'cuando': 'Si tu negocio trabaja con citas o turnos (consultorios, salones, asesorías).'},
                ],
            },
            {
                'titulo': '3. Audiencia y marketing',
                'descripcion': 'Organiza tus contactos y véndeles: etiquetas, segmentos, campañas y goteo.',
                'modulos': [
                    {'nombre': 'Contactos', 'url': '/whatsapp/contacto/', 'icono': 'fa fa-address-book', 'nivel': 'esencial',
                     'para_que': 'Tu base de datos: importación masiva desde Excel, campos personalizados, bajas (opt-out) y duplicados.',
                     'cuando': 'Importa tu base apenas conectes; el resto de contactos se crean solos cuando la gente escribe.'},
                    {'nombre': 'Etiquetas', 'url': '/whatsapp/etiquetas/', 'icono': 'fa fa-tags', 'nivel': 'esencial',
                     'para_que': 'Marcadores libres (VIP, Lead caliente, Newsletter) para clasificar contactos.',
                     'cuando': 'Desde el primer día — son la base de segmentos, campañas y secuencias.'},
                    {'nombre': 'Segmentos', 'url': '/whatsapp/segmentos/', 'icono': 'fa fa-filter', 'nivel': 'recomendado',
                     'para_que': 'Filtros guardados que se recalculan solos: combina etiquetas, canal, campos personalizados y actividad reciente.',
                     'cuando': 'Cuando repites la misma audiencia en varias campañas ("VIP sin compra en 30 días") — defínela una vez y reutilízala.'},
                    {'nombre': 'Plantillas Meta', 'url': '/whatsapp/plantillas/', 'icono': 'fa fa-file-lines', 'nivel': 'recomendado',
                     'para_que': 'Crear y someter a aprobación las plantillas oficiales de Meta (con variables y botones).',
                     'cuando': 'Obligatorias en API oficial para escribirle a alguien fuera de la ventana de 24 horas. Genera borradores con IA.'},
                    {'nombre': 'Campañas', 'url': '/whatsapp/campanas/', 'icono': 'fa fa-bullhorn', 'nivel': 'recomendado',
                     'para_que': 'Envíos masivos segmentados con velocidad controlada y tope diario según tu nivel de Meta.',
                     'cuando': 'Promociones y anuncios puntuales a una audiencia (etiquetas o segmento).'},
                    {'nombre': 'Secuencias', 'url': '/whatsapp/secuencias/', 'icono': 'fa fa-stream', 'nivel': 'recomendado',
                     'para_que': 'Series de mensajes por goteo con esperas entre pasos; el contacto entra por etiqueta o a mano y sale solo al responder.',
                     'cuando': 'Seguimientos automáticos: bienvenida de leads, post-venta, reactivación. Lo que en ManyChat son las "sequences".'},
                    {'nombre': 'Enlaces de captación', 'url': '/whatsapp/enlaces/', 'icono': 'fa fa-link', 'nivel': 'recomendado',
                     'para_que': 'Links wa.me con seguimiento y QR: cada canal (bio de Instagram, volante, local) etiqueta a sus leads, puede dispararles una secuencia y cuenta cuántos llegaron.',
                     'cuando': 'Cuando quieras saber de dónde viene cada lead y automatizar su primera atención según el origen.'},
                    {'nombre': 'Tarifas Meta', 'url': '/whatsapp/tarifas/', 'icono': 'fa fa-coins', 'nivel': 'avanzado',
                     'para_que': 'Registrar los precios por país/categoría y simular el costo de tus envíos masivos.',
                     'cuando': 'Antes de lanzar campañas grandes por API oficial, para presupuestar.'},
                ],
            },
            {
                'titulo': '4. Operación diaria',
                'descripcion': 'Donde tu equipo vive: la bandeja de conversaciones y el tablero de ventas.',
                'modulos': [
                    {'nombre': 'Conversaciones', 'url': '/whatsapp/conversaciones/', 'icono': 'fa fa-comments', 'nivel': 'esencial',
                     'para_que': 'La bandeja en vivo: responder, asignar asesores, pausar el bot, plantillas rápidas, notas de voz transcritas y ficha del cliente.',
                     'cuando': 'Todos los días. Los asesores toman conversaciones cuando el bot hace handoff o cuando quieren intervenir.'},
                    {'nombre': 'Conversaciones finalizadas', 'url': '/whatsapp/conversaciones-finalizadas/', 'icono': 'fa fa-box-archive', 'nivel': 'recomendado',
                     'para_que': 'Historial de conversaciones cerradas con resumen IA y sentimiento; permite reactivar dentro de la ventana.',
                     'cuando': 'Para auditar atención pasada o retomar un cliente que quedó frío.'},
                    {'nombre': 'Pendientes de reconexión', 'url': '/whatsapp/conversaciones-pendiente-reconexion/', 'icono': 'fa fa-rotate-left', 'nivel': 'avanzado',
                     'para_que': 'Conversaciones marcadas para reenganchar con plantilla cuando venció la ventana de 24h.',
                     'cuando': 'Cuando manejas volumen por API oficial y no quieres perder leads por la ventana.'},
                    {'nombre': 'Pipeline de ventas', 'url': '/whatsapp/pipeline/', 'icono': 'fa fa-table-columns', 'nivel': 'recomendado',
                     'para_que': 'Tablero Kanban de oportunidades: etapas con probabilidad, valor estimado y comentarios; al ganar reporta conversión a Meta.',
                     'cuando': 'Cuando vendes con seguimiento y quieres pronóstico de cierre, no solo chats sueltos.'},
                    {'nombre': 'Citas', 'url': '/agenda/citas/', 'icono': 'fa fa-calendar-days', 'nivel': 'avanzado',
                     'para_que': 'Calendario de turnos: crear, reagendar, marcar cumplido/no asistió.',
                     'cuando': 'La vista diaria del equipo si usas el módulo de agenda.'},
                ],
            },
            {
                'titulo': '5. Medición y control',
                'descripcion': 'Qué está funcionando, quién atiende bien y por qué falló un mensaje.',
                'modulos': [
                    {'nombre': 'Analytics', 'url': '/whatsapp/analytics/', 'icono': 'fa fa-chart-line', 'nivel': 'recomendado',
                     'para_que': 'KPIs y gráficos: conversaciones, leads, % de respuesta IA, consumo facturable de Meta, ROI de anuncios Click-to-WhatsApp.',
                     'cuando': 'Revisión semanal del negocio.'},
                    {'nombre': 'Supervisión', 'url': '/whatsapp/supervision/', 'icono': 'fa fa-eye', 'nivel': 'recomendado',
                     'para_que': 'Embudo de prospectos, rendimiento por asesor y monitor en vivo de esperas.',
                     'cuando': 'Para líderes de equipo: detectar conversaciones demoradas al momento.'},
                    {'nombre': 'Trazas / Logs', 'url': '/whatsapp/trazas/', 'icono': 'fa fa-bug', 'nivel': 'avanzado',
                     'para_que': 'El detective: timeline completo de cada mensaje por el pipeline (webhook → IA → envío) con errores y tokens.',
                     'cuando': 'Cuando algo no respondió y necesitas saber exactamente por qué.'},
                ],
            },
        ],
    },
    'instagram': {
        'titulo': 'Centro Instagram',
        'icono': 'fa-brands fa-instagram',
        'descripcion': 'Guía del canal Instagram: conecta tu cuenta, atiende DMs, modera comentarios y convierte seguidores en clientes.',
        'fases': [
            {
                'titulo': '1. Conexión',
                'descripcion': 'Credenciales de Meta y tu cuenta Business de Instagram.',
                'modulos': [
                    {'nombre': 'Credenciales Meta', 'url': '/seguridad/credencial-meta/', 'icono': 'fa fa-key', 'nivel': 'esencial',
                     'para_que': 'Registrar la Meta App (App ID, Secret, token) que da acceso a la API de Instagram.',
                     'cuando': 'Primero de todo — Instagram siempre requiere la API oficial de Meta.'},
                    {'nombre': 'Sesiones Instagram', 'url': '/instagram/sesiones/', 'icono': 'fa fa-plug', 'nivel': 'esencial',
                     'para_que': 'Conectar tu cuenta Business: con el Access Token se autodetecta la página y el usuario IG.',
                     'cuando': 'Después de las credenciales. Aquí también asignas el agente IA y el modo de bot.'},
                ],
            },
            {
                'titulo': '2. Atención y moderación',
                'descripcion': 'DMs y comentarios en un solo lugar.',
                'modulos': [
                    {'nombre': 'Conversaciones Instagram', 'url': '/instagram/conversaciones/', 'icono': 'fa fa-comments', 'nivel': 'esencial',
                     'para_que': 'La bandeja de DMs de Instagram con el mismo motor que WhatsApp: bot IA, asignación de asesores, tiempo real.',
                     'cuando': 'Todos los días — cada DM entra aquí y el bot responde según el modo configurado.'},
                    {'nombre': 'Comentarios', 'url': '/instagram/comentarios/', 'icono': 'fa fa-comment-dots', 'nivel': 'recomendado',
                     'para_que': 'Moderar comentarios de tus publicaciones: responder público, ocultar, o llevar al autor a DM (private reply).',
                     'cuando': 'Cuando publicas contenido con interacción — cada comentario es un lead potencial que puedes convertir en conversación.'},
                    {'nombre': 'Reglas de comentarios', 'url': '/instagram/reglas-comentarios/', 'icono': 'fa fa-wand-magic-sparkles', 'nivel': 'recomendado',
                     'para_que': 'Automatizar los comentarios: si contiene una keyword (ej. "precio"), responde público, manda DM al autor y lo etiqueta — sin intervención humana.',
                     'cuando': 'Cuando lanzas posts tipo "comenta INFO y te escribo" — el growth tool clásico de Instagram.'},
                    {'nombre': 'Publicaciones', 'url': '/instagram/publicaciones/', 'icono': 'fa fa-images', 'nivel': 'recomendado',
                     'para_que': 'Ver tus posts en vivo con likes y comentarios, y moderarlos sin salir del panel.',
                     'cuando': 'Para trabajar los comentarios post por post.'},
                ],
            },
            {
                'titulo': '3. Automatización y marketing',
                'descripcion': 'El mismo cerebro que WhatsApp, aplicado a Instagram.',
                'modulos': [
                    {'nombre': 'Entrenamiento IA', 'url': '/crm/entrenamiento/', 'icono': 'fa fa-robot', 'nivel': 'recomendado',
                     'para_que': 'El agente IA que responde DMs es el mismo que entrenas para WhatsApp — un solo entrenamiento, todos los canales.',
                     'cuando': 'Al conectar la sesión, asígnale un agente entrenado.'},
                    {'nombre': 'Campañas', 'url': '/whatsapp/campanas/', 'icono': 'fa fa-bullhorn', 'nivel': 'avanzado',
                     'para_que': 'Los envíos masivos soportan canal Instagram para contactos que ya te escribieron.',
                     'cuando': 'Reactivación de audiencia IG dentro de las ventanas permitidas.'},
                    {'nombre': 'Analytics', 'url': '/whatsapp/analytics/', 'icono': 'fa fa-chart-line', 'nivel': 'recomendado',
                     'para_que': 'Las métricas incluyen el canal de origen — filtra conversaciones y leads que llegaron por Instagram.',
                     'cuando': 'Revisión semanal.'},
                ],
            },
        ],
    },
    'facebook': {
        'titulo': 'Centro Facebook',
        'icono': 'fa-brands fa-facebook',
        'descripcion': 'Guía del canal Facebook: conecta tu página, atiende Messenger, modera los comentarios de tus publicaciones y convierte seguidores en clientes.',
        'fases': [
            {
                'titulo': '1. Conexión',
                'descripcion': 'Credenciales de Meta y tu página de Facebook.',
                'modulos': [
                    {'nombre': 'Credenciales Meta', 'url': '/seguridad/credencial-meta/', 'icono': 'fa fa-key', 'nivel': 'esencial',
                     'para_que': 'Registrar la Meta App (App ID, Secret, token) que da acceso a la API de páginas y Messenger.',
                     'cuando': 'Primero de todo — Facebook siempre requiere la API oficial de Meta.'},
                    {'nombre': 'Sesiones Facebook', 'url': '/facebook/sesiones/', 'icono': 'fa fa-plug', 'nivel': 'esencial',
                     'para_que': 'Conectar tu página: con el Access Token se autodetecta el Page ID y el nombre de la página.',
                     'cuando': 'Después de las credenciales. Aquí también asignas el agente IA y el modo de bot.'},
                ],
            },
            {
                'titulo': '2. Atención y moderación',
                'descripcion': 'Messenger y comentarios del feed en un solo lugar.',
                'modulos': [
                    {'nombre': 'Conversaciones Facebook', 'url': '/facebook/conversaciones/', 'icono': 'fa fa-comments', 'nivel': 'esencial',
                     'para_que': 'La bandeja de Messenger con el mismo motor que WhatsApp: bot IA, asignación de asesores, tiempo real.',
                     'cuando': 'Todos los días — cada mensaje de Messenger entra aquí y el bot responde según el modo configurado.'},
                    {'nombre': 'Comentarios', 'url': '/facebook/comentarios/', 'icono': 'fa fa-comment-dots', 'nivel': 'recomendado',
                     'para_que': 'Moderar los comentarios de los posts de tu página: responder público, ocultar, o llevar al autor a Messenger (private reply).',
                     'cuando': 'Cuando publicas contenido con interacción — cada comentario es un lead potencial que puedes convertir en conversación.'},
                    {'nombre': 'Reglas de comentarios', 'url': '/facebook/reglas-comentarios/', 'icono': 'fa fa-wand-magic-sparkles', 'nivel': 'recomendado',
                     'para_que': 'Automatizar los comentarios: si contiene una keyword (ej. "precio"), responde público, manda DM al autor por Messenger y lo etiqueta — sin intervención humana.',
                     'cuando': 'Cuando lanzas posts tipo "comenta INFO y te escribo" — el growth tool clásico, ahora en tu página.'},
                    {'nombre': 'Publicaciones', 'url': '/facebook/publicaciones/', 'icono': 'fa fa-images', 'nivel': 'recomendado',
                     'para_que': 'Ver los posts de tu página en vivo con likes y comentarios, y moderarlos sin salir del panel.',
                     'cuando': 'Para trabajar los comentarios post por post.'},
                ],
            },
            {
                'titulo': '3. Automatización y marketing',
                'descripcion': 'El mismo cerebro que WhatsApp, aplicado a tu página.',
                'modulos': [
                    {'nombre': 'Entrenamiento IA', 'url': '/crm/entrenamiento/', 'icono': 'fa fa-robot', 'nivel': 'recomendado',
                     'para_que': 'El agente IA que responde Messenger es el mismo que entrenas para WhatsApp — un solo entrenamiento, todos los canales.',
                     'cuando': 'Al conectar la sesión, asígnale un agente entrenado.'},
                    {'nombre': 'Campañas', 'url': '/whatsapp/campanas/', 'icono': 'fa fa-bullhorn', 'nivel': 'avanzado',
                     'para_que': 'Los envíos masivos soportan canal Messenger para contactos que ya te escribieron.',
                     'cuando': 'Reactivación de audiencia dentro de las ventanas permitidas por Meta.'},
                    {'nombre': 'Analytics', 'url': '/whatsapp/analytics/', 'icono': 'fa fa-chart-line', 'nivel': 'recomendado',
                     'para_que': 'Las métricas incluyen el canal de origen — filtra conversaciones y leads que llegaron por Messenger.',
                     'cuando': 'Revisión semanal.'},
                ],
            },
        ],
    },
    'tiktok': {
        'titulo': 'Centro TikTok',
        'icono': 'fa-brands fa-tiktok',
        'descripcion': 'Guía del canal TikTok (beta): deja tu cuenta pre-registrada para activarla apenas TikTok apruebe el acceso a su Business Messaging API.',
        'fases': [
            {
                'titulo': '1. Pre-registro (disponible hoy)',
                'descripcion': 'La API de mensajería de TikTok está en beta con aprobación por solicitud.',
                'modulos': [
                    {'nombre': 'Sesiones TikTok', 'url': '/tiktok/sesiones/', 'icono': 'fa fa-plug', 'nivel': 'esencial',
                     'para_que': 'Pre-registrar tu cuenta Business (usuario, business ID, tokens OAuth) y dejarla lista.',
                     'cuando': 'Ahora — cuando TikTok apruebe el acceso, la sesión se activa sin reconfigurar nada.'},
                ],
            },
            {
                'titulo': '2. Atención (se activa con la aprobación)',
                'descripcion': 'Los mismos módulos de WhatsApp/Instagram, con branding TikTok.',
                'modulos': [
                    {'nombre': 'Conversaciones TikTok', 'url': '/tiktok/conversaciones/', 'icono': 'fa fa-comments', 'nivel': 'recomendado',
                     'para_que': 'Bandeja de mensajes directos de TikTok con bot IA, asignación y tiempo real.',
                     'cuando': 'Se pobla automáticamente cuando el webhook empiece a recibir mensajes.'},
                    {'nombre': 'Comentarios TikTok', 'url': '/tiktok/comentarios/', 'icono': 'fa fa-comment-dots', 'nivel': 'recomendado',
                     'para_que': 'Moderación de comentarios de tus videos (fase 2 de la integración).',
                     'cuando': 'Pendiente de la aprobación de la Comments API.'},
                ],
            },
        ],
    },
}


def _render_centro(request, canal):
    guia = GUIAS_CANAL[canal]
    data = {
        'titulo': guia['titulo'],
        'descripcion': guia['descripcion'],
        'ruta': request.path,
        'guia': guia,
        'niveles': NIVELES,
    }
    addData(request, data)
    return render(request, 'whatsapp/centro/centro.html', data)


@login_required
@secure_module
def centroWhatsappView(request):
    return _render_centro(request, 'whatsapp')
