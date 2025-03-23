const jstreeModulosUrls = $('#jstree-modulos-urls');
const jstreeListadoModulosUrls = $('#jstree-listado-modulos-urls');
(function ($, undefined) {
    "use strict";
    $.jstree.plugins.noclose = function () {
        this.close_node = $.noop;
    };
})(jQuery);

$(function () {
    jstreeListadoModulosUrls.jstree({
        "core": {
            "themes": {
                "responsive": false
            }
        },
        "types": {
            "default": {
                "icon": "fa fa-folder text-warning fa-lg"
            },
            "file": {
                "icon": "fa fa-file text-inverse fa-lg"
            }
        },
        "plugins": ["wholerow", "types"]
    });


    jstreeModulosUrls.jstree({
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
                    if (this.get_node(node).parent === this.get_node(node_parent).id && node.children.length === 0) {
                        //node_position
                        return true;
                    } else {
                        return false;
                    }
                }
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
        "plugins": ["wholerow", "checkbox", "noclose", "dnd", "types"]
    });
    jstreeModulosUrls.bind("move_node.jstree", function (e, data) {
        var children = data.node.children;
        if (children.length === 0) {
            var inp = jstreeModulosUrls.jstree(true).get_node(data.parent).children;
            for (var i = 0; i < inp.length; i++) {
                var mod = jstreeModulosUrls.jstree(true).get_node(inp[i]);
                var datosMod = JSON.parse($(`#${mod.state.input_id}`).val());
                datosMod.orden = i;
                $(`#${mod.state.input_id}`).val(JSON.stringify(datosMod));
            }
        }
    });
    jstreeModulosUrls.bind("changed.jstree", function (e, ppp) {
        try{
            var children = ppp.node.children;
            if (children.length > 0) {
                for (var i = 0; i < children.length; i++) {
                    var sel = `#${children[i]}`;
                    if ($(sel).data('jstree').url) {
                        var datos = $(sel).data('jstree');
                        if (ppp.action === 'select_node') {
                            $(`#${datos.input_id}`).prop("checked", true);
                        } else if (ppp.action === 'deselect_node') {
                            $(`#${datos.input_id}`).prop("checked", false);
                        }
                    }
                }
            } else {
                var datos = ppp.node.data.jstree;
                if (datos.url) {
                    if (ppp.action === 'select_node') {
                        $(`#${datos.input_id}`).prop("checked", true);
                    } else if (ppp.action === 'deselect_node') {
                        $(`#${datos.input_id}`).prop("checked", false);
                    }
                }
            }
        }catch (e) {

        }
        //alert(JSON.stringify(data));
    });
});