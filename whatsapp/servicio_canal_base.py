"""Contrato común de los servicios de canal (WhatsApp Baileys, Meta Cloud,
Instagram, Messenger, TikTok).

`get_whatsapp_service(sesion)` puede devolver cualquiera de ellos y el pipeline
compartido (procesar_mensaje, inbox de conversaciones, cron de campañas) invoca
estos métodos sin saber el transporte. Todo servicio de canal DEBE heredar de
`ServicioCanalBase`: los métodos obligatorios se sobreescriben; los opcionales
tienen aquí un default seguro (no-op o error claro) para que un canal que no
soporta la capacidad degrade con mensaje en vez de romper con AttributeError.

Convención de retorno: dict con al menos `success: bool` y, si falla, `error: str`
en español (visible para el asesor).
"""

_NO_SOPORTADO = 'Función no soportada en este canal.'


def partir_texto_por_limite(texto: str, limite: int) -> list[str]:
    """Divide un texto en partes <= limite respetando párrafos y espacios.

    Los canales tienen techos de caracteres por mensaje (Instagram/Messenger:
    1000; WhatsApp Cloud: 4096). Un envío que exceda el techo es rechazado por
    la API y el cliente no recibe NADA — mejor entregar en varias partes.
    """
    texto = (texto or '').strip()
    if len(texto) <= limite:
        return [texto] if texto else []
    partes = []
    resto = texto
    while len(resto) > limite:
        corte = resto.rfind('\n\n', 0, limite)
        if corte < int(limite * 0.4):
            corte = resto.rfind('\n', 0, limite)
        if corte < int(limite * 0.4):
            corte = resto.rfind(' ', 0, limite)
        if corte < int(limite * 0.4):
            corte = limite
        partes.append(resto[:corte].strip())
        resto = resto[corte:].strip()
    if resto:
        partes.append(resto)
    return [p for p in partes if p]


class ServicioCanalBase:
    # ------------------------------------------------------------------
    # Obligatorios — todo canal debe sobreescribirlos
    # ------------------------------------------------------------------

    def send_text_message(self, session_id, to, text, conversacion_id=None, simularEscritura=False):
        raise NotImplementedError('El servicio de canal debe implementar send_text_message.')

    # ------------------------------------------------------------------
    # Envío de media — sobreescribir si el canal lo soporta.
    # La firma con kwargs es el contrato: los callers SIEMPRE pasan
    # caption/file_content/filename/media_type/conversacion_id por keyword.
    # ------------------------------------------------------------------

    def send_media_message(self, session_id, to, file_path=None, file_content=None,
                           caption=None, filename=None, media_url=None,
                           media_type='image', conversacion_id=None, **kwargs):
        return {'success': False, 'error': 'Envío de archivos no soportado en este canal.'}

    # ------------------------------------------------------------------
    # Presencia ("escribiendo...") — no-op seguro por defecto
    # ------------------------------------------------------------------

    def send_presence_update(self, session_id, to, presence='composing'):
        return {'success': True}

    def quit_presence_update(self, session_id, to):
        return {'success': True}

    # ------------------------------------------------------------------
    # Capacidades opcionales — default: degradar con mensaje claro
    # ------------------------------------------------------------------

    def edit_message(self, session_id, to, message_id, new_text):
        return {'success': False, 'error': 'Editar mensajes no está soportado en este canal.'}

    def delete_message(self, session_id, to, message_id):
        return {'success': False, 'error': 'Eliminar mensajes no está soportado en este canal.'}

    def send_template(self, session_id, to, plantilla_nombre, idioma='es',
                      parametros_cuerpo=None, parametros_header=None, conversacion_id=None):
        return {'success': False, 'error': 'Plantillas solo disponibles en WhatsApp Cloud API (Meta).'}

    def transcribe_audio(self, message, model_size='base', lang='es'):
        return None

    def sync_transcribe_audio(self, message, model_size='base', lang='es'):
        return None

    def get_user_image(self, session_id, to):
        return None

    def sync_contacts(self, session):
        return {'success': False, 'error': _NO_SOPORTADO}

    def create_session(self, session, webhook_url):
        return {'success': False, 'error': _NO_SOPORTADO}

    def check_session_status(self, session_id):
        return {'success': True, 'estado': 'desconocido'}

    def close_session(self, session_id):
        return {'success': True}

    def format_phone_number(self, numero):
        return str(numero or '')
