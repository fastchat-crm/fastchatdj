/* =============================================================
   Módulo Conexiones — lógica del tablero + modal + kebab menu.
   Usa jQuery + SweetAlert del base.html cuando está disponible
   (funciones globales: eliminarajax, Swal, pantallaespera).
   ============================================================= */
(function () {
  'use strict';

  // ---------- CSRF ----------
  function getCookie(name) {
    var m = document.cookie.match(new RegExp('(?:^|;\\s*)' + name + '=([^;]+)'));
    return m ? decodeURIComponent(m[1]) : '';
  }
  function csrfToken() {
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return (input && input.value) || getCookie('csrftoken');
  }

  function postAccion(data) {
    var body = new URLSearchParams();
    body.append('csrfmiddlewaretoken', csrfToken());
    Object.keys(data).forEach(function (k) { body.append(k, data[k]); });
    return fetch(window.CONEX_URL, {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken(),
        'X-Requested-With': 'XMLHttpRequest',
      },
      credentials: 'same-origin',
      body: body,
    }).then(function (r) { return r.json(); });
  }

  function fetchPartial(accion, pk) {
    var url = window.CONEX_URL + '?action=' + accion + '&pk=' + encodeURIComponent(pk);
    return fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
    }).then(function (r) { return r.json(); });
  }

  // ---------- Toast helper ----------
  function mostrarToast(msg, tipo) {
    if (window.Swal && Swal.fire) {
      var icon = tipo === 'ok' ? 'success' : tipo === 'err' ? 'error' : 'info';
      Swal.fire({ icon: icon, title: msg, timer: 2400, showConfirmButton: false, toast: true, position: 'top-end' });
      return;
    }
    var t = document.createElement('div');
    t.textContent = msg;
    t.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:2000;padding:.75rem 1.1rem;'
      + 'border-radius:10px;font-size:.9rem;box-shadow:0 6px 20px rgba(0,0,0,.15);max-width:420px;'
      + (tipo === 'ok' ? 'background:#d4f5e3;color:#15803d'
         : tipo === 'err' ? 'background:#fee2e2;color:#b91c1c'
         : 'background:#e0f2fe;color:#0369a1');
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 2800);
  }

  // ---------- Modal principal (Agregar conexión) ----------
  var modal = document.getElementById('conex-modal');
  function abrirModal(canalInicial) {
    if (!modal) return;
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    cambiarPanel(canalInicial || 'whatsapp');
  }
  function cerrarModal() {
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
  }
  var btnAbrir = document.getElementById('btn-abrir-modal');
  if (btnAbrir) btnAbrir.addEventListener('click', function () { abrirModal(); });
  var btnCerrar = document.getElementById('btn-cerrar-modal');
  if (btnCerrar) btnCerrar.addEventListener('click', cerrarModal);
  document.querySelectorAll('[data-cerrar]').forEach(function (b) {
    b.addEventListener('click', cerrarModal);
  });
  if (modal) modal.addEventListener('click', function (e) {
    if (e.target === modal) cerrarModal();
  });

  function cambiarPanel(canal) {
    document.querySelectorAll('.conex-canal').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-canal') === canal);
    });
    document.querySelectorAll('.pane').forEach(function (p) {
      p.classList.toggle('pane-hidden', p.getAttribute('data-pane') !== canal);
    });
  }
  document.querySelectorAll('.conex-canal').forEach(function (b) {
    b.addEventListener('click', function () { cambiarPanel(b.getAttribute('data-canal')); });
  });

  // ---------- Checkbox WhatsApp / botón Continuar (modo OAuth) ----------
  var chkWa = document.getElementById('chk-wa-requisitos');
  var btnCont = document.getElementById('btn-wa-continuar');
  var formManual = document.getElementById('form-wa-manual');
  var btnValManual = document.getElementById('btn-wa-validar-manual');
  var btnSaveManual = document.getElementById('btn-wa-guardar-manual');

  function setManualEnabled(enabled) {
    if (btnValManual) btnValManual.disabled = !enabled;
    if (btnSaveManual) btnSaveManual.disabled = !enabled;
    if (formManual) {
      formManual.querySelectorAll('input').forEach(function (i) { i.disabled = !enabled; });
    }
  }

  if (chkWa) {
    if (btnCont) {
      var continuarYaHabilitado = !btnCont.hasAttribute('disabled');
      if (!continuarYaHabilitado) {
        btnCont.disabled = true; chkWa.disabled = true;
      } else {
        btnCont.disabled = true;
      }
    }
    if (formManual) setManualEnabled(false);
    chkWa.addEventListener('change', function () {
      if (btnCont && !btnCont.hasAttribute('data-locked-out')) btnCont.disabled = !chkWa.checked;
      if (formManual) setManualEnabled(chkWa.checked);
    });
  }
  if (btnCont) {
    btnCont.addEventListener('click', function () {
      if (btnCont.disabled) return;
      var w = 600, h = 720;
      var left = (window.screen.width / 2) - (w / 2);
      var top  = (window.screen.height / 2) - (h / 2);
      var popup = window.open(window.META_OAUTH_START_URL, 'meta_oauth',
        'width=' + w + ',height=' + h + ',left=' + left + ',top=' + top);
      if (!popup) mostrarToast('Tu navegador bloqueó el popup. Permite ventanas emergentes.', 'err');
    });
  }

  // ---------- Panel guía colapsable (modo manual) ----------
  var manHelpToggle = document.getElementById('man-help-toggle');
  var manHelpPanel  = document.getElementById('man-help-panel');
  if (manHelpToggle && manHelpPanel) {
    manHelpToggle.addEventListener('click', function () {
      var open = manHelpPanel.hasAttribute('hidden') === false;
      if (open) {
        manHelpPanel.setAttribute('hidden', '');
        manHelpToggle.setAttribute('aria-expanded', 'false');
      } else {
        manHelpPanel.removeAttribute('hidden');
        manHelpToggle.setAttribute('aria-expanded', 'true');
      }
    });
  }
  // Links "¿de dónde?" → abre panel y resalta el paso correspondiente
  document.querySelectorAll('.man-help-link').forEach(function (link) {
    link.addEventListener('click', function (ev) {
      ev.preventDefault();
      if (!manHelpPanel || !manHelpToggle) return;
      if (manHelpPanel.hasAttribute('hidden')) {
        manHelpPanel.removeAttribute('hidden');
        manHelpToggle.setAttribute('aria-expanded', 'true');
      }
      var target = link.getAttribute('data-help-jump');
      var item = manHelpPanel.querySelector('li[data-target="' + target + '"]');
      if (!item) return;
      manHelpPanel.querySelectorAll('li.is-highlight').forEach(function (el) { el.classList.remove('is-highlight'); });
      item.classList.add('is-highlight');
      item.scrollIntoView({behavior: 'smooth', block: 'nearest'});
      setTimeout(function () { item.classList.remove('is-highlight'); }, 2200);
    });
  });

  // ---------- Toggle ojo password (modo manual) ----------
  var manTokenEye = document.getElementById('man-token-eye');
  var manTokenInp = document.getElementById('man-token');
  if (manTokenEye && manTokenInp) {
    manTokenEye.addEventListener('click', function () {
      var isPwd = manTokenInp.type === 'password';
      manTokenInp.type = isPwd ? 'text' : 'password';
      var icon = manTokenEye.querySelector('i');
      if (icon) icon.className = isPwd ? 'fa fa-eye-slash' : 'fa fa-eye';
    });
  }

  // ---------- Modo manual: validar + conectar ----------
  function fmGetCsrf() {
    var i = formManual && formManual.querySelector('input[name=csrfmiddlewaretoken]');
    return i ? i.value : '';
  }
  function fmGetData() {
    var d = new FormData(formManual);
    return d;
  }
  function fmShowResult(html, type) {
    var box = document.getElementById('man-resultado');
    if (!box) return;
    box.classList.remove('d-none', 'alert-success', 'alert-danger', 'alert-info', 'alert-warning');
    box.classList.add('alert-' + type);
    box.innerHTML = html;
  }
  function fmPost(url, formData, onDone) {
    var xhr = new XMLHttpRequest();
    xhr.open('POST', url, true);
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    xhr.setRequestHeader('X-CSRFToken', fmGetCsrf());
    xhr.onload = function () {
      var data = {};
      try { data = JSON.parse(xhr.responseText) || {}; } catch (e) {}
      onDone(data, xhr.status);
    };
    xhr.onerror = function () { onDone({ok: false, error: 'Error de red.'}, 0); };
    xhr.send(formData);
  }
  if (btnValManual && formManual) {
    btnValManual.addEventListener('click', function () {
      if (btnValManual.disabled) return;
      var orig = btnValManual.innerHTML;
      btnValManual.disabled = true;
      btnValManual.innerHTML = '<i class="fa fa-spinner fa-spin me-1"></i> Validando con Meta...';
      fmPost(window.META_MANUAL_VALIDAR_URL || '/whatsapp/meta/manual/validar/', fmGetData(), function (data) {
        btnValManual.disabled = false;
        btnValManual.innerHTML = orig;
        if (!data.ok) {
          fmShowResult('<i class="fa fa-circle-xmark me-2"></i>' + (data.error || 'Meta rechazó las credenciales.'), 'danger');
          return;
        }
        var lineas = [];
        if (data.waba_name) lineas.push('<b>WABA:</b> ' + data.waba_name);
        if (data.display_phone_number) {
          lineas.push('<b>Número:</b> <code>' + data.display_phone_number + '</code>');
          var disp = document.getElementById('man-display');
          if (disp && !disp.value) disp.value = data.display_phone_number;
        }
        if (data.verified_name) lineas.push('<b>Nombre verificado:</b> ' + data.verified_name);
        if (data.quality_rating) lineas.push('<b>Calidad:</b> <code>' + data.quality_rating + '</code>');
        fmShowResult('<i class="fa fa-circle-check me-2"></i>Meta validó las credenciales:<br>' + lineas.join('<br>'), 'success');
      });
    });
  }
  if (formManual) {
    formManual.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (btnSaveManual && btnSaveManual.disabled) return;
      var orig = btnSaveManual ? btnSaveManual.innerHTML : '';
      if (btnSaveManual) {
        btnSaveManual.disabled = true;
        btnSaveManual.innerHTML = '<i class="fa fa-spinner fa-spin me-1"></i> Conectando...';
      }
      fmPost(window.META_MANUAL_CONECTAR_URL || '/whatsapp/meta/manual/conectar/', fmGetData(), function (data) {
        if (btnSaveManual) {
          btnSaveManual.disabled = false;
          btnSaveManual.innerHTML = orig;
        }
        if (!data.ok) {
          fmShowResult('<i class="fa fa-circle-xmark me-2"></i>' + (data.error || 'No se pudo conectar la sesión.'), 'danger');
          return;
        }
        fmShowResult('<i class="fa fa-circle-check me-2"></i>Sesión <b>' + (data.nombre || '') + '</b> conectada. Recargando...', 'success');
        cerrarModal();
        mostrarToast('WhatsApp conectado manualmente: ' + (data.display_phone_number || data.nombre || ''), 'ok');
        setTimeout(function () { window.location.reload(); }, 900);
      });
    });
  }

  // ---------- postMessage del popup OAuth ----------
  window.addEventListener('message', function (ev) {
    var data = ev.data || {};
    if (data.source !== 'meta_oauth') return;
    var p = data.payload || {};
    if (p.ok) {
      cerrarModal();
      mostrarToast('WhatsApp enlazado: ' + (p.numero || p.nombre || ''), 'ok');
      setTimeout(function () { window.location.reload(); }, 900);
    } else {
      mostrarToast(p.error || 'Meta no permitió completar la conexión.', 'err');
    }
  });

  // ---------- Modal secundario (detail) ----------
  var detailBackdrop = document.getElementById('conex-detail-modal');
  var detailContent  = document.getElementById('conex-detail-content');

  function abrirDetail(html) {
    if (!detailBackdrop) return;
    detailContent.innerHTML = html;
    detailBackdrop.classList.add('open');
    detailBackdrop.setAttribute('aria-hidden', 'false');
  }
  function cerrarDetail() {
    if (!detailBackdrop) return;
    detailBackdrop.classList.remove('open');
    detailBackdrop.setAttribute('aria-hidden', 'true');
    detailContent.innerHTML = '';
  }
  if (detailBackdrop) detailBackdrop.addEventListener('click', function (e) {
    if (e.target === detailBackdrop) cerrarDetail();
  });

  // Click en cualquier [data-cerrar-detail] dentro del modal secundario
  document.addEventListener('click', function (e) {
    if (e.target.closest('[data-cerrar-detail]')) cerrarDetail();
  });

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    if (detailBackdrop && detailBackdrop.classList.contains('open')) return cerrarDetail();
    if (modal && modal.classList.contains('open')) return cerrarModal();
  });

  // ---------- Kebab menu ----------
  document.addEventListener('click', function (e) {
    var toggle = e.target.closest('[data-kebab-toggle]');
    if (toggle) {
      var menu = toggle.parentElement.querySelector('[data-kebab-menu]');
      // Cerrar todos los demás
      document.querySelectorAll('[data-kebab-menu]').forEach(function (m) {
        if (m !== menu) m.classList.remove('open');
      });
      if (menu) menu.classList.toggle('open');
      e.stopPropagation();
      return;
    }
    // Click fuera: cerrar todos
    if (!e.target.closest('[data-kebab-menu]')) {
      document.querySelectorAll('[data-kebab-menu]').forEach(function (m) { m.classList.remove('open'); });
    }
  });

  // ---------- Baileys QR ----------
  var baileysSesionId = null;
  var baileysPoll = null;
  var btnBaileysStart = document.getElementById('btn-baileys-start');
  if (btnBaileysStart) {
    btnBaileysStart.addEventListener('click', function () {
      btnBaileysStart.disabled = true;
      btnBaileysStart.innerHTML = '<i class="fa fa-spinner fa-spin me-1"></i> Generando...';
      var data = { action: 'baileys_start' };
      if (baileysSesionId) data.session_id = baileysSesionId;
      postAccion(data).then(function (res) {
        btnBaileysStart.disabled = false;
        btnBaileysStart.innerHTML = '<i class="fa fa-rotate me-1"></i> Regenerar código';
        if (res.error) return mostrarToast(res.message || 'Error generando QR', 'err');
        baileysSesionId = res.sesion_id;
        mostrarQR(res.qr);
        iniciarPollBaileys();
      }).catch(function (ex) {
        btnBaileysStart.disabled = false;
        btnBaileysStart.innerHTML = '<i class="fa fa-qrcode me-1"></i> Generar código QR';
        mostrarToast('Error de red: ' + ex, 'err');
      });
    });
  }
  function mostrarQR(qr) {
    var img = document.getElementById('qr-img');
    var ph = document.getElementById('qr-placeholder');
    var ok = document.getElementById('qr-success');
    if (ph) ph.style.display = 'none';
    if (ok) ok.style.display = 'none';
    if (img) { img.style.display = qr ? 'block' : 'none'; img.src = qr || ''; }
  }
  function mostrarConectado(num) {
    var img = document.getElementById('qr-img');
    var ph = document.getElementById('qr-placeholder');
    var ok = document.getElementById('qr-success');
    var n  = document.getElementById('qr-success-num');
    if (ph) ph.style.display = 'none';
    if (img) img.style.display = 'none';
    if (ok) ok.style.display = 'block';
    if (n) n.textContent = num ? '+' + num : '';
  }
  function iniciarPollBaileys() {
    if (baileysPoll) clearInterval(baileysPoll);
    baileysPoll = setInterval(function () {
      if (!baileysSesionId) { clearInterval(baileysPoll); return; }
      postAccion({ action: 'baileys_status', sesion_id: baileysSesionId }).then(function (res) {
        if (res.error) return;
        if (res.estado === 'conectado') {
          clearInterval(baileysPoll); baileysPoll = null;
          mostrarConectado(res.numero);
          setTimeout(function () { window.location.reload(); }, 1500);
        } else if (res.qr) {
          var img = document.getElementById('qr-img');
          if (img && img.src !== res.qr) mostrarQR(res.qr);
        }
      });
    }, 3000);
  }

  // ---------- Búsqueda live ----------
  var searchInput = document.getElementById('conex-search-input');
  if (searchInput) {
    var debounce = null;
    searchInput.addEventListener('input', function () {
      clearTimeout(debounce);
      debounce = setTimeout(function () {
        var q = encodeURIComponent(searchInput.value.trim());
        window.location.href = window.CONEX_URL + (q ? ('?criterio=' + q) : '');
      }, 400);
    });
  }

  // ---------- Filtros chip ----------
  document.querySelectorAll('.conex-chip').forEach(function (chip) {
    chip.addEventListener('click', function () {
      document.querySelectorAll('.conex-chip').forEach(function (c) { c.classList.remove('active'); });
      chip.classList.add('active');
      var f = chip.getAttribute('data-filtro');
      document.querySelectorAll('.conex-card').forEach(function (card) {
        var est = card.getAttribute('data-estado');
        card.style.display = (f === 'todas' || est === f) ? '' : 'none';
      });
    });
  });

  // ---------- Acciones del kebab y botones rápidos ----------
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-action]');
    if (!btn) return;
    var card = btn.closest('.conex-card');
    if (!card) return;
    var sesionId = card.getAttribute('data-sesion-id');
    var nombre   = card.getAttribute('data-sesion-nombre') || '';
    var action   = btn.getAttribute('data-action');

    // Cerrar kebab abierto
    document.querySelectorAll('[data-kebab-menu]').forEach(function (m) { m.classList.remove('open'); });

    if (action === 'editar') {
      fetchPartial('editar_modal', sesionId).then(function (r) {
        if (!r.ok) return mostrarToast(r.message || 'No se pudo abrir el editor.', 'err');
        abrirDetail(r.html);
      });
    } else if (action === 'historial') {
      fetchPartial('historial_modal', sesionId).then(function (r) {
        if (!r.ok) return mostrarToast(r.message || 'No se pudo cargar el historial.', 'err');
        abrirDetail(r.html);
      });
    } else if (action === 'resumen') {
      fetchPartial('resumen_modal', sesionId).then(function (r) {
        if (!r.ok) return mostrarToast(r.message || 'No se pudo cargar el resumen.', 'err');
        abrirDetail(r.html);
      });
    } else if (action === 'plantilla-prueba') {
      fetchPartial('plantilla_modal', sesionId).then(function (r) {
        if (!r.ok) return mostrarToast(r.message || 'No se pudo abrir la plantilla.', 'err');
        abrirDetail(r.html);
      });
    } else if (action === 'meta-validar') {
      postAccion({ action: 'meta_validar', id: sesionId }).then(function (r) {
        if (r.error) return mostrarToast(r.message, 'err');
        mostrarToast(r.message || 'Número revalidado con Meta.', 'ok');
        setTimeout(function () { window.location.reload(); }, 900);
      });
    } else if (action === 'baileys-verificar') {
      postAccion({ action: 'baileys_verificar', id: sesionId }).then(function (r) {
        if (r.error) return mostrarToast(r.message || 'No respondió.', 'err');
        mostrarToast(r.message, r.connected ? 'ok' : 'err');
        setTimeout(function () { window.location.reload(); }, 900);
      });
    } else if (action === 'baileys-reconnect') {
      baileysSesionId = sesionId;
      abrirModal('baileys');
      if (btnBaileysStart) btnBaileysStart.click();
    } else if (action === 'disconnect') {
      if (window.Swal) {
        Swal.fire({
          title: '¿Desconectar ' + nombre + '?',
          text: 'La sesión dejará de recibir y enviar mensajes hasta que la reconectes.',
          icon: 'warning', showCancelButton: true, allowOutsideClick: false,
          confirmButtonText: 'Sí, desconectar', cancelButtonText: 'Cancelar',
          confirmButtonColor: '#d97706',
        }).then(function (res) {
          if (!res.value) return;
          postAccion({ action: 'disconnect', id: sesionId }).then(function (r) {
            if (r.error) return mostrarToast(r.message, 'err');
            mostrarToast('Sesión desconectada.', 'ok');
            setTimeout(function () { window.location.reload(); }, 600);
          });
        });
      }
    } else if (action === 'eliminar') {
      // Usa la función global del base.html — Swal + POST + reload.
      if (typeof window.eliminarajax === 'function') {
        window.eliminarajax(sesionId, nombre, 'delete');
      } else {
        mostrarToast('No se encontró el helper eliminarajax en base.html.', 'err');
      }
    }
  });

  // ---------- Submit form "Modificar" (en detail modal) ----------
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (form.id === 'form-editar-sesion') {
      e.preventDefault();
      var fd = new FormData(form);
      var obj = {};
      fd.forEach(function (v, k) { obj[k] = v; });
      postAccion(obj).then(function (r) {
        if (r.error) return mostrarToast(r.message, 'err');
        mostrarToast(r.message || 'Guardado.', 'ok');
        cerrarDetail();
        if (r.reload) setTimeout(function () { window.location.reload(); }, 600);
      });
    } else if (form.id === 'form-plantilla-prueba') {
      e.preventDefault();
      var fd2 = new FormData(form);
      var obj2 = {};
      fd2.forEach(function (v, k) { obj2[k] = v; });
      postAccion(obj2).then(function (r) {
        if (r.error) return mostrarToast(r.message, 'err');
        mostrarToast(r.message || 'Plantilla enviada.', 'ok');
        cerrarDetail();
      });
    }
  });

})();
