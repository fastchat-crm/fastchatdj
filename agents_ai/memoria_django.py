from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.chat_history import BaseChatMessageHistory
from .models import MessageStore


class DjangoChatMessageHistory(BaseChatMessageHistory):
    def __init__(self, session_id: str):
        self.session_id = session_id

    @property
    def messages(self) -> list[BaseMessage]:
        qs = MessageStore.objects.filter(session_id=self.session_id).order_by("created_at")
        messages = []
        for entry in qs:
            if entry.role == "human":
                messages.append(HumanMessage(content=entry.content))
            elif entry.role == "ai":
                messages.append(AIMessage(content=entry.content))
        return messages

    def add_message(self, message: BaseMessage) -> None:
        role = "human" if isinstance(message, HumanMessage) else "ai"
        MessageStore.objects.create(
            session_id=self.session_id,
            role=role,
            content=message.content
        )

    def clear(self) -> None:
        MessageStore.objects.filter(session_id=self.session_id).delete()