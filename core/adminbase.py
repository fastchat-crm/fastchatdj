# -*- coding: utf-8 -*-
# from django.utils.translation import ugettext_lazy as _
from django.contrib import admin


class BaseModelTabularAdmin(admin.TabularInline):
    exclude = ("usuario_creacion", "fecha_registro", "usuario_modificacion", "fecha_modificacion",)


class BaseModelAdmin(admin.ModelAdmin):

    def get_actions(self, request):
        actions = super(BaseModelAdmin, self).get_actions(request)
        # if request.user.username not in [x[0] for x in MY_MANAGERS]:
        #     # del actions['delete_selected']
        return actions

    def has_add_permission(self, request):
        # return request.user.username in [x[0] for x in MY_MANAGERS]
        return True

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        # return request.user.username in [x[0] for x in MY_MANAGERS]
        return True

    def get_form(self, request, obj=None, **kwargs):
        self.exclude = ("fecha_registro", "usuario_creacion", "fecha_modificacion", "usuario_modificacion",)
        form = super(BaseModelAdmin, self).get_form(request, obj, **kwargs)
        return form

    def save_model(self, request, obj, form, change):
        obj.save()

