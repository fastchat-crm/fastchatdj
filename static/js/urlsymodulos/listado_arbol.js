const jstreeGrupoUrls = $('#jstree-grupos-urls');
const formArbolUrl = $('#formArbolUrl');

jstreeGrupoUrls.jstree({
    "core": {
        "themes": {
            "responsive": false
        },
        "check_callback": function (operation, node, node_parent, node_position, more) {
            // operation can be 'create_node', 'rename_node', 'delete_node', 'move_node', 'copy_node' or 'edit'
            // in case of 'rename_node' node_position is filled with the new node name
            // console.log(more)
            // return node_parent.parent==='#'
            if (operation === 'move_node') {
                return node_parent.parent === '#' && node.children.length === 0 && !node.data.jstree.is_parent;
            }
            return false;
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
    "plugins": ["wholerow", "noclose", "dnd", "types"]
});

jstreeGrupoUrls.bind("move_node.jstree", function (e, data) {
    if (!$('#btnGuardarArbol').length) {
        formArbolUrl.append('<button id="btnGuardarArbol" type="submit" class="btn btn-icon btn-circle btn-white"><i class="fa fa-save text-success"></i></button>');
    }
    var grupos = $(this).children('ul').children('li').toArray();
    for (var i = 0; i < grupos.length; i++) {
        var padre = jstreeGrupoUrls.jstree(true).get_node($(grupos[i]).attr('id'));
        var grupo_pk = padre.state.grupo_pk;
        if (padre.children.length > 0 && padre.state.is_parent) {
            var hijos = padre.children;
            for (var j = 0; j < hijos.length; j++) {
                var hijo = jstreeGrupoUrls.jstree(true).get_node(hijos[j]);
                var hijoState = JSON.parse($(`#${hijos[j]}`).attr("data-jstree"));
                hijoState.pk_destino = grupo_pk;
                hijoState.orden = j;
                $(`#${hijos[j]}`).attr("data-jstree", JSON.stringify(hijoState));
                var datosMod = JSON.parse($(`#${hijo.state.input_id}`).val());
                datosMod.orden = j;
                datosMod.pk_destino = grupo_pk;
                $(`#${hijo.state.input_id}`).val(JSON.stringify(datosMod));
            }
        }
    }
    // var children = data.node.children;
    // var parent = this.get_node(data.parent);
    // if (children.length === 0) {
    //     var inp = jstreeModulosUrls.jstree(true).get_node(data.parent).children;
    //     for (var i = 0; i < inp.length; i++) {
    //         var mod = jstreeModulosUrls.jstree(true).get_node(inp[i]);
    //         var datosMod = JSON.parse($(`#${mod.state.input_id}`).val());
    //         datosMod.orden = i;
    //         $(`#${mod.state.input_id}`).val(JSON.stringify(datosMod));
    //     }
    // }
});