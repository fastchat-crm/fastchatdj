"""Centro CRM e IA — guía instructiva de los módulos de CRM e inteligencia artificial."""
from django.contrib.auth.decorators import login_required

from core.funciones import secure_module
from whatsapp.view_centro import _render_centro


@login_required
@secure_module
def centroCrmView(request):
    return _render_centro(request, 'crm')
