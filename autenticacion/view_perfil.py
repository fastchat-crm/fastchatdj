import sys

from django.contrib.auth import authenticate
from django.contrib.sessions.models import Session
from django.db.models import When, Value, BooleanField, Case
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.shortcuts import render, redirect
from django.utils import timezone

from area_geografica.models import Ciudad, Provincia
from core.constantes import TIMEZONE_CHOICES
from core.funciones import addData, salva_auditoria, secure_module, log, remover_caracteres_especiales_unicode, \
    generar_nombre
from seguridad.models import AudiUsuarioTabla, SessionUser
from .forms import EditPersonaForm
from .models import Usuario
from django.contrib.admin.models import LogEntry


@login_required
@secure_module
def perfilView(request):
    ruta = request.path
    data = {
        'titulo': "Perfil",
        "descripcion": "Gestionar Perfil de Usuario",
        'modulo': 'Perfil',
        'ruta': ruta,
        'auditoria': LogEntry.objects.filter(user__id=request.user.pk).order_by('-id')[:10],
    }
    addData(request, data)

    if request.method == 'POST':
        if 'action' in request.POST:
            res_json = []
            action = request.POST['action']
            try:
                with transaction.atomic():
                    if action == 'probar_push':
                        try:
                            from pwa.notificaciones import enviar_push_usuario
                            titulo = (request.POST.get('titulo') or '🔔 Notificación de prueba').strip()[:120]
                            cuerpo = (request.POST.get('cuerpo') or '✅ Esta es una notificación de prueba para tu cuenta.').strip()[:300]
                            ok = enviar_push_usuario(
                                request.user,
                                head=titulo,
                                body=cuerpo,
                                url='/perfilpanel/',
                                tag='perfil-prueba',
                                extra={'tipo': 'perfil.prueba'},
                            )
                            return JsonResponse([{
                                'error': not ok,
                                'message': 'Push de prueba enviado a tus dispositivos.' if ok else 'No tienes dispositivos suscriptos o el envío falló.',
                            }], safe=False)
                        except Exception as ex:
                            return JsonResponse([{'error': True, 'message': str(ex)}], safe=False)
                    if action == 'delete_push_subscription':
                        try:
                            from webpush.models import PushInformation
                            pid = int(request.POST.get('id') or 0)
                            pi = PushInformation.objects.filter(pk=pid, user=request.user).first()
                            if not pi:
                                return JsonResponse([{'error': True, 'message': 'Push subscription not found.'}], safe=False)
                            sub = pi.subscription
                            pi.delete()
                            try:
                                if sub and not sub.webpush_info.exists():
                                    sub.delete()
                            except Exception:
                                pass
                            log(f'Push subscription {pid} removed by user', request, 'del')
                            return JsonResponse([{'error': False, 'message': 'Push subscription removed.', 'reload': True}], safe=False)
                        except Exception as ex:
                            return JsonResponse([{'error': True, 'message': str(ex)}], safe=False)
                    if action == 'delete_all_push_subscriptions':
                        try:
                            from webpush.models import PushInformation
                            qs = PushInformation.objects.filter(user=request.user).select_related('subscription')
                            subs = {}
                            total = 0
                            for pi in qs:
                                if pi.subscription_id and pi.subscription_id not in subs:
                                    subs[pi.subscription_id] = pi.subscription
                                pi.delete()
                                total += 1
                            for sub in subs.values():
                                try:
                                    if sub and not sub.webpush_info.exists():
                                        sub.delete()
                                except Exception:
                                    pass
                            log(f'All push subscriptions removed by user ({total})', request, 'del')
                            if total:
                                mensaje = f'Se eliminaron {total} conexión(es) push.'
                            else:
                                mensaje = 'No hay conexiones push para eliminar.'
                            return JsonResponse([{'error': False, 'message': mensaje, 'reload': True}], safe=False)
                        except Exception as ex:
                            return JsonResponse([{'error': True, 'message': str(ex)}], safe=False)
                    if action == 'delete_session_user':
                        try:
                            sid = int(request.POST.get('id') or 0)
                            su = SessionUser.objects.filter(pk=sid, user=request.user).first()
                            if not su:
                                return JsonResponse([{'error': True, 'message': 'Session not found.'}], safe=False)
                            is_current = (su.session.session_key == request.session.session_key) if su.session_id else False
                            session_key = su.session.session_key if su.session_id else None
                            try:
                                if su.session_id:
                                    Session.objects.filter(session_key=session_key).delete()
                            except Exception:
                                pass
                            try:
                                su.delete()
                            except Exception:
                                pass
                            log(f'SessionUser {sid} removed by user', request, 'del')
                            return JsonResponse([{
                                'error': False,
                                'message': 'Session ended.',
                                'reload': not is_current,
                                'logout': is_current,
                            }], safe=False)
                        except Exception as ex:
                            return JsonResponse([{'error': True, 'message': str(ex)}], safe=False)
                    if action == 'changeperfil':
                        usuario = Usuario.objects.get(pk=int(request.user.pk))
                        usuario.first_name = request.POST['first_name']
                        usuario.last_name = request.POST['last_name']
                        usuario.telefono = request.POST['telefono']
                        usuario.ciudad_id =  request.POST['ciudad']
                        fecha_nacimiento_ = request.POST["fecha_nacimiento"]
                        usuario.fecha_nacimiento = fecha_nacimiento_
                        usuario.direccion = request.POST["direccion"]
                        usuario.save()
                        messages.success(request, 'Información de perfil actualizada')
                        res_json.append({'error': False, 'reload': True})
                    if action == 'changepass':
                        usuario = Usuario.objects.get(pk=int(request.user.pk))
                        user_login = authenticate(username=usuario.username, password=request.POST['clave_actual'])
                        if user_login is not None:
                            if request.POST['clave_actual'] != request.POST['clave']:
                                user_login.set_password(request.POST['clave'])
                                user_login.save()
                                messages.success(request, 'Contraseña cambiada satisfactoriamente.')
                                res_json.append({'error': False, 'reload': True})
                            else:
                                res_json.append({"error": True, "message": 'La contraseña nueva debe ser diferente a la contraseña actual'})
                        else:
                            res_json.append({"error": True, "message": 'Contraseña actual incorrecta'})
                    if action == 'updatephoto':
                        usuario = Usuario.objects.get(pk=int(request.user.pk))
                        if 'foto' in request.FILES:
                            file = request.FILES['foto']
                            nombredocumento = remover_caracteres_especiales_unicode(f"{usuario.username}_{file._name}")
                            file._name = generar_nombre(nombredocumento, file._name)
                            usuario.foto = file
                            usuario.save()
                            messages.success(request, 'Foto de perfil actualizada exitosamente')
                            res_json.append({'error': False, 'reload': True})
                        else:
                            res_json.append({"error": True, "message": 'No se ha seleccionado ninguna imagen'})
            except Exception as ex:
                res_json.append({"error": True, "message": f"{ex}"})
            return JsonResponse(res_json, safe=False)
    try:
        push_subs = []
        try:
            from webpush.models import PushInformation
            qs_push = (
                PushInformation.objects
                .filter(user=request.user)
                .select_related('subscription')
                .order_by('-id')
            )
            for p in qs_push:
                sub = p.subscription
                endpoint = (sub.endpoint or '') if sub else ''
                host = ''
                if endpoint:
                    try:
                        from urllib.parse import urlparse
                        host = urlparse(endpoint).netloc
                    except Exception:
                        host = endpoint[:40]
                push_subs.append({
                    'id': p.id,
                    'browser': (sub.browser if sub else '') or 'Unknown',
                    'host': host,
                    'endpoint_preview': (endpoint[:60] + '…') if len(endpoint) > 60 else endpoint,
                })
        except Exception:
            pass
        data['push_subscriptions'] = push_subs

        active_sessions = []
        current_key = request.session.session_key or ''
        ahora_aware = timezone.now()
        try:
            qs_su = (
                SessionUser.objects
                .filter(user=request.user)
                .select_related('session')
                .order_by('-fecha_conexion')
            )
            for s in qs_su:
                try:
                    sess = s.session
                except Exception:
                    sess = None
                expira = getattr(sess, 'expire_date', None)
                vigente = False
                if expira:
                    try:
                        if timezone.is_aware(expira):
                            vigente = expira > ahora_aware
                        else:
                            from datetime import datetime as _dt_naive
                            vigente = expira > _dt_naive.now()
                    except Exception:
                        vigente = False
                sess_key = getattr(sess, 'session_key', '') if sess else ''
                active_sessions.append({
                    'id': s.id,
                    'dispositivo': (s.dispositivo or '—')[:80],
                    'ip': s.ip or '—',
                    'areageografica': s.areageografica or '—',
                    'fecha_conexion': s.fecha_conexion,
                    'expira': expira,
                    'vigente': vigente,
                    'is_current': bool(sess_key and current_key and sess_key == current_key),
                })
        except Exception:
            import logging as _lg
            _lg.getLogger(__name__).exception('Error cargando sesiones activas del perfil')
        data['active_sessions'] = active_sessions

        formPersona = EditPersonaForm(instance=request.user)
        if request.user.ciudad:
            if request.user.ciudad.provincia:
                formPersona.fields['ciudad'].queryset = Ciudad.objects.filter(provincia=request.user.ciudad.provincia).order_by('nombre')
                formPersona.fields['provincia'].queryset = Provincia.objects.filter(pais=request.user.ciudad.provincia.pais).order_by('nombre')
                formPersona.fields['ciudad'].initial = request.user.ciudad.pk
                formPersona.fields['provincia'].initial = request.user.ciudad.provincia.pk
                formPersona.fields['pais'].initial = request.user.ciudad.provincia.pais.pk
        else:
            formPersona.fields['ciudad'].queryset = Ciudad.objects.none()
            formPersona.fields['provincia'].queryset = Provincia.objects.none()
        data['formPersona'] = formPersona
        return render(request, 'autenticacion/perfil.html', data)
    except Exception as ex:
        msg_error_linea = f"{ex} - Code ({ex.__class__.__name__}) - Line {sys.exc_info()[-1].tb_lineno}"
        return JsonResponse({"error": True, "message": msg_error_linea})
