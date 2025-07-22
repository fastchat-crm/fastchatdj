from django.db import models


class MessageStore(models.Model):
    session_id = models.CharField(max_length=255, db_index=True)
    role = models.CharField(max_length=20)  # "human" o "ai"
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'message_store'
        ordering = ['created_at']