from django.contrib import admin
from django.utils.safestring import mark_safe

from core.adminbase import BaseModelTabularAdmin, BaseModelAdmin
from seguridad.models import ErrorLog, Configuracion, AudiUsuarioTabla, Modulo, GroupModulo, ModuloGrupo


class ErrorLogAdmin(BaseModelAdmin):
    list_per_page = 15
    search_fields = ('usuario__username', 'usuario__documento',
                     'usuario__first_name', 'usuario__last_name')
    list_display = ('descripcion', 'archivo', 'accion', 'metodo', 'usuario', 'corregido', 'fecha')
    list_filter = ('corregido', 'accion', 'metodo', 'fecha')


    def edit_tag(self, obj):
        return mark_safe(
            f'<a href="{obj.get_absolute_url()}?edit=True">Editar</a>'
        )

    edit_tag.short_description = 'Editar'


class ModuloAdmin(BaseModelAdmin):
    model = Modulo


class ModuloGrupoAdmin(BaseModelAdmin):
    model = ModuloGrupo


class GroupModuloAdmin(BaseModelAdmin):
    model = GroupModulo


class ConfiguracionAdmin(BaseModelAdmin):
    model = Configuracion

admin.site.register(ErrorLog, ErrorLogAdmin)
admin.site.register(Configuracion, ConfiguracionAdmin)
admin.site.register(Modulo, ModuloAdmin)
admin.site.register(GroupModulo, GroupModuloAdmin)
admin.site.register(ModuloGrupo, ModuloGrupoAdmin)
