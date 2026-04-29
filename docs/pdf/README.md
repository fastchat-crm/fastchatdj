# Documentación PDF

Esta carpeta contiene la documentación del sistema en formato PDF, generada automáticamente desde los archivos `.md` en `docs/`.

## Archivos disponibles

| PDF | Páginas aprox. | Audiencia | Descripción |
|---|---|---|---|
| **`indice_urls_modulos.pdf`** | 4 | Admins / devs | Cheat-sheet con todas las URLs del sistema agrupadas por módulo. Empieza por acá si es tu primer contacto. |
| **`meta_setup.pdf`** | 6 | Técnico | Configuración paso a paso de Meta Cloud API (WhatsApp Business oficial). |
| **`crm_features.pdf`** | 20 | Técnico + PM | Referencia técnica completa: arquitectura, modelos, servicios, API REST, flujo end-to-end CTWA→CAPI. |
| **`tutorial_paso_a_paso.pdf`** | 25 | Usuario final + equipo | Tutorial práctico de uso diario con 7 casos de negocio concretos (e-commerce, restaurante, inmobiliaria, clínica, instituto, agencia, B2B). |
| **`chatbot_tradicional.pdf`** | varía | Configurador | Cómo armar flujos de chatbot sin IA (menús, palabras clave). |

## Orden sugerido de lectura

**Si eres dueño del negocio / PM:**
1. `tutorial_paso_a_paso.pdf` · lee la parte correspondiente a tu industria (Parte 8).
2. `indice_urls_modulos.pdf` · para saber dónde está cada cosa.
3. `crm_features.pdf` · la sección "Arquitectura general" y "Flujo end-to-end".

**Si eres desarrollador / implementador:**
1. `indice_urls_modulos.pdf` · panorama rápido.
2. `crm_features.pdf` · referencia técnica.
3. `meta_setup.pdf` · al momento de conectar WhatsApp oficial.
4. `tutorial_paso_a_paso.pdf` · para entender cómo se usa en la práctica.

**Si eres agente / operador diario:**
1. `tutorial_paso_a_paso.pdf` · Parte 9 ("Operación diaria").
2. El caso de uso de tu industria (Parte 8).

## Regenerar los PDFs

Cada vez que edites un `.md`, corre:

```bash
python docs/generar_pdfs.py
```

Requiere `markdown` y `xhtml2pdf`, ya incluidos en `requirements.txt`.

## Fuente

Todos los PDFs se generan desde los MD en `docs/`. La fuente siempre es la verdad — si encuentras algo mal en un PDF, edita el `.md` y vuelve a correr el script.
