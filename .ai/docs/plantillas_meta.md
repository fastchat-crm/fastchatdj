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
  `_procesar_cambio_plantilla`, guarda `reason`) — la suscripción del WABA debe
  incluir ese campo. Fallback manual: acción `sincronizar` (botón global por
  sesión y dentro del modal Ver cuando está PENDING o REJECTED).
- **Ejemplos obligatorios:** al someter, `_construir_payload_plantilla`
  (`meta/whatsapp.py`) incluye `example.body_text` (desde `variables_json`
  ejemplos, fallback "Ejemplo N") y `example.header_text` si hay `{{N}}` —
  sin ejemplos el revisor de Meta no puede evaluar y rechaza (fix 2026-07-14).
- **Categorización (doc Meta 2026-05):** los recordatorios de
  inscripción/carrito/renovación son **MARKETING** ("nueva segmentación") aunque
  el usuario los haya pedido; UTILITY exige tono transaccional sin persuasión
  ("¡No te quedes fuera!", "¡Te esperamos!" lo descalifican). Desde abr-2025
  Meta re-categoriza UTILITY→MARKETING automáticamente y rechaza con
  `INCORRECT_CATEGORY`. URLs variables `{{N}}` en el cuerpo son otra causa
  frecuente de rechazo — preferir botón URL con sufijo dinámico.
- **Motivo de rechazo:** Graph API NO devuelve `rejected_reason` por defecto —
  `sincronizar_plantillas` (`meta/whatsapp.py:805`) lo pide explícito vía
  `fields=...,rejected_reason,quality_score` (fix 2026-07-13; antes el motivo
  llegaba siempre vacío). Valor `NONE` de Meta se normaliza a vacío.
- Solo plantillas `APPROVED` se listan para envío desde el chat.
