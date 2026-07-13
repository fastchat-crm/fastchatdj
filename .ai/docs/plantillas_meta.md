# Módulo Plantillas WhatsApp (Meta) — `/whatsapp/plantillas/`

Vista: `whatsapp/view_plantillas.py` (`plantillasView`). Template:
`whatsapp/templates/whatsapp/plantillas/listado.html` + `form.html` +
`_modal_ver.html`. Modelo: `PlantillaWhatsApp` (`whatsapp/models.py:1701`).

## Acciones

| Action | Método | Qué hace |
|---|---|---|
| `add` / `change` | GET (form) + POST | CRUD de borradores. Editar solo en `BORRADOR`/`REJECTED` |
| `ver` | GET | Modal de solo lectura (`_modal_ver.html`): contenido + metadatos Meta (id_meta, estado, motivo_rechazo, fecha_aprobacion, ultima_sincronizacion, uso) + link "Abrir en Meta Business" (`business.facebook.com/wa/manage/message-templates/?waba_id=...`) + botón "Sincronizar estado ahora" si está PENDING |
| `someter_a_meta` | POST | Envía a aprobación. Valida ANTES que el cuerpo no empiece/termine con `{{N}}` (error Meta 2388299) con mensaje claro |
| `sincronizar` | POST | Pull de estados desde Meta (`MetaWhatsAppService.sincronizar_plantillas`) |
| `generar_con_ia` / `preview_plantillas_ia` / `confirmar_plantillas_ia` | POST | Generador IA (uno / lote con preview). Lógica en `agents_ai/ai_actions/plantillas_wa.py` |
| `editar_con_ia` | POST | Reescribe una plantilla `BORRADOR`/`REJECTED` según instrucción libre (`plantillas_wa.editar_uno`). No toca nombre/idioma. Trazabilidad: `ConsumoTokenIA` (origen `plantilla`) + log de auditoría con la instrucción |
| `delete` | POST | Elimina (si estaba APPROVED intenta borrarla también en Meta) |

## Reglas duras

- **Variables en extremos:** Meta rechaza cuerpos que empiezan o terminan con
  `{{N}}` (error 2388299). Defensa en 4 capas: prompts IA lo prohíben,
  `ajustar_variables_extremos()` corrige en `generar_uno`/`editar_uno`/
  `_sanitizar_plantilla`, **`PlantillaWhatsApp.save()` lo aplica siempre**
  (cubre alta/edición manual), y `someter_a_meta` valida con mensaje claro.
- **Estado de aprobación:** se actualiza solo vía webhook
  `message_template_status_update` (`meta_webhook_view.py:329` →
  `_procesar_cambio_plantilla`) — la suscripción del WABA debe incluir ese
  campo. Fallback manual: acción `sincronizar` (botón global por sesión y
  dentro del modal Ver cuando está PENDING).
- Solo plantillas `APPROVED` se listan para envío desde el chat.
