/* ============================================================
   JsonPretty — formateo + syntax highlight ligero para mostrar
   JSON crudo en modales de auditoría (webhook hits, trazas,
   diagnóstico de sesión).
   ============================================================
   API:
     JsonPretty.tryParse(text)  → objeto/array si parsea, null si no
     JsonPretty.indent(text, n) → string indentado o el texto original
     JsonPretty.highlight(text) → string HTML con spans coloreadas
     JsonPretty.format(text)    → HTML listo para inyectar:
                                    <pre class="json-pretty">…</pre>
                                  para JSON, o <pre class="json-raw">…</pre>
                                  para texto plano (también escapa HTML).
   El helper detecta automáticamente JSON envuelto en texto (ej. detalle
   de traza estilo "key=valor | key=valor") y deja eso como texto plano.
   ============================================================ */
(function () {
    'use strict';

    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function tryParse(text) {
        if (text == null) return null;
        var trimmed = String(text).trim();
        if (!trimmed) return null;
        if (trimmed[0] !== '{' && trimmed[0] !== '[') return null;
        try {
            return JSON.parse(trimmed);
        } catch (e) {
            return null;
        }
    }

    function indent(text, n) {
        var parsed = tryParse(text);
        if (parsed === null) return String(text == null ? '' : text);
        try {
            return JSON.stringify(parsed, null, n || 2);
        } catch (e) {
            return String(text);
        }
    }

    // Syntax highlight simple — sin librería externa.
    // Toma string YA indentado y devuelve HTML con clases:
    //   .json-key, .json-str, .json-num, .json-bool, .json-null, .json-punct
    function highlight(jsonStr) {
        var html = escapeHtml(jsonStr);
        // Strings (incluyendo claves "...":)
        html = html.replace(
            /("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*")(\s*:)?/g,
            function (match, str, colon) {
                if (colon) {
                    return '<span class="json-key">' + str + '</span>'
                         + '<span class="json-punct">' + colon + '</span>';
                }
                return '<span class="json-str">' + str + '</span>';
            }
        );
        // Booleans
        html = html.replace(/\b(true|false)\b/g, '<span class="json-bool">$1</span>');
        // Null
        html = html.replace(/\bnull\b/g, '<span class="json-null">null</span>');
        // Numbers (no dentro de strings — ya están envueltos en spans, así que
        // matcheamos solo los que NO estén precedidos por > de </span>)
        html = html.replace(
            /(^|[\s,\[\:])(-?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?)/g,
            '$1<span class="json-num">$2</span>'
        );
        return html;
    }

    function format(text) {
        if (text == null || text === '') {
            return '<pre class="json-raw json-empty">(vacío)</pre>';
        }
        var parsed = tryParse(text);
        if (parsed !== null) {
            try {
                var pretty = JSON.stringify(parsed, null, 2);
                return '<pre class="json-pretty">' + highlight(pretty) + '</pre>';
            } catch (e) { /* fallthrough */ }
        }
        return '<pre class="json-raw">' + escapeHtml(text) + '</pre>';
    }

    window.JsonPretty = {
        tryParse: tryParse,
        indent:   indent,
        highlight: highlight,
        format:   format,
        escapeHtml: escapeHtml,
    };
})();
