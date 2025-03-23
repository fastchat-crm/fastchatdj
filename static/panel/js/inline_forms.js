window.django = {jQuery: $};
const btnAddInlineForm = document.querySelectorAll('.btnAddInlineForm');

function getElementInlineForm(target, selector) {
    let parent = target.parentElement;
    let output = null;
    while (parent.getAttribute("data-isinline") !== "true" && parent.tagName.toLowerCase() !== "body") {
        if ('querySelector' in parent && parent.querySelector(selector)) {
            output = parent.querySelector(selector);
            break;
        }
        parent = parent.parentElement;
    }
    return output;
}

function getTemplateInlineForm(target) {
    return getElementInlineForm(target, '.templateInlineForm').cloneNode(true);
}

function getTemplateEmptyContainer(target) {
    return getElementInlineForm(target, '.empty-container');
}

function removeEmptyMessage(target, fieldName) {
    const el = getElementInlineForm(target, `.empty-${fieldName}`);
    el && el.remove();
}

function getContainerInlineForm(target) {
    return getElementInlineForm(target, '.containerInlineForm');
}

function execFormsetEvent(element) {
    if (element) {
        element.dispatchEvent(new CustomEvent(
            'formset:added', {
                bubbles: true,
                detail: {
                    formsetName: "as"
                }
            }
        ));
    }
}

function dispatchFormsetEvent(element) {
    const elementTag = ["input", "textarea", "select"];
    execFormsetEvent(element);
    elementTag.forEach(t => {
        element.querySelectorAll(t).forEach(selector => execFormsetEvent(selector));
    });
}

function indexarFormulario(containerInlineForm) {
    containerInlineForm.querySelectorAll('.inlineFormRow').forEach((element, index) => {
        let btnTitle = element.querySelector('.btnTitle');
        if(btnTitle){
            btnTitle.setHTML(btnTitle.getAttribute('data-btntitle').replaceAll('__num_item__', (index+1).toString()));
        }
        element.querySelectorAll('input,select,textarea').forEach(e => {
            let name = e.getAttribute("data-fieldnametemplate");
            if (name) {
                let id = `id_${name}`;
                let inlineFormRowCount = index;
                name = name.replaceAll('__prefix__', inlineFormRowCount);
                id = id.replaceAll('__prefix__', inlineFormRowCount);
                e.setAttribute('id', id);
                e.setAttribute('name', name);
                let formGroup = e.closest('.form-group');
                formGroup.querySelector('.invalid-feedback').setAttribute("id", `errorMessage${name}`);
                formGroup.querySelector('label').setAttribute("for", id);
            }
        });
    });
}

function setFieldNameTemplate(template) {
    template.querySelectorAll('input,select,textarea').forEach(e => {
        let name = e.getAttribute("name");
        if (name) {
            e.setAttribute('data-fieldnametemplate', name);
        }
    });
}

btnAddInlineForm.forEach(btn => {
    btn.onclick = (event) => {
        const template = getTemplateInlineForm(event.target);
        const emptyContainerTemplate = getTemplateEmptyContainer(event.target);
        const fieldName = btn.getAttribute("data-fieldname");
        const containerInlineForm = getContainerInlineForm(event.target);
        const txtTotalForms = containerInlineForm.querySelector('input[name$=_set-TOTAL_FORMS]');
        if (template && containerInlineForm) {
            template.removeAttribute("style");
            template.classList.remove("templateInlineForm");
            template.classList.remove("empty-form");
            template.classList.add("inlineFormRow");
            setFieldNameTemplate(template);
            removeEmptyMessage(event.target, fieldName);
            containerInlineForm.appendChild(template);
            indexarFormulario(containerInlineForm);
            dispatchFormsetEvent(template);
            txtTotalForms.value = containerInlineForm.querySelectorAll('.inlineFormRow').length;
            template.querySelector('.btnQuitInlineForm').onclick = () => {
                template.remove();
                indexarFormulario(containerInlineForm);
                if (containerInlineForm.querySelectorAll('.inlineFormRow').length === 0) {
                    emptyContainerTemplate.removeAttribute("style");
                    emptyContainerTemplate.classList.add(`empty-${fieldName}`);
                    containerInlineForm.appendChild(emptyContainerTemplate);
                }
                txtTotalForms.value = containerInlineForm.querySelectorAll('.inlineFormRow').length;
                document.dispatchEvent(new CustomEvent("formset:removed", {
                    detail: {
                        formsetName: "a"
                    }
                }));
            };
        }
    }
});