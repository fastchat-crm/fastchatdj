# fastchatdj

Plataforma Django: **CRM con chatbot IA multi-agente + WhatsApp + cotizador médico**.
El chatbot es multi-proveedor (Gemini, OpenAI, Claude, Ollama Cloud) con RAG
(Weaviate multi-tenant + FAISS) y memoria de conversación.

Servidor de producción: `http://2.24.107.52/` (Nginx → Daphne ASGI).

## Stack

- **Backend:** Python 3.11, Django 4.2, Django REST framework
- **ASGI / tiempo real:** Daphne + Channels + Redis
- **Base de datos:** PostgreSQL
- **IA:** LangChain, proveedores Gemini / OpenAI / Claude / **Ollama Cloud**
- **RAG:** Weaviate (multi-tenant, embeddings Gemini) + FAISS local
- **Servidor web:** Nginx (proxy) → `daphne` vía socket unix (`systemd: fastchatdj.service`)

## Puesta en marcha / despliegue

```bash
git pull origin reformula

# entorno (venv del servidor)
/home/venv/bin/pip install -r requirements.txt

# ⚠️ MIGRACIONES: ver sección de abajo (NO vienen en git)
/home/venv/bin/python manage.py makemigrations
/home/venv/bin/python manage.py migrate

# estáticos si aplica
/home/venv/bin/python manage.py collectstatic --noinput

# reiniciar el servicio ASGI
sudo systemctl restart fastchatdj.service
sudo systemctl status fastchatdj.service --no-pager
```

Variables de entorno del servicio: `/etc/fastchatdj.env`.
Config de Nginx: `/etc/nginx/sites-available/fastchatdj`.

## ⚠️ Migraciones (IMPORTANTE)

**Las migraciones NO se versionan.** El `.gitignore` incluye `**/migrations/**`
(solo se conserva `__init__.py`). Por lo tanto **el código de los modelos SÍ va en
git, pero los archivos de migración NO**.

Consecuencia: después de cada `git pull` que traiga cambios en algún `models.py`,
**hay que regenerar y aplicar las migraciones en cada entorno**:

```bash
/home/venv/bin/python manage.py makemigrations
/home/venv/bin/python manage.py migrate
```

Si se omite este paso, la app fallará al leer/escribir columnas nuevas
(p. ej. `ConsumoTokenIA.prompt_full`).

## Configuración que vive en la base de datos (no en git)

Estos ajustes se guardan en PostgreSQL y **no se replican por git**; se configuran
por entorno desde el panel de *Entrenamiento IA* o el admin:

- **Agentes IA** (`AgentesIA`): prompt, API key, RAG, y overrides de consumo
  (`cfg_faiss_k`, `cfg_max_context_chars`, `cfg_max_output_tokens`, `cfg_history_turns`).
- **API Keys** (`ApiKeyIA`) y sus **alertas de consumo** (`AlertaConsumoIA`,
  umbral diario/mensual + destinatarios).
- Base de conocimiento del RAG (Weaviate por tenant `agente_<id>`).

## Observabilidad de consumo IA

- **Traza en vivo:** `/cotizador/traza/` — por cada request: prompt ejecutado,
  respuesta, tokens (entrada/salida), modelo, y **costo USD**. Modal "ver todo"
  con el prompt completo ensamblado. Totales día/mes por modelo y origen.
- **Documentación técnica:** `/cotizador/documentacion/`.
- **Cálculo de costo:** `crm/costos_ia.py` (tabla de precios USD/millón por modelo,
  editable). Nota de facturación: **Ollama Cloud (ollama.com) es suscripción fija**
  (no cobra por token → costo marginal $0); Gemini/OpenAI/Claude cobran por token.
- **Registro:** cada llamada al LLM crea un `ConsumoTokenIA` (tokens, modelo,
  origen, prompt/respuesta completos) y dispara alertas si supera los umbrales.

## Servicios

| Servicio | Rol |
|---|---|
| Nginx | Proxy :80 → Daphne; sirve `/static/` y `/media/` |
| `fastchatdj.service` (systemd) | Daphne ASGI (HTTP + WebSockets) vía socket unix |
| PostgreSQL | Base de datos principal |
| Redis | Channel layer de Channels (chat en vivo) |
| Weaviate | Base vectorial del RAG (127.0.0.1) |
| `cron_jobs/` | Campañas, recordatorios, reconexión de sesiones |
