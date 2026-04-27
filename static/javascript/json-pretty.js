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

    // Best-effort indent — para JSON truncado (body_preview de 600 chars)
    // o con errores, recorre char a char insertando saltos/indent a partir
    // de la estructura visible. Respeta strings (no rompe dentro de "...").
    function bestEffortIndent(text) {
        var out = '';
        var depth = 0;
        var inStr = false;
        var esc = false;
        var pad = function (n) {
            var s = '';
            for (var i = 0; i < n; i++) s += '  ';
            return s;
        };
        for (var i = 0; i < text.length; i++) {
            var c = text.charAt(i);
            if (inStr) {
                out += c;
                if (esc) { esc = false; continue; }
                if (c === '\\') { esc = true; continue; }
                if (c === '"')  { inStr = false; }
                continue;
            }
            if (c === '"') { inStr = true; out += c; continue; }
            if (c === '{' || c === '[') {
                depth++;
                out += c + '\n' + pad(depth);
                continue;
            }
            if (c === '}' || c === ']') {
                depth = Math.max(0, depth - 1);
                out += '\n' + pad(depth) + c;
                continue;
            }
            if (c === ',') { out += c + '\n' + pad(depth); continue; }
            if (c === ':') { out += c + ' '; continue; }
            if (c === ' ' || c === '\n' || c === '\t' || c === '\r') continue;
            out += c;
        }
        return out;
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
        // Fallback: si arranca con { o [ asumimos JSON truncado/inválido y
        // hacemos indent best-effort con highlight. Si no, texto plano.
        var trimmed = String(text).trim();
        if (trimmed && (trimmed[0] === '{' || trimmed[0] === '[')) {
            var indented = bestEffortIndent(trimmed);
            return '<pre class="json-pretty json-pretty-partial" '
                 + 'title="JSON truncado o inválido — formato best-effort">'
                 + highlight(indented) + '</pre>';
        }
        return '<pre class="json-raw">' + escapeHtml(text) + '</pre>';
    }

    window.JsonPretty = {
        tryParse: tryParse,
        indent:   indent,
        bestEffortIndent: bestEffortIndent,
        highlight: highlight,
        format:   format,
        escapeHtml: escapeHtml,
    };
})();
