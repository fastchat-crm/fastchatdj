"""Genera PDFs de la documentación con diseño profesional.

Uso:
    python docs/generar_pdfs.py

Salida:
    docs/pdf/00_indice_urls_modulos.pdf
    docs/pdf/01_meta_setup.pdf
    docs/pdf/02_crm_features.pdf
    docs/pdf/03_tutorial_paso_a_paso.pdf
    docs/pdf/04_chatbot_tradicional.pdf

Requiere: markdown, xhtml2pdf.
"""
import os
import re
import sys
from datetime import datetime

import markdown
from xhtml2pdf import pisa


DOCS_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(DOCS_DIR, 'pdf')

BRAND = {
    'primary':    '#1e40af',   # Azul principal
    'primary_dk': '#1e3a8a',
    'accent':     '#059669',   # Verde éxito
    'warning':    '#d97706',
    'danger':     '#dc2626',
    'light':      '#f1f5f9',
    'border':     '#cbd5e1',
    'text':       '#1e293b',
    'muted':      '#64748b',
}

DOCUMENTOS = [
    {
        'orden': '01',
        'src':    'meta_setup.md',
        'pdf':    '01_meta_setup.pdf',
        'titulo': 'Meta Cloud API',
        'subtitulo': 'Guía de configuración para WhatsApp Business oficial',
        'emoji':   '🔧',
        'color':   BRAND['primary'],
        'descripcion': 'Paso a paso para conectar tu número de WhatsApp a Meta Cloud API (proveedor oficial). Incluye creación de app en Meta Developer Portal, obtención de tokens, configuración de webhooks y validación.',
    },
    {
        'orden': '02',
        'src':    'crm_features.md',
        'pdf':    '02_crm_features.pdf',
        'titulo': 'CRM Features',
        'subtitulo': 'Referencia técnica completa de todas las funcionalidades',
        'emoji':   '📘',
        'color':   BRAND['primary'],
        'descripcion': 'Arquitectura, modelos de datos, servicios, webhooks, API REST y flujo end-to-end desde un anuncio Instagram hasta una venta reportada a Meta Ads.',
    },
    {
        'orden': '03',
        'src':    'tutorial_paso_a_paso.md',
        'pdf':    '03_tutorial_paso_a_paso.pdf',
        'titulo': 'Tutorial paso a paso',
        'subtitulo': 'Guía práctica con 7 casos de uso por industria',
        'emoji':   '🎓',
        'color':   BRAND['accent'],
        'descripcion': 'Desde el primer arranque hasta campañas CTWA. Incluye casos de uso específicos para e-commerce, restaurante, inmobiliaria, clínica, instituto, agencia de servicios y B2B.',
    },
    {
        'orden': '04',
        'src':    'chatbot_tradicional.md',
        'pdf':    '04_chatbot_tradicional.pdf',
        'titulo': 'Chatbot Tradicional',
        'subtitulo': 'Flujos conversacionales sin IA',
        'emoji':   '🤖',
        'color':   BRAND['warning'],
        'descripcion': 'Cómo construir menús, palabras clave y flujos determinísticos para automatizar respuestas sin depender de LLMs.',
    },
]


# ----------------------------------------------------------------------------
# Inventario de URLs agrupadas por módulo
# ----------------------------------------------------------------------------

URLS_POR_MODULO = [
    {
        'modulo': 'Panel y cuenta',
        'color': BRAND['muted'],
        'icono': 'P',
        'urls': [
            ('Panel principal',          '/panel/',           'Dashboard de inicio'),
            ('Notificaciones',           '/notificaciones/',  'Centro de notificaciones del usuario'),
            ('Mi perfil',                '/perfilpanel/',     'Editar datos del usuario actual'),
            ('Documentación',            '/seguridad/documentacion/', 'Visor interno de documentación'),
        ],
    },
    {
        'modulo': 'WhatsApp · Operación diaria',
        'color': BRAND['accent'],
        'icono': 'W',
        'urls': [
            ('Sesiones',                   '/whatsapp/sesiones/',                    'Conectar números WhatsApp (Baileys + Meta)'),
            ('Conversaciones',             '/whatsapp/conversaciones/',              'Inbox unificado en tiempo real'),
            ('Conversaciones finalizadas', '/whatsapp/conversaciones-finalizadas/',  'Historial de conversaciones cerradas'),
            ('Contactos',                  '/whatsapp/contacto/',                    'Gestión de contactos'),
            ('Trazas IA',                  '/whatsapp/trazas/',                      'Diagnóstico paso a paso del pipeline IA'),
            ('Plantillas WhatsApp',        '/whatsapp/plantillas/',                  'Plantillas Meta (UTILITY / MARKETING / AUTHENTICATION)'),
        ],
    },
    {
        'modulo': 'WhatsApp · CRM avanzado',
        'color': BRAND['primary'],
        'icono': 'C',
        'urls': [
            ('Etiquetas (tags)',      '/whatsapp/etiquetas/',  'Tags libres para segmentación de contactos'),
            ('Pipeline de ventas',    '/whatsapp/pipeline/',   'Tablero Kanban con drag & drop'),
            ('Campañas',              '/whatsapp/campanas/',   'Broadcasts segmentados con throttling'),
            ('Horarios de atención',  '/whatsapp/horarios/',   'Business hours + feriados + mensaje fuera de horario'),
            ('Analytics',             '/whatsapp/analytics/',  'Dashboard con KPIs, ROI CTWA y forecast'),
        ],
    },
    {
        'modulo': 'Webhooks entrantes',
        'color': BRAND['warning'],
        'icono': 'H',
        'urls': [
            ('Webhook Baileys',          '/whatsapp/webhook_handler/',        'Eventos del servicio Node.js (Baileys)'),
            ('Webhook Baileys (batch)',  '/whatsapp/webhook_handler/batch/',  'Outbox con ACK por evento'),
            ('Heartbeat Node',           '/whatsapp/heartbeat/',              'Ping del servicio Node cada 30-60s'),
            ('Trazas Node',              '/whatsapp/trace/',                  'Recibe trazas del lado Node.js'),
            ('Webhook Meta Cloud API',   '/whatsapp/meta_webhook/',           'WhatsApp oficial + captura referral CTWA'),
            ('Webhook Instagram DM',     '/whatsapp/instagram_webhook/',      'DMs Instagram Business'),
            ('Webhook Messenger',        '/whatsapp/messenger_webhook/',      'Facebook Messenger Platform'),
        ],
    },
    {
        'modulo': 'REST API v1',
        'color': BRAND['primary_dk'],
        'icono': 'A',
        'subtitulo': 'Requiere header X-API-Key: &lt;NODE_SECRET_KEY&gt; · Rate limit 120 req/min',
        'urls': [
            ('Contactos (listar/crear)',     '/whatsapp/api/v1/contactos/',                             'GET lista · POST crear'),
            ('Detalle contacto',             '/whatsapp/api/v1/contactos/<id>/',                        'GET'),
            ('Conversaciones',               '/whatsapp/api/v1/conversaciones/',                        'GET filtros (sesión, estado, canal, ctwa)'),
            ('Mensajes de conversación',     '/whatsapp/api/v1/conversaciones/<id>/mensajes/',          'GET historial'),
            ('Asignar conversación',         '/whatsapp/api/v1/conversaciones/<id>/asignar/',           'POST manual o round-robin'),
            ('Mover etapa pipeline',         '/whatsapp/api/v1/conversaciones/<id>/etapa/',             'POST etapa_id + valor'),
            ('Enviar mensaje',               '/whatsapp/api/v1/mensajes/enviar/',                       'POST texto por cualquier canal'),
            ('Aplicar etiquetas (bulk)',     '/whatsapp/api/v1/etiquetas/aplicar/',                     'POST contacto_ids + etiqueta_ids'),
            ('Disparar evento CAPI',         '/whatsapp/api/v1/capi/evento/',                           'POST Lead/Purchase manual'),
            ('Stats de campaña',             '/whatsapp/api/v1/campanas/<id>/stats/',                   'GET métricas en vivo'),
        ],
    },
    {
        'modulo': 'APIs legacy',
        'color': BRAND['muted'],
        'icono': 'L',
        'urls': [
            ('Enviar mensaje (legacy)',   '/api/enviar-mensaje/',  'Endpoint heredado, rate-limit 30/min'),
            ('Consultar IA',              '/api/ia/consultar/',    'Consulta directa al agente IA'),
        ],
    },
    {
        'modulo': 'CRM · IA y negocio',
        'color': BRAND['accent'],
        'icono': 'I',
        'urls': [
            ('Perfil del negocio',       '/crm/perfil-negocio/',  'Datos del negocio para IA'),
            ('Agentes IA',               '/crm/agentes-ia/',      'Configuración de agentes (modelo, prompt, contexto)'),
            ('API Keys IA',              '/crm/api-keys/',        'Gestión de keys Gemini / OpenAI'),
            ('Productos / Servicios',    '/crm/productos/',       'Catálogo accesible a la IA'),
            ('Departamentos chatbot',    '/crm/departamentos/',   'Flujos del chatbot tradicional'),
            ('Entrenamientos IA',        '/crm/entrenamientos/',  'Cargar PDF/CSV/XLSX/JSON al vectorstore FAISS'),
            ('Reglas fin de conversación','/crm/reglas-fin/',     'Acciones automáticas al cerrar'),
        ],
    },
    {
        'modulo': 'Seguridad y acceso',
        'color': BRAND['danger'],
        'icono': 'S',
        'urls': [
            ('Usuarios',           '/autenticacion/usuario/',      'Gestión de usuarios del sistema'),
            ('Grupos',             '/seguridad/grupo/',            'Roles y permisos por grupo'),
            ('Módulos',            '/seguridad/modulo/',           'Catálogo de URLs accesibles'),
            ('Configuración',      '/seguridad/configuracion/',    'Singleton de configuración del sitio'),
            ('Empresas',           '/seguridad/empresa/',          'Multi-tenant (parcial)'),
        ],
    },
    {
        'modulo': 'Áreas geográficas',
        'color': BRAND['muted'],
        'icono': 'G',
        'urls': [
            ('Países',      '/area-geografica/pais/',       'Catálogo de países'),
            ('Provincias',  '/area-geografica/provincia/',  'Provincias por país'),
            ('Ciudades',    '/area-geografica/ciudad/',     'Ciudades por provincia'),
            ('Parroquias',  '/area-geografica/parroquia/',  'Subdivisión más fina'),
        ],
    },
    {
        'modulo': 'Admin Django (superusuario)',
        'color': BRAND['primary_dk'],
        'icono': 'D',
        'urls': [
            ('Admin raíz',                   '/admin/',                                'Acceso a todos los modelos'),
            ('Pixels Meta (CAPI)',           '/admin/whatsapp/pixelmeta/',             'Configurar pixels para conversiones'),
            ('Eventos CAPI',                 '/admin/whatsapp/eventocapi/',            'Auditoría de eventos enviados a Meta'),
            ('Disponibilidad de agentes',    '/admin/whatsapp/disponibilidadagente/',  'Configurar agentes para round-robin'),
            ('Webhooks salientes',           '/admin/whatsapp/webhooksaliente/',       'Integraciones outbound estilo Zapier'),
            ('Configuración Instagram',      '/admin/whatsapp/configinstagram/',       'Credenciales IG Business'),
            ('Configuración Messenger',      '/admin/whatsapp/configmessenger/',       'Credenciales FB Messenger'),
            ('Eventos Meta recibidos',       '/admin/whatsapp/eventometarecibido/',    'Auditoría de webhooks entrantes'),
        ],
    },
]


# ============================================================================
# CSS — diseño profesional estilo manual
# ============================================================================

CSS = """
<style>
@page {
    size: letter;
    margin: 2.2cm 1.8cm 2.2cm 1.8cm;
    @frame footer {
        -pdf-frame-content: footerContent;
        bottom: 0.8cm; left: 1.8cm; right: 1.8cm; height: 0.9cm;
    }
    @frame header_frame {
        -pdf-frame-content: headerContent;
        top: 0.8cm; left: 1.8cm; right: 1.8cm; height: 0.9cm;
    }
}

@page cover {
    size: letter;
    margin: 0;
}

body {
    font-family: 'Helvetica', Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.55;
    color: #1e293b;
}

/* --- PORTADA --- */
.cover-page {
    -pdf-frame-border: 0;
    page: cover;
    padding: 0;
    margin: 0;
}
.cover-bg {
    background-color: #1e40af;
    padding: 4cm 2cm 2cm 2cm;
    height: 14cm;
    color: white;
}
.cover-bg-accent {
    background-color: #059669;
    height: 0.4cm;
}
.cover-section {
    padding: 1.5cm 2cm;
}
.cover-brand {
    font-size: 11pt;
    color: #93c5fd;
    text-transform: uppercase;
    letter-spacing: 3px;
    margin-bottom: 1cm;
    font-weight: bold;
}
.cover-title {
    font-size: 36pt;
    color: white;
    font-weight: bold;
    margin: 0;
    padding: 0;
    line-height: 1.1;
}
.cover-subtitle {
    font-size: 14pt;
    color: #bfdbfe;
    margin-top: 0.5cm;
    line-height: 1.4;
}
.cover-meta-block {
    margin-top: 2cm;
    padding: 20px;
    background: #f1f5f9;
    border-left: 6px solid #1e40af;
}
.cover-meta-title {
    color: #1e40af;
    font-size: 11pt;
    font-weight: bold;
    margin-bottom: 6px;
    text-transform: uppercase;
    letter-spacing: 1px;
}
.cover-meta-text {
    color: #475569;
    font-size: 10pt;
    line-height: 1.5;
}
.cover-footer {
    margin-top: 3cm;
    padding-top: 12px;
    border-top: 2px solid #cbd5e1;
    color: #64748b;
    font-size: 9pt;
}

/* --- TÍTULOS --- */
h1 {
    font-size: 20pt;
    color: #1e40af;
    font-weight: bold;
    padding: 8px 0 6px 14px;
    border-left: 6px solid #1e40af;
    background: #eff6ff;
    margin: 2em 0 0.6em 0;
    page-break-before: always;
    page-break-after: avoid;
}
h1.first { page-break-before: avoid; }
h2 {
    font-size: 15pt;
    color: #1e3a8a;
    font-weight: bold;
    margin: 1.6em 0 0.5em 0;
    padding-bottom: 5px;
    border-bottom: 2px solid #dbeafe;
    page-break-after: avoid;
}
h3 {
    font-size: 12.5pt;
    color: #1e40af;
    font-weight: bold;
    margin: 1.2em 0 0.4em 0;
    page-break-after: avoid;
}
h4 {
    font-size: 11pt;
    color: #334155;
    font-weight: bold;
    margin: 1em 0 0.3em 0;
    page-break-after: avoid;
}

/* --- TEXTO --- */
p {
    margin: 0.5em 0;
    text-align: justify;
}
strong { color: #0f172a; font-weight: bold; }
em { color: #475569; font-style: italic; }

/* --- LISTAS --- */
ul, ol {
    margin: 0.5em 0 0.9em 1.3em;
    padding: 0;
}
li { margin: 0.25em 0; line-height: 1.5; }

/* --- LINKS --- */
a { color: #2563eb; text-decoration: none; }

/* --- CÓDIGO --- */
code {
    font-family: 'Courier New', monospace;
    background: #1e293b;
    color: #fbbf24;
    border: 1px solid #334155;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 9pt;
    font-weight: bold;
}
pre, div.codehilite, div.codehilite pre {
    background: #0f172a;
    color: #f1f5f9;
    padding: 12px 14px;
    border-radius: 6px;
    font-family: 'Courier New', monospace;
    font-size: 8.5pt;
    line-height: 1.5;
    page-break-inside: avoid;
    margin: 0.8em 0;
    border-left: 4px solid #38bdf8;
}
div.codehilite { padding: 0; border: none; }
div.codehilite pre { margin: 0; border-left: 4px solid #38bdf8; }
pre code, pre code * , div.codehilite code, div.codehilite span {
    background: transparent !important;
    color: #f1f5f9 !important;
    padding: 0;
    border: none;
    font-size: inherit;
    font-weight: normal;
}

/* --- TABLAS --- */
table {
    border-collapse: collapse;
    width: 100%;
    margin: 0.9em 0;
    font-size: 9pt;
    page-break-inside: avoid;
    border: 1px solid #cbd5e1;
}
thead th {
    background: #1e40af;
    color: white;
    font-weight: bold;
    padding: 8px 10px;
    text-align: left;
    font-size: 9pt;
    border: none;
}
td {
    border: 1px solid #e2e8f0;
    padding: 7px 9px;
    vertical-align: top;
    line-height: 1.45;
}
tbody tr:nth-child(even) td { background: #f8fafc; }
tbody tr:nth-child(odd)  td { background: #ffffff; }
tbody tr td strong { color: #1e40af; }

/* --- CITAS / TIPS --- */
blockquote {
    margin: 1em 0;
    padding: 10px 16px 10px 16px;
    background: #fef3c7;
    border-left: 5px solid #d97706;
    color: #78350f;
    font-style: italic;
    border-radius: 4px;
}

/* --- HR --- */
hr {
    border: none;
    border-top: 2px dashed #cbd5e1;
    margin: 1.5em 0;
    height: 1px;
}

/* --- HEADER / FOOTER --- */
#headerContent {
    font-size: 8pt;
    color: #64748b;
    border-bottom: 1px solid #cbd5e1;
    padding-bottom: 4px;
}
#headerContent .hdr-brand { color: #1e40af; font-weight: bold; }
#headerContent .hdr-title { color: #64748b; }

#footerContent {
    font-size: 8pt;
    color: #94a3b8;
    border-top: 1px solid #e2e8f0;
    padding-top: 4px;
    text-align: center;
}

/* --- CAJAS ESPECIALES (se aplican via clase en el MD) --- */
.box-tip, .box-warning, .box-info, .box-danger {
    margin: 1em 0;
    padding: 12px 16px;
    border-radius: 5px;
    page-break-inside: avoid;
}
.box-tip     { background: #dcfce7; border-left: 5px solid #16a34a; color: #14532d; }
.box-info    { background: #dbeafe; border-left: 5px solid #2563eb; color: #1e3a8a; }
.box-warning { background: #fef3c7; border-left: 5px solid #d97706; color: #78350f; }
.box-danger  { background: #fee2e2; border-left: 5px solid #dc2626; color: #7f1d1d; }

/* --- TOC --- */
.toc-container {
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    padding: 18px 24px;
    margin: 1em 0;
    border-radius: 6px;
    page-break-inside: avoid;
}
.toc-title {
    color: #1e40af;
    font-size: 14pt;
    font-weight: bold;
    margin-bottom: 12px;
    padding-bottom: 6px;
    border-bottom: 2px solid #1e40af;
}
.toc-item {
    padding: 4px 0;
    font-size: 10pt;
    color: #334155;
    border-bottom: 1px dotted #e2e8f0;
}
.toc-item .toc-num {
    display: inline-block;
    width: 25px;
    color: #1e40af;
    font-weight: bold;
}
.toc-item.toc-h3 { padding-left: 24px; color: #64748b; font-size: 9.5pt; }

/* --- URL INDEX --- */
.url-module-card {
    background: white;
    border: 1px solid #e2e8f0;
    border-left: 6px solid #1e40af;
    border-radius: 6px;
    margin: 1em 0;
    padding: 0;
    page-break-inside: avoid;
}
.url-module-header {
    background: #1e40af;
    color: white;
    padding: 10px 16px;
    font-weight: bold;
    font-size: 11pt;
}
.url-module-header-sub {
    font-weight: normal;
    font-size: 8.5pt;
    color: #bfdbfe;
    display: block;
    margin-top: 3px;
}
.url-module-body { padding: 6px 0 0 0; }
.url-module-body table { margin: 0; border: none; }
.url-module-body table td { border-left: none; border-right: none; }
.url-module-body table thead th {
    background: #f1f5f9;
    color: #1e40af;
    font-size: 8.5pt;
    padding: 6px 10px;
    border-bottom: 2px solid #cbd5e1;
}

/* --- DOCUMENT INDEX (portada principal PDF) --- */
.doc-card {
    background: white;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    margin: 0.8em 0;
    padding: 16px 20px;
    page-break-inside: avoid;
}
.doc-card-num {
    background: #1e40af;
    color: white;
    font-weight: bold;
    font-size: 11pt;
    padding: 3px 10px;
    border-radius: 3px;
    display: inline-block;
    margin-right: 10px;
}
.doc-card-title {
    font-size: 13pt;
    font-weight: bold;
    color: #1e40af;
    margin: 0;
    display: inline;
}
.doc-card-subtitle {
    font-size: 10pt;
    color: #64748b;
    margin: 4px 0 8px 0;
}
.doc-card-desc { color: #334155; font-size: 9.5pt; line-height: 1.5; }

</style>
"""

def make_header_footer(doc_titulo: str) -> str:
    return f"""
<div id="headerContent">
    <table style="border:none;margin:0;padding:0;width:100%;">
      <tr>
        <td style="border:none;background:transparent;padding:0;text-align:left;">
          <span class="hdr-brand">FastChat DJ</span> · <span class="hdr-title">{doc_titulo}</span>
        </td>
        <td style="border:none;background:transparent;padding:0;text-align:right;">
          <span class="hdr-title">Abril 2026</span>
        </td>
      </tr>
    </table>
</div>
<div id="footerContent">
    Página <pdf:pagenumber/> de <pdf:pagecount/>  ·  docs/pdf/  ·  FastChat DJ Documentation
</div>
"""


def cover_page_html(doc: dict) -> str:
    """Portada full-bleed con color corporativo."""
    return f"""
<div class="cover-page">
  <div class="cover-bg-accent"></div>
  <div class="cover-bg">
    <div class="cover-brand">Documentación oficial</div>
    <div class="cover-title">{doc['titulo']}</div>
    <div class="cover-subtitle">{doc['subtitulo']}</div>
  </div>
  <div class="cover-section">
    <div class="cover-meta-block">
      <div class="cover-meta-title">De qué trata este documento</div>
      <div class="cover-meta-text">{doc['descripcion']}</div>
    </div>
    <div class="cover-footer">
      <strong>FastChat DJ</strong> · Plataforma WhatsApp CRM con IA<br>
      Documento {doc['orden']} · Generado desde <code>docs/{doc['src']}</code><br>
      Última actualización: abril 2026
    </div>
  </div>
</div>
<pdf:nextpage/>
"""


def toc_html(md_text: str) -> str:
    """Extrae encabezados del MD y arma TOC."""
    items = []
    n = 0
    for line in md_text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('# '):
            continue  # el H1 es el título
        if stripped.startswith('## '):
            n += 1
            t = stripped[3:].replace('`', '')
            items.append(('h2', n, t))
        elif stripped.startswith('### '):
            t = stripped[4:].replace('`', '')
            items.append(('h3', None, t))
    if not items:
        return ''
    rows = []
    for level, num, text in items:
        if level == 'h2':
            rows.append(f'<div class="toc-item"><span class="toc-num">{num}.</span>{text}</div>')
        else:
            rows.append(f'<div class="toc-item toc-h3">&#9679; {text}</div>')
    return f"""
<div class="toc-container">
    <div class="toc-title">Contenido</div>
    {''.join(rows)}
</div>
<pdf:nextpage/>
"""


def markdown_a_html(md_text: str) -> str:
    """MD -> HTML body con convertor estándar."""
    return markdown.markdown(
        md_text,
        extensions=['extra', 'tables', 'fenced_code'],
    )


def build_document_html(doc: dict, md_text: str) -> str:
    body = markdown_a_html(md_text)
    # Remove the first H1 since the cover already shows it
    body = re.sub(r'^<h1[^>]*>.*?</h1>', '', body, count=1, flags=re.DOTALL)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{doc['titulo']}</title>{CSS}</head>
<body>
{make_header_footer(doc['titulo'])}
{cover_page_html(doc)}
{toc_html(md_text)}
{body}
</body></html>"""


# ----------------------------------------------------------------------------
# Índice de URLs (PDF especial)
# ----------------------------------------------------------------------------

def indice_urls_html() -> str:
    cover_doc = {
        'titulo': 'Índice de URLs',
        'subtitulo': 'Mapa completo de todos los módulos y endpoints del sistema',
        'orden':    '00',
        'src':      'generar_pdfs.py (hardcoded)',
        'descripcion': 'Listado estructurado de todas las URLs del sistema, agrupadas por módulo: operación diaria, CRM avanzado, webhooks entrantes, REST API v1, administración y áreas auxiliares. Úsalo como cheat-sheet para encontrar rápido dónde está cada funcionalidad.',
    }

    secciones = []
    total_urls = 0
    for grupo in URLS_POR_MODULO:
        rows = ''.join(
            f'<tr><td style="width:35%"><strong>{nombre}</strong></td>'
            f'<td style="width:30%"><code>{url}</code></td>'
            f'<td style="width:35%">{desc}</td></tr>'
            for nombre, url, desc in grupo['urls']
        )
        total_urls += len(grupo['urls'])
        subtitulo = grupo.get('subtitulo', '')
        subtitulo_html = f'<span class="url-module-header-sub">{subtitulo}</span>' if subtitulo else ''
        secciones.append(f"""
<div class="url-module-card" style="border-left-color:{grupo['color']};">
    <div class="url-module-header" style="background:{grupo['color']};">
        {grupo['modulo']}
        {subtitulo_html}
    </div>
    <div class="url-module-body">
        <table>
            <thead><tr><th>Nombre</th><th>URL</th><th>Descripción</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
</div>""")

    intro = f"""
<h1 class="first">Índice de URLs del sistema</h1>

<div class="box-info">
    <strong>Cómo leer este documento</strong><br>
    Cada bloque corresponde a un módulo del sistema con todas sus URLs relativas al dominio donde
    está desplegado FastChat DJ (ejemplo: <code>https://miempresa.com/whatsapp/sesiones/</code>).<br><br>
    &#9679; Los placeholders <code>&lt;id&gt;</code> se reemplazan por el ID real del recurso.<br>
    &#9679; Los endpoints de la <strong>REST API v1</strong> requieren el header <code>X-API-Key</code>.<br>
    &#9679; Los webhooks entrantes son consumidos por Meta / Node y validan HMAC-SHA256.
</div>

<p><strong>Total de endpoints documentados:</strong> {total_urls}, distribuidos en {len(URLS_POR_MODULO)} módulos.</p>

<h2>Módulos del sistema</h2>
{''.join(secciones)}
"""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Índice de URLs</title>{CSS}</head>
<body>
{make_header_footer('Índice de URLs')}
{cover_page_html(cover_doc)}
{intro}
</body></html>"""


# ----------------------------------------------------------------------------
# Portada general del paquete: overview de los PDFs
# ----------------------------------------------------------------------------

def portada_paquete_html() -> str:
    cover_doc = {
        'titulo': 'FastChat DJ',
        'subtitulo': 'Guía maestra · documentación completa del sistema',
        'orden':    '00',
        'src':      '— (generado automáticamente)',
        'descripcion': 'Documento índice que resume los 5 PDFs que componen la documentación del sistema. Empieza por aquí para saber cuál leer según tu rol.',
    }

    cards = []
    cards.append(f"""
<div class="doc-card" style="border-left: 6px solid {BRAND['muted']};">
    <span class="doc-card-num" style="background:{BRAND['muted']};">00</span>
    <h3 class="doc-card-title">Índice de URLs</h3>
    <div class="doc-card-subtitle">Cheat-sheet con todos los endpoints agrupados por módulo</div>
    <div class="doc-card-desc">
        Mapa visual de todas las URLs: operación diaria, CRM avanzado, webhooks,
        REST API y administración. <strong>Empieza por acá si es tu primer contacto con el sistema.</strong>
    </div>
</div>""")

    for doc in DOCUMENTOS:
        cards.append(f"""
<div class="doc-card" style="border-left: 6px solid {doc['color']};">
    <span class="doc-card-num" style="background:{doc['color']};">{doc['orden']}</span>
    <h3 class="doc-card-title">{doc['titulo']}</h3>
    <div class="doc-card-subtitle">{doc['subtitulo']}</div>
    <div class="doc-card-desc">{doc['descripcion']}</div>
</div>""")

    guia_lectura = """
<h2>Orden sugerido según tu rol</h2>

<div class="box-tip">
    <strong>Si eres dueño / product manager</strong><br>
    1. <strong>03 · Tutorial paso a paso</strong> → lee la parte de tu industria.<br>
    2. <strong>00 · Índice de URLs</strong> → ubicarte en el sistema.<br>
    3. <strong>02 · CRM Features</strong> → sección "Arquitectura" y "Flujo end-to-end".
</div>

<div class="box-info">
    <strong>Si eres desarrollador / implementador</strong><br>
    1. <strong>00 · Índice de URLs</strong> → panorama.<br>
    2. <strong>02 · CRM Features</strong> → referencia técnica.<br>
    3. <strong>01 · Meta Setup</strong> → al conectar WhatsApp oficial.<br>
    4. <strong>03 · Tutorial paso a paso</strong> → entender el uso real.
</div>

<div class="box-warning">
    <strong>Si eres agente / operador diario</strong><br>
    1. <strong>03 · Tutorial paso a paso</strong>, Parte 9 ("Operación diaria").<br>
    2. El caso de uso de tu industria (Parte 8).
</div>
"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>FastChat DJ — Documentación</title>{CSS}</head>
<body>
{make_header_footer('Guía maestra')}
{cover_page_html(cover_doc)}
<h1 class="first">Documentación disponible</h1>
<p>La documentación de FastChat DJ se compone de <strong>5 PDFs temáticos</strong>. Cada uno es independiente y puede leerse en cualquier orden, aunque abajo sugerimos una lectura según tu rol.</p>
{''.join(cards)}
{guia_lectura}
</body></html>"""


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def html_a_pdf(html: str, path: str) -> bool:
    with open(path, 'wb') as f:
        result = pisa.CreatePDF(src=html, dest=f, encoding='utf-8')
    return not result.err


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 0. Portada general del paquete
    path = os.path.join(OUTPUT_DIR, '00_INICIO_lea_primero.pdf')
    print(f'Generando portada general -> {os.path.basename(path)}')
    ok = html_a_pdf(portada_paquete_html(), path)
    print('  OK' if ok else '  ERROR')

    # 1. Índice de URLs
    path = os.path.join(OUTPUT_DIR, '00_indice_urls_modulos.pdf')
    print(f'Generando índice de URLs -> {os.path.basename(path)}')
    ok = html_a_pdf(indice_urls_html(), path)
    print('  OK' if ok else '  ERROR')

    # 2. PDFs por documento MD
    for doc in DOCUMENTOS:
        src_path = os.path.join(DOCS_DIR, doc['src'])
        if not os.path.exists(src_path):
            print(f'SKIP (no existe): {doc["src"]}')
            continue
        with open(src_path, 'r', encoding='utf-8') as f:
            md_text = f.read()
        out_path = os.path.join(OUTPUT_DIR, doc['pdf'])
        print(f'Generando {doc["pdf"]:40s} <- {doc["src"]}')
        html = build_document_html(doc, md_text)
        ok = html_a_pdf(html, out_path)
        print('  OK' if ok else '  ERROR')

    # Limpiar viejos
    legacy = ['meta_setup.pdf', 'crm_features.pdf', 'tutorial_paso_a_paso.pdf',
              'chatbot_tradicional.pdf', 'indice_urls_modulos.pdf']
    for f in legacy:
        p = os.path.join(OUTPUT_DIR, f)
        if os.path.exists(p):
            os.remove(p)

    print()
    print(f'Listo. Salida en: {OUTPUT_DIR}')
    for f in sorted(os.listdir(OUTPUT_DIR)):
        full = os.path.join(OUTPUT_DIR, f)
        if os.path.isfile(full):
            size_kb = os.path.getsize(full) // 1024
            print(f'  {f:45s} {size_kb:5d} KB')


if __name__ == '__main__':
    sys.exit(main() or 0)
