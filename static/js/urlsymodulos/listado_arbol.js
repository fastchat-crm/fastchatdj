const jstreeGrupoUrls = $('#jstree-grupos-urls');
const formArbolUrl = $('#formArbolUrl');

function readJstreeData(elId) {
    var raw = $('#' + elId).attr('data-jstree');
    if (!raw) return {};
    try {
        return JSON.parse(raw);
    } catch (e) {
        return {};
    }
}

function writeJstreeData(elId, obj) {
    $('#' + elId).attr('data-jstree', JSON.stringify(obj));
}

jstreeGrupoUrls.jstree({
    "core": {
        "themes": {
            "responsive": false
        },
        "check_callback": function (operation, node, node_parent, node_position, more) {
            if (operation === 'move_node' || operation === 'copy_node') {
                if (!node || !node_parent) return false;
                if (node.parent === '#') return false;
                if (!node_parent.parent || node_parent.parent !== '#') return false;
                return true;
            }
            return true;
        },
    },
    "types": {
        "default": {
            "icon": "fa fa-folder text-warning fa-lg"
        },
        "file": {
            "icon": "fa fa-file text-inverse fa-lg"
        }
    },
    "dnd": {
        "copy": false,
        "is_draggable": function (nodes) {
            for (var i = 0; i < nodes.length; i++) {
                if (!nodes[i].parent || nodes[i].parent === '#') return false;
            }
            return true;
        }
    },
    "plugins": ["wholerow", "dnd", "types"]
});

jstreeGrupoUrls.bind("move_node.jstree", function (e, data) {
    if (!$('#btnGuardarArbol').length) {
        formArbolUrl.append('<button id="btnGuardarArbol" type="submit" class="btn btn-icon btn-circle btn-white"><i class="fa fa-save text-success"></i></button>');
    }
    var grupos = $(this).children('ul').children('li').toArray();
    for (var i = 0; i < grupos.length; i++) {
        var grupoEl = grupos[i];
        var grupoId = $(grupoEl).attr('id');
        var padreData = readJstreeData(grupoId);
        var grupo_pk = padreData.grupo_pk;
        if (!grupo_pk) continue;
        var padre = jstreeGrupoUrls.jstree(true).get_node(grupoId);
        if (padre.children.length === 0 || !padreData.is_parent) continue;
        var hijos = padre.children;
        for (var j = 0; j < hijos.length; j++) {
            var hijoId = hijos[j];
            var hijoState = readJstreeData(hijoId);
            hijoState.pk_destino = grupo_pk;
            hijoState.orden = j;
            writeJstreeData(hijoId, hijoState);
            var inputId = hijoState.input_id;
            if (!inputId) continue;
            var $inp = $('#' + inputId);
            if (!$inp.length) continue;
            var datosMod;
            try {
                datosMod = JSON.parse($inp.val());
            } catch (e) {
                continue;
            }
            datosMod.orden = j;
            datosMod.pk_destino = grupo_pk;
            $inp.val(JSON.stringify(datosMod));
        }
    }
});
