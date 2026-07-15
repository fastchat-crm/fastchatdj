import json

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.chat_history import BaseChatMessageHistory
from ..models import MessageStore

PREFIJO_RESUMEN_RODANTE = "RESUMEN_RODANTE:"


class DjangoChatMessageHistory(BaseChatMessageHistory):
    def __init__(self, session_id: str):
        self.session_id = session_id
        self._cache: list[BaseMessage] | None = None  # invalidado al escribir

    # ------------------------------------------------------------------
    # LangChain interface
    # ------------------------------------------------------------------

    @property
    def messages(self) -> list[BaseMessage]:
        """Carga todos los mensajes (resultado cacheado en el ciclo de vida del objeto)."""
        if self._cache is None:
            self._cache = self._load_all()
        return self._cache

    def add_user_message(self, content: str) -> None:
        MessageStore.objects.create(session_id=self.session_id, role="human", content=content)
        self._cache = None  # invalidar cache

    def add_ai_message(self, content: str) -> None:
        MessageStore.objects.create(session_id=self.session_id, role="ai", content=content)
        self._cache = None

    def add_message(self, message: BaseMessage) -> None:
        role = "human" if isinstance(message, HumanMessage) else "ai"
        MessageStore.objects.create(session_id=self.session_id, role=role, content=message.content)
        self._cache = None

    def clear(self) -> None:
        MessageStore.objects.filter(session_id=self.session_id).delete()
        self._cache = None

    # ------------------------------------------------------------------
    # Helpers eficientes
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Cuenta mensajes con COUNT(*) — sin cargar registros."""
        return MessageStore.objects.filter(session_id=self.session_id).count()

    def _qs_conversacion(self):
        """Solo los turnos reales de la conversación: sin filas internas
        (system/resumen) ni LISTA_GUARDADA."""
        return (
            MessageStore.objects
            .filter(session_id=self.session_id)
            .exclude(role="system")
            .exclude(content__startswith="LISTA_GUARDADA:")
        )

    def count_conversacion(self) -> int:
        """Cuenta solo los turnos reales (excluye filas internas)."""
        return self._qs_conversacion().count()

    def get_range(self, desde: int, hasta: int) -> list[BaseMessage]:
        """Turnos reales [desde:hasta] en orden cronológico (para resumir los
        que rotaron fuera de la ventana reciente)."""
        qs = self._qs_conversacion().order_by('created_at')[desde:hasta]
        result = []
        for entry in qs:
            if entry.role == "human":
                result.append(HumanMessage(content=entry.content))
            elif entry.role == "ai":
                result.append(AIMessage(content=entry.content))
        return result

    def get_resumen_rodante(self) -> dict | None:
        """Devuelve {'texto': str, 'hasta': int} del resumen rodante, o None."""
        row = (
            MessageStore.objects
            .filter(session_id=self.session_id, role="system",
                    content__startswith=PREFIJO_RESUMEN_RODANTE)
            .order_by('-created_at')
            .first()
        )
        if not row:
            return None
        try:
            return json.loads(row.content[len(PREFIJO_RESUMEN_RODANTE):])
        except Exception:
            return None

    def set_resumen_rodante(self, texto: str, hasta: int) -> None:
        """Guarda/actualiza el resumen rodante como fila system interna."""
        payload = PREFIJO_RESUMEN_RODANTE + json.dumps(
            {'texto': texto, 'hasta': int(hasta)}, ensure_ascii=False
        )
        row = (
            MessageStore.objects
            .filter(session_id=self.session_id, role="system",
                    content__startswith=PREFIJO_RESUMEN_RODANTE)
            .order_by('-created_at')
            .first()
        )
        if row:
            row.content = payload
            row.save(update_fields=['content'])
        else:
            MessageStore.objects.create(
                session_id=self.session_id, role="system", content=payload
            )
        self._cache = None

    def get_recent(self, n: int) -> list[BaseMessage]:
        """Devuelve los últimos n mensajes en orden cronológico.

        Usa LIMIT en la query en vez de cargar todo el historial.
        Filtra automáticamente las filas internas (system y LISTA_GUARDADA)
        para que no consuman lugares de la ventana.
        """
        qs = (
            self._qs_conversacion()
            .order_by('-created_at')[:n]
        )
        result = []
        for entry in reversed(list(qs)):
            if entry.role == "human":
                result.append(HumanMessage(content=entry.content))
            elif entry.role == "ai":
                result.append(AIMessage(content=entry.content))
        return result

    def update_last_ai_message(self, new_content: str) -> None:
        """Actualiza el contenido del último mensaje AI (para correcciones en consultar_con_listas)."""
        last = (
            MessageStore.objects
            .filter(session_id=self.session_id, role="ai")
            .exclude(content__startswith="LISTA_GUARDADA:")
            .order_by('-created_at')
            .first()
        )
        if last:
            last.content = new_content
            last.save(update_fields=['content'])
        else:
            self.add_ai_message(new_content)
        self._cache = None

    def get_recent_lista_guardada(self, n: int = 20) -> list[BaseMessage]:
        """Devuelve los últimos n mensajes AI que sean LISTA_GUARDADA."""
        qs = (
            MessageStore.objects
            .filter(session_id=self.session_id, role="ai", content__startswith="LISTA_GUARDADA:")
            .order_by('-created_at')[:n]
        )
        return [AIMessage(content=e.content) for e in qs]

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------

    def _load_all(self) -> list[BaseMessage]:
        result = []
        for entry in MessageStore.objects.filter(session_id=self.session_id).order_by("created_at"):
            if entry.role == "human":
                result.append(HumanMessage(content=entry.content))
            elif entry.role == "ai":
                result.append(AIMessage(content=entry.content))
            elif entry.role == "system":
                result.append(SystemMessage(content=entry.content))
        return result
