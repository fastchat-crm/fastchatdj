from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from autenticacion.models import Usuario, PerfilPersona, PerfilAdministrativo
from core.adminbase import BaseModelAdmin


class PerfilAdministrativoAdmin(BaseModelAdmin):
    model = PerfilAdministrativo


class PerfilPersonaAdmin(BaseModelAdmin):
    model = PerfilPersona


admin.site.register(Usuario, UserAdmin)
admin.site.register(PerfilPersona, PerfilPersonaAdmin)
admin.site.register(PerfilAdministrativo, PerfilAdministrativoAdmin)