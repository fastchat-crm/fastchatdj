"""Reglas de comentarios Instagram — wrapper de la vista genérica."""
from django.contrib.auth.decorators import login_required

from core.funciones import secure_module
from whatsapp.view_reglas_comentarios import reglasComentariosView


@login_required
@secure_module
def reglasComentariosInstagramView(request):
    return reglasComentariosView(request, canal='instagram')
