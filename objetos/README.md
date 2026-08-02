# App `objetos/` — modelo de datos extensible en runtime

> Fase 1.1 del plan en `.ai/docs/estudio_gohighlevel.md`. Resuelve la brecha de
> la que dependen 6 de las 12 identificadas contra GoHighLevel: hasta ahora cada
> cliente de un rubro nuevo (inmobiliaria, clínica, concesionaria) obligaba a
> agregar modelos a `models.py`, migrar y desplegar. Acá el usuario define sus
> entidades desde la UI y el sistema las interpreta.

## Por qué JSONB y no EAV

Un EAV (`Entidad` + `Atributo` + `Valor`) obliga a un JOIN por cada campo que se
consulta. Con PostgreSQL 15 —que ya corremos— un `JSONB` con índice GIN filtra y
ordena bien, y deja una sola tabla de registros.

El costo es que **la integridad la valida la aplicación, no la base**. Toda
escritura tiene que pasar por `ObjetoPersonalizado.validar_datos()`; si alguien
escribe directo en `datos` se saltea los tipos y los obligatorios.

## Modelos (`models.py`)

| Modelo | Rol |
|---|---|
| `ObjetoPersonalizado` | La entidad: "Propiedad", "Póliza". Tiene `slug` único que define la URL |
| `CampoPersonalizado` | Un campo y su tipo. `nombre` es la clave dentro del JSONB |
| `RegistroPersonalizado` | Una fila. Los valores viven en `datos` (JSONB + índice GIN) |
| `AsociacionRegistro` | Relaciona dos registros cualesquiera, sin definir ForeignKeys |

Los 12 tipos de campo están en `TIPO_CAMPO_CHOICES`. Cada uno se normaliza en
`CampoPersonalizado.limpiar()`, que devuelve `(valor, error)`.

**Cómo se guarda cada tipo en el JSONB** (importa, porque no es obvio):

- `decimal` → **string**, no float. Un float en JSON pierde precisión y estos
  campos suelen ser importes.
- `fecha` / `fecha_hora` → ISO 8601.
- `seleccion_multiple` → lista; los demás, escalares.
- `booleano` → bool real.

## Vistas

| Archivo | URL | Rol |
|---|---|---|
| `view_objetos.py` | `/objetos/` | Diseñador: CRUD de objetos y campos |
| `view_registros.py` | `/objetos/<slug>/` | CRUD genérico de registros — **una sola vista para todas las entidades** |

`registrosView` lee la metadata y arma listado, formulario y detalle en runtime.
Agregar un objeto nuevo no requiere código ni URL nueva.

## Trampas conocidas

- **La clave interna de un campo no se puede cambiar al editar.** Cambiarla
  dejaría huérfanos todos los valores ya guardados bajo la clave vieja en el
  JSONB de cada registro. `_guardar_campo` la ignora deliberadamente en modo
  edición; solo se setea al crear, desde `normalizar_clave(etiqueta)`.

- **El formulario declara qué campos trae, en el hidden `__campos`.** Sin ese
  marcador no se puede distinguir "el usuario vació el campo" de "el formulario
  no incluía el campo", y una edición parcial borraba en silencio todo lo que no
  venía en el POST. Con el marcador, `_leer_datos_del_post` solo lee lo
  declarado y `validar_datos(parcial=True)` no exige obligatorios ausentes.
  Si el marcador no llega se asume formulario completo.

- **El borrado es soft en los tres niveles.** Borrar un campo no toca los valores
  ya guardados: si se restaura, vuelven a aparecer.

- **Un campo agregado después no rompe los registros viejos**: sale vacío en el
  detalle y el merge del `change` conserva lo que ya había.

## Pendiente

- Filtros por campo en el listado (hoy solo hay búsqueda de texto sobre el JSONB
  completo, que no usa el índice GIN — lo usa el filtro por objeto).
- Selector de registros en la UI para crear asociaciones: el backend
  (`asociar` / `desasociar`) ya está, falta el front.
- Exponer los objetos custom como herramientas del agente IA, para que el bot
  pueda consultarlos y cargarlos.
