try {
    "use strict";
    var WPFormsElementorFrontend = window.WPFormsElementorFrontend || function (o, t) {
        var i = {
            init: function () {
                i.events()
            }, events: function () {
                t(o).on("elementor/popup/show", function (e, o, n) {
                    var r = t("#elementor-popup-modal-" + o).find(".wpforms-form");
                    r.length && i.initFields(r)
                })
            }, initFields: function (e) {
                wpforms.ready(), "undefined" != typeof wpformsModernFileUpload && wpformsModernFileUpload.init(), "undefined" != typeof wpformsRecaptchaLoad && "undefined" != typeof grecaptcha && ("v3" === wpformsElementorVars.recaptcha_type ? grecaptcha.ready(wpformsRecaptchaLoad) : wpformsRecaptchaLoad()), t(o).trigger("wpforms_elementor_form_fields_initialized", [e])
            }
        };
        return i
    }(document, (window, jQuery));
    WPFormsElementorFrontend.init()
} catch (e) {
    console.log(e)
}
try {
    /*! jQuery Validation Plugin - v1.19.0 - 11/28/2018
 * https://jqueryvalidation.org/
 * Copyright (c) 2018 Jörn Zaefferer; Licensed MIT */
    !function (a) {
        "function" == typeof define && define.amd ? define(["jquery"], a) : "object" == typeof module && module.exports ? module.exports = a(require("jquery")) : a(jQuery)
    }(function (a) {
        a.extend(a.fn, {
            validate: function (b) {
                if (!this.length) return void (b && b.debug && window.console && console.warn("Nothing selected, can't validate, returning nothing."));
                var c = a.data(this[0], "validator");
                return c ? c : (this.attr("novalidate", "novalidate"), c = new a.validator(b, this[0]), a.data(this[0], "validator", c), c.settings.onsubmit && (this.on("click.validate", ":submit", function (b) {
                    c.submitButton = b.currentTarget, a(this).hasClass("cancel") && (c.cancelSubmit = !0), void 0 !== a(this).attr("formnovalidate") && (c.cancelSubmit = !0)
                }), this.on("submit.validate", function (b) {
                    function d() {
                        var d, e;
                        return c.submitButton && (c.settings.submitHandler || c.formSubmitted) && (d = a("<input type='hidden'/>").attr("name", c.submitButton.name).val(a(c.submitButton).val()).appendTo(c.currentForm)), !(c.settings.submitHandler && !c.settings.debug) || (e = c.settings.submitHandler.call(c, c.currentForm, b), d && d.remove(), void 0 !== e && e)
                    }

                    return c.settings.debug && b.preventDefault(), c.cancelSubmit ? (c.cancelSubmit = !1, d()) : c.form() ? c.pendingRequest ? (c.formSubmitted = !0, !1) : d() : (c.focusInvalid(), !1)
                })), c)
            }, valid: function () {
                var b, c, d;
                return a(this[0]).is("form") ? b = this.validate().form() : (d = [], b = !0, c = a(this[0].form).validate(), this.each(function () {
                    b = c.element(this) && b, b || (d = d.concat(c.errorList))
                }), c.errorList = d), b
            }, rules: function (b, c) {
                var d, e, f, g, h, i, j = this[0],
                    k = "undefined" != typeof this.attr("contenteditable") && "false" !== this.attr("contenteditable");
                if (null != j && (!j.form && k && (j.form = this.closest("form")[0], j.name = this.attr("name")), null != j.form)) {
                    if (b) switch (d = a.data(j.form, "validator").settings, e = d.rules, f = a.validator.staticRules(j), b) {
                        case"add":
                            a.extend(f, a.validator.normalizeRule(c)), delete f.messages, e[j.name] = f, c.messages && (d.messages[j.name] = a.extend(d.messages[j.name], c.messages));
                            break;
                        case"remove":
                            return c ? (i = {}, a.each(c.split(/\s/), function (a, b) {
                                i[b] = f[b], delete f[b]
                            }), i) : (delete e[j.name], f)
                    }
                    return g = a.validator.normalizeRules(a.extend({}, a.validator.classRules(j), a.validator.attributeRules(j), a.validator.dataRules(j), a.validator.staticRules(j)), j), g.required && (h = g.required, delete g.required, g = a.extend({required: h}, g)), g.remote && (h = g.remote, delete g.remote, g = a.extend(g, {remote: h})), g
                }
            }
        }), a.extend(a.expr.pseudos || a.expr[":"], {
            blank: function (b) {
                return !a.trim("" + a(b).val())
            }, filled: function (b) {
                var c = a(b).val();
                return null !== c && !!a.trim("" + c)
            }, unchecked: function (b) {
                return !a(b).prop("checked")
            }
        }), a.validator = function (b, c) {
            this.settings = a.extend(!0, {}, a.validator.defaults, b), this.currentForm = c, this.init()
        }, a.validator.format = function (b, c) {
            return 1 === arguments.length ? function () {
                var c = a.makeArray(arguments);
                return c.unshift(b), a.validator.format.apply(this, c)
            } : void 0 === c ? b : (arguments.length > 2 && c.constructor !== Array && (c = a.makeArray(arguments).slice(1)), c.constructor !== Array && (c = [c]), a.each(c, function (a, c) {
                b = b.replace(new RegExp("\\{" + a + "\\}", "g"), function () {
                    return c
                })
            }), b)
        }, a.extend(a.validator, {
            defaults: {
                messages: {},
                groups: {},
                rules: {},
                errorClass: "error",
                pendingClass: "pending",
                validClass: "valid",
                errorElement: "label",
                focusCleanup: !1,
                focusInvalid: !0,
                errorContainer: a([]),
                errorLabelContainer: a([]),
                onsubmit: !0,
                ignore: ":hidden",
                ignoreTitle: !1,
                onfocusin: function (a) {
                    this.lastActive = a, this.settings.focusCleanup && (this.settings.unhighlight && this.settings.unhighlight.call(this, a, this.settings.errorClass, this.settings.validClass), this.hideThese(this.errorsFor(a)))
                },
                onfocusout: function (a) {
                    this.checkable(a) || !(a.name in this.submitted) && this.optional(a) || this.element(a)
                },
                onkeyup: function (b, c) {
                    var d = [16, 17, 18, 20, 35, 36, 37, 38, 39, 40, 45, 144, 225];
                    9 === c.which && "" === this.elementValue(b) || a.inArray(c.keyCode, d) !== -1 || (b.name in this.submitted || b.name in this.invalid) && this.element(b)
                },
                onclick: function (a) {
                    a.name in this.submitted ? this.element(a) : a.parentNode.name in this.submitted && this.element(a.parentNode)
                },
                highlight: function (b, c, d) {
                    "radio" === b.type ? this.findByName(b.name).addClass(c).removeClass(d) : a(b).addClass(c).removeClass(d)
                },
                unhighlight: function (b, c, d) {
                    "radio" === b.type ? this.findByName(b.name).removeClass(c).addClass(d) : a(b).removeClass(c).addClass(d)
                }
            },
            setDefaults: function (b) {
                a.extend(a.validator.defaults, b)
            },
            messages: {
                required: "This field is required.",
                remote: "Please fix this field.",
                email: "Please enter a valid email address.",
                url: "Please enter a valid URL.",
                date: "Please enter a valid date.",
                dateISO: "Please enter a valid date (ISO).",
                number: "Please enter a valid number.",
                digits: "Please enter only digits.",
                equalTo: "Please enter the same value again.",
                maxlength: a.validator.format("Please enter no more than {0} characters."),
                minlength: a.validator.format("Please enter at least {0} characters."),
                rangelength: a.validator.format("Please enter a value between {0} and {1} characters long."),
                range: a.validator.format("Please enter a value between {0} and {1}."),
                max: a.validator.format("Please enter a value less than or equal to {0}."),
                min: a.validator.format("Please enter a value greater than or equal to {0}."),
                step: a.validator.format("Please enter a multiple of {0}.")
            },
            autoCreateRanges: !1,
            prototype: {
                init: function () {
                    function b(b) {
                        var c = "undefined" != typeof a(this).attr("contenteditable") && "false" !== a(this).attr("contenteditable");
                        if (!this.form && c && (this.form = a(this).closest("form")[0], this.name = a(this).attr("name")), d === this.form) {
                            var e = a.data(this.form, "validator"), f = "on" + b.type.replace(/^validate/, ""),
                                g = e.settings;
                            g[f] && !a(this).is(g.ignore) && g[f].call(e, this, b)
                        }
                    }

                    this.labelContainer = a(this.settings.errorLabelContainer), this.errorContext = this.labelContainer.length && this.labelContainer || a(this.currentForm), this.containers = a(this.settings.errorContainer).add(this.settings.errorLabelContainer), this.submitted = {}, this.valueCache = {}, this.pendingRequest = 0, this.pending = {}, this.invalid = {}, this.reset();
                    var c, d = this.currentForm, e = this.groups = {};
                    a.each(this.settings.groups, function (b, c) {
                        "string" == typeof c && (c = c.split(/\s/)), a.each(c, function (a, c) {
                            e[c] = b
                        })
                    }), c = this.settings.rules, a.each(c, function (b, d) {
                        c[b] = a.validator.normalizeRule(d)
                    }), a(this.currentForm).on("focusin.validate focusout.validate keyup.validate", ":text, [type='password'], [type='file'], select, textarea, [type='number'], [type='search'], [type='tel'], [type='url'], [type='email'], [type='datetime'], [type='date'], [type='month'], [type='week'], [type='time'], [type='datetime-local'], [type='range'], [type='color'], [type='radio'], [type='checkbox'], [contenteditable], [type='button']", b).on("click.validate", "select, option, [type='radio'], [type='checkbox']", b), this.settings.invalidHandler && a(this.currentForm).on("invalid-form.validate", this.settings.invalidHandler)
                }, form: function () {
                    return this.checkForm(), a.extend(this.submitted, this.errorMap), this.invalid = a.extend({}, this.errorMap), this.valid() || a(this.currentForm).triggerHandler("invalid-form", [this]), this.showErrors(), this.valid()
                }, checkForm: function () {
                    this.prepareForm();
                    for (var a = 0, b = this.currentElements = this.elements(); b[a]; a++) this.check(b[a]);
                    return this.valid()
                }, element: function (b) {
                    var c, d, e = this.clean(b), f = this.validationTargetFor(e), g = this, h = !0;
                    return void 0 === f ? delete this.invalid[e.name] : (this.prepareElement(f), this.currentElements = a(f), d = this.groups[f.name], d && a.each(this.groups, function (a, b) {
                        b === d && a !== f.name && (e = g.validationTargetFor(g.clean(g.findByName(a))), e && e.name in g.invalid && (g.currentElements.push(e), h = g.check(e) && h))
                    }), c = this.check(f) !== !1, h = h && c, c ? this.invalid[f.name] = !1 : this.invalid[f.name] = !0, this.numberOfInvalids() || (this.toHide = this.toHide.add(this.containers)), this.showErrors(), a(b).attr("aria-invalid", !c)), h
                }, showErrors: function (b) {
                    if (b) {
                        var c = this;
                        a.extend(this.errorMap, b), this.errorList = a.map(this.errorMap, function (a, b) {
                            return {message: a, element: c.findByName(b)[0]}
                        }), this.successList = a.grep(this.successList, function (a) {
                            return !(a.name in b)
                        })
                    }
                    this.settings.showErrors ? this.settings.showErrors.call(this, this.errorMap, this.errorList) : this.defaultShowErrors()
                }, resetForm: function () {
                    a.fn.resetForm && a(this.currentForm).resetForm(), this.invalid = {}, this.submitted = {}, this.prepareForm(), this.hideErrors();
                    var b = this.elements().removeData("previousValue").removeAttr("aria-invalid");
                    this.resetElements(b)
                }, resetElements: function (a) {
                    var b;
                    if (this.settings.unhighlight) for (b = 0; a[b]; b++) this.settings.unhighlight.call(this, a[b], this.settings.errorClass, ""), this.findByName(a[b].name).removeClass(this.settings.validClass); else a.removeClass(this.settings.errorClass).removeClass(this.settings.validClass)
                }, numberOfInvalids: function () {
                    return this.objectLength(this.invalid)
                }, objectLength: function (a) {
                    var b, c = 0;
                    for (b in a) void 0 !== a[b] && null !== a[b] && a[b] !== !1 && c++;
                    return c
                }, hideErrors: function () {
                    this.hideThese(this.toHide)
                }, hideThese: function (a) {
                    a.not(this.containers).text(""), this.addWrapper(a).hide()
                }, valid: function () {
                    return 0 === this.size()
                }, size: function () {
                    return this.errorList.length
                }, focusInvalid: function () {
                    if (this.settings.focusInvalid) try {
                        a(this.findLastActive() || this.errorList.length && this.errorList[0].element || []).filter(":visible").focus().trigger("focusin")
                    } catch (b) {
                    }
                }, findLastActive: function () {
                    var b = this.lastActive;
                    return b && 1 === a.grep(this.errorList, function (a) {
                        return a.element.name === b.name
                    }).length && b
                }, elements: function () {
                    var b = this, c = {};
                    return a(this.currentForm).find("input, select, textarea, [contenteditable]").not(":submit, :reset, :image, :disabled").not(this.settings.ignore).filter(function () {
                        var d = this.name || a(this).attr("name"),
                            e = "undefined" != typeof a(this).attr("contenteditable") && "false" !== a(this).attr("contenteditable");
                        return !d && b.settings.debug && window.console && console.error("%o has no name assigned", this), e && (this.form = a(this).closest("form")[0], this.name = d), this.form === b.currentForm && (!(d in c || !b.objectLength(a(this).rules())) && (c[d] = !0, !0))
                    })
                }, clean: function (b) {
                    return a(b)[0]
                }, errors: function () {
                    var b = this.settings.errorClass.split(" ").join(".");
                    return a(this.settings.errorElement + "." + b, this.errorContext)
                }, resetInternals: function () {
                    this.successList = [], this.errorList = [], this.errorMap = {}, this.toShow = a([]), this.toHide = a([])
                }, reset: function () {
                    this.resetInternals(), this.currentElements = a([])
                }, prepareForm: function () {
                    this.reset(), this.toHide = this.errors().add(this.containers)
                }, prepareElement: function (a) {
                    this.reset(), this.toHide = this.errorsFor(a)
                }, elementValue: function (b) {
                    var c, d, e = a(b), f = b.type,
                        g = "undefined" != typeof e.attr("contenteditable") && "false" !== e.attr("contenteditable");
                    return "radio" === f || "checkbox" === f ? this.findByName(b.name).filter(":checked").val() : "number" === f && "undefined" != typeof b.validity ? b.validity.badInput ? "NaN" : e.val() : (c = g ? e.text() : e.val(), "file" === f ? "C:\\fakepath\\" === c.substr(0, 12) ? c.substr(12) : (d = c.lastIndexOf("/"), d >= 0 ? c.substr(d + 1) : (d = c.lastIndexOf("\\"), d >= 0 ? c.substr(d + 1) : c)) : "string" == typeof c ? c.replace(/\r/g, "") : c)
                }, check: function (b) {
                    b = this.validationTargetFor(this.clean(b));
                    var c, d, e, f, g = a(b).rules(), h = a.map(g, function (a, b) {
                        return b
                    }).length, i = !1, j = this.elementValue(b);
                    "function" == typeof g.normalizer ? f = g.normalizer : "function" == typeof this.settings.normalizer && (f = this.settings.normalizer), f && (j = f.call(b, j), delete g.normalizer);
                    for (d in g) {
                        e = {method: d, parameters: g[d]};
                        try {
                            if (c = a.validator.methods[d].call(this, j, b, e.parameters), "dependency-mismatch" === c && 1 === h) {
                                i = !0;
                                continue
                            }
                            if (i = !1, "pending" === c) return void (this.toHide = this.toHide.not(this.errorsFor(b)));
                            if (!c) return this.formatAndAdd(b, e), !1
                        } catch (k) {
                            throw this.settings.debug && window.console && console.log("Exception occurred when checking element " + b.id + ", check the '" + e.method + "' method.", k), k instanceof TypeError && (k.message += ".  Exception occurred when checking element " + b.id + ", check the '" + e.method + "' method."), k
                        }
                    }
                    if (!i) return this.objectLength(g) && this.successList.push(b), !0
                }, customDataMessage: function (b, c) {
                    return a(b).data("msg" + c.charAt(0).toUpperCase() + c.substring(1).toLowerCase()) || a(b).data("msg")
                }, customMessage: function (a, b) {
                    var c = this.settings.messages[a];
                    return c && (c.constructor === String ? c : c[b])
                }, findDefined: function () {
                    for (var a = 0; a < arguments.length; a++) if (void 0 !== arguments[a]) return arguments[a]
                }, defaultMessage: function (b, c) {
                    "string" == typeof c && (c = {method: c});
                    var d = this.findDefined(this.customMessage(b.name, c.method), this.customDataMessage(b, c.method), !this.settings.ignoreTitle && b.title || void 0, a.validator.messages[c.method], "<strong>Warning: No message defined for " + b.name + "</strong>"),
                        e = /\$?\{(\d+)\}/g;
                    return "function" == typeof d ? d = d.call(this, c.parameters, b) : e.test(d) && (d = a.validator.format(d.replace(e, "{$1}"), c.parameters)), d
                }, formatAndAdd: function (a, b) {
                    var c = this.defaultMessage(a, b);
                    this.errorList.push({
                        message: c,
                        element: a,
                        method: b.method
                    }), this.errorMap[a.name] = c, this.submitted[a.name] = c
                }, addWrapper: function (a) {
                    return this.settings.wrapper && (a = a.add(a.parent(this.settings.wrapper))), a
                }, defaultShowErrors: function () {
                    var a, b, c;
                    for (a = 0; this.errorList[a]; a++) c = this.errorList[a], this.settings.highlight && this.settings.highlight.call(this, c.element, this.settings.errorClass, this.settings.validClass), this.showLabel(c.element, c.message);
                    if (this.errorList.length && (this.toShow = this.toShow.add(this.containers)), this.settings.success) for (a = 0; this.successList[a]; a++) this.showLabel(this.successList[a]);
                    if (this.settings.unhighlight) for (a = 0, b = this.validElements(); b[a]; a++) this.settings.unhighlight.call(this, b[a], this.settings.errorClass, this.settings.validClass);
                    this.toHide = this.toHide.not(this.toShow), this.hideErrors(), this.addWrapper(this.toShow).show()
                }, validElements: function () {
                    return this.currentElements.not(this.invalidElements())
                }, invalidElements: function () {
                    return a(this.errorList).map(function () {
                        return this.element
                    })
                }, showLabel: function (b, c) {
                    var d, e, f, g, h = this.errorsFor(b), i = this.idOrName(b), j = a(b).attr("aria-describedby");
                    h.length ? (h.removeClass(this.settings.validClass).addClass(this.settings.errorClass), h.html(c)) : (h = a("<" + this.settings.errorElement + ">").attr("id", i + "-error").addClass(this.settings.errorClass).html(c || ""), d = h, this.settings.wrapper && (d = h.hide().show().wrap("<" + this.settings.wrapper + "/>").parent()), this.labelContainer.length ? this.labelContainer.append(d) : this.settings.errorPlacement ? this.settings.errorPlacement.call(this, d, a(b)) : d.insertAfter(b), h.is("label") ? h.attr("for", i) : 0 === h.parents("label[for='" + this.escapeCssMeta(i) + "']").length && (f = h.attr("id"), j ? j.match(new RegExp("\\b" + this.escapeCssMeta(f) + "\\b")) || (j += " " + f) : j = f, a(b).attr("aria-describedby", j), e = this.groups[b.name], e && (g = this, a.each(g.groups, function (b, c) {
                        c === e && a("[name='" + g.escapeCssMeta(b) + "']", g.currentForm).attr("aria-describedby", h.attr("id"))
                    })))), !c && this.settings.success && (h.text(""), "string" == typeof this.settings.success ? h.addClass(this.settings.success) : this.settings.success(h, b)), this.toShow = this.toShow.add(h)
                }, errorsFor: function (b) {
                    var c = this.escapeCssMeta(this.idOrName(b)), d = a(b).attr("aria-describedby"),
                        e = "label[for='" + c + "'], label[for='" + c + "'] *";
                    return d && (e = e + ", #" + this.escapeCssMeta(d).replace(/\s+/g, ", #")), this.errors().filter(e)
                }, escapeCssMeta: function (a) {
                    return a.replace(/([\\!"#$%&'()*+,.\/:;<=>?@\[\]^`{|}~])/g, "\\$1")
                }, idOrName: function (a) {
                    return this.groups[a.name] || (this.checkable(a) ? a.name : a.id || a.name)
                }, validationTargetFor: function (b) {
                    return this.checkable(b) && (b = this.findByName(b.name)), a(b).not(this.settings.ignore)[0]
                }, checkable: function (a) {
                    return /radio|checkbox/i.test(a.type)
                }, findByName: function (b) {
                    return a(this.currentForm).find("[name='" + this.escapeCssMeta(b) + "']")
                }, getLength: function (b, c) {
                    switch (c.nodeName.toLowerCase()) {
                        case"select":
                            return a("option:selected", c).length;
                        case"input":
                            if (this.checkable(c)) return this.findByName(c.name).filter(":checked").length
                    }
                    return b.length
                }, depend: function (a, b) {
                    return !this.dependTypes[typeof a] || this.dependTypes[typeof a](a, b)
                }, dependTypes: {
                    "boolean": function (a) {
                        return a
                    }, string: function (b, c) {
                        return !!a(b, c.form).length
                    }, "function": function (a, b) {
                        return a(b)
                    }
                }, optional: function (b) {
                    var c = this.elementValue(b);
                    return !a.validator.methods.required.call(this, c, b) && "dependency-mismatch"
                }, startRequest: function (b) {
                    this.pending[b.name] || (this.pendingRequest++, a(b).addClass(this.settings.pendingClass), this.pending[b.name] = !0)
                }, stopRequest: function (b, c) {
                    this.pendingRequest--, this.pendingRequest < 0 && (this.pendingRequest = 0), delete this.pending[b.name], a(b).removeClass(this.settings.pendingClass), c && 0 === this.pendingRequest && this.formSubmitted && this.form() ? (a(this.currentForm).submit(), this.submitButton && a("input:hidden[name='" + this.submitButton.name + "']", this.currentForm).remove(), this.formSubmitted = !1) : !c && 0 === this.pendingRequest && this.formSubmitted && (a(this.currentForm).triggerHandler("invalid-form", [this]), this.formSubmitted = !1)
                }, previousValue: function (b, c) {
                    return c = "string" == typeof c && c || "remote", a.data(b, "previousValue") || a.data(b, "previousValue", {
                        old: null,
                        valid: !0,
                        message: this.defaultMessage(b, {method: c})
                    })
                }, destroy: function () {
                    this.resetForm(), a(this.currentForm).off(".validate").removeData("validator").find(".validate-equalTo-blur").off(".validate-equalTo").removeClass("validate-equalTo-blur").find(".validate-lessThan-blur").off(".validate-lessThan").removeClass("validate-lessThan-blur").find(".validate-lessThanEqual-blur").off(".validate-lessThanEqual").removeClass("validate-lessThanEqual-blur").find(".validate-greaterThanEqual-blur").off(".validate-greaterThanEqual").removeClass("validate-greaterThanEqual-blur").find(".validate-greaterThan-blur").off(".validate-greaterThan").removeClass("validate-greaterThan-blur")
                }
            },
            classRuleSettings: {
                required: {required: !0},
                email: {email: !0},
                url: {url: !0},
                date: {date: !0},
                dateISO: {dateISO: !0},
                number: {number: !0},
                digits: {digits: !0},
                creditcard: {creditcard: !0}
            },
            addClassRules: function (b, c) {
                b.constructor === String ? this.classRuleSettings[b] = c : a.extend(this.classRuleSettings, b)
            },
            classRules: function (b) {
                var c = {}, d = a(b).attr("class");
                return d && a.each(d.split(" "), function () {
                    this in a.validator.classRuleSettings && a.extend(c, a.validator.classRuleSettings[this])
                }), c
            },
            normalizeAttributeRule: function (a, b, c, d) {
                /min|max|step/.test(c) && (null === b || /number|range|text/.test(b)) && (d = Number(d), isNaN(d) && (d = void 0)), d || 0 === d ? a[c] = d : b === c && "range" !== b && (a[c] = !0)
            },
            attributeRules: function (b) {
                var c, d, e = {}, f = a(b), g = b.getAttribute("type");
                for (c in a.validator.methods) "required" === c ? (d = b.getAttribute(c), "" === d && (d = !0), d = !!d) : d = f.attr(c), this.normalizeAttributeRule(e, g, c, d);
                return e.maxlength && /-1|2147483647|524288/.test(e.maxlength) && delete e.maxlength, e
            },
            dataRules: function (b) {
                var c, d, e = {}, f = a(b), g = b.getAttribute("type");
                for (c in a.validator.methods) d = f.data("rule" + c.charAt(0).toUpperCase() + c.substring(1).toLowerCase()), "" === d && (d = !0), this.normalizeAttributeRule(e, g, c, d);
                return e
            },
            staticRules: function (b) {
                var c = {}, d = a.data(b.form, "validator");
                return d.settings.rules && (c = a.validator.normalizeRule(d.settings.rules[b.name]) || {}), c
            },
            normalizeRules: function (b, c) {
                return a.each(b, function (d, e) {
                    if (e === !1) return void delete b[d];
                    if (e.param || e.depends) {
                        var f = !0;
                        switch (typeof e.depends) {
                            case"string":
                                f = !!a(e.depends, c.form).length;
                                break;
                            case"function":
                                f = e.depends.call(c, c)
                        }
                        f ? b[d] = void 0 === e.param || e.param : (a.data(c.form, "validator").resetElements(a(c)), delete b[d])
                    }
                }), a.each(b, function (d, e) {
                    b[d] = a.isFunction(e) && "normalizer" !== d ? e(c) : e
                }), a.each(["minlength", "maxlength"], function () {
                    b[this] && (b[this] = Number(b[this]))
                }), a.each(["rangelength", "range"], function () {
                    var c;
                    b[this] && (a.isArray(b[this]) ? b[this] = [Number(b[this][0]), Number(b[this][1])] : "string" == typeof b[this] && (c = b[this].replace(/[\[\]]/g, "").split(/[\s,]+/), b[this] = [Number(c[0]), Number(c[1])]))
                }), a.validator.autoCreateRanges && (null != b.min && null != b.max && (b.range = [b.min, b.max], delete b.min, delete b.max), null != b.minlength && null != b.maxlength && (b.rangelength = [b.minlength, b.maxlength], delete b.minlength, delete b.maxlength)), b
            },
            normalizeRule: function (b) {
                if ("string" == typeof b) {
                    var c = {};
                    a.each(b.split(/\s/), function () {
                        c[this] = !0
                    }), b = c
                }
                return b
            },
            addMethod: function (b, c, d) {
                a.validator.methods[b] = c, a.validator.messages[b] = void 0 !== d ? d : a.validator.messages[b], c.length < 3 && a.validator.addClassRules(b, a.validator.normalizeRule(b))
            },
            methods: {
                required: function (b, c, d) {
                    if (!this.depend(d, c)) return "dependency-mismatch";
                    if ("select" === c.nodeName.toLowerCase()) {
                        var e = a(c).val();
                        return e && e.length > 0
                    }
                    return this.checkable(c) ? this.getLength(b, c) > 0 : void 0 !== b && null !== b && b.length > 0
                }, email: function (a, b) {
                    return this.optional(b) || /^[a-zA-Z0-9.!#$%&'*+\/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/.test(a)
                }, url: function (a, b) {
                    return this.optional(b) || /^(?:(?:(?:https?|ftp):)?\/\/)(?:\S+(?::\S*)?@)?(?:(?!(?:10|127)(?:\.\d{1,3}){3})(?!(?:169\.254|192\.168)(?:\.\d{1,3}){2})(?!172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2})(?:[1-9]\d?|1\d\d|2[01]\d|22[0-3])(?:\.(?:1?\d{1,2}|2[0-4]\d|25[0-5])){2}(?:\.(?:[1-9]\d?|1\d\d|2[0-4]\d|25[0-4]))|(?:(?:[a-z\u00a1-\uffff0-9]-*)*[a-z\u00a1-\uffff0-9]+)(?:\.(?:[a-z\u00a1-\uffff0-9]-*)*[a-z\u00a1-\uffff0-9]+)*(?:\.(?:[a-z\u00a1-\uffff]{2,})).?)(?::\d{2,5})?(?:[\/?#]\S*)?$/i.test(a)
                }, date: function () {
                    var a = !1;
                    return function (b, c) {
                        return a || (a = !0, this.settings.debug && window.console && console.warn("The `date` method is deprecated and will be removed in version '2.0.0'.\nPlease don't use it, since it relies on the Date constructor, which\nbehaves very differently across browsers and locales. Use `dateISO`\ninstead or one of the locale specific methods in `localizations/`\nand `additional-methods.js`.")), this.optional(c) || !/Invalid|NaN/.test(new Date(b).toString())
                    }
                }(), dateISO: function (a, b) {
                    return this.optional(b) || /^\d{4}[\/\-](0?[1-9]|1[012])[\/\-](0?[1-9]|[12][0-9]|3[01])$/.test(a)
                }, number: function (a, b) {
                    return this.optional(b) || /^(?:-?\d+|-?\d{1,3}(?:,\d{3})+)?(?:\.\d+)?$/.test(a)
                }, digits: function (a, b) {
                    return this.optional(b) || /^\d+$/.test(a)
                }, minlength: function (b, c, d) {
                    var e = a.isArray(b) ? b.length : this.getLength(b, c);
                    return this.optional(c) || e >= d
                }, maxlength: function (b, c, d) {
                    var e = a.isArray(b) ? b.length : this.getLength(b, c);
                    return this.optional(c) || e <= d
                }, rangelength: function (b, c, d) {
                    var e = a.isArray(b) ? b.length : this.getLength(b, c);
                    return this.optional(c) || e >= d[0] && e <= d[1]
                }, min: function (a, b, c) {
                    return this.optional(b) || a >= c
                }, max: function (a, b, c) {
                    return this.optional(b) || a <= c
                }, range: function (a, b, c) {
                    return this.optional(b) || a >= c[0] && a <= c[1]
                }, step: function (b, c, d) {
                    var e, f = a(c).attr("type"), g = "Step attribute on input type " + f + " is not supported.",
                        h = ["text", "number", "range"], i = new RegExp("\\b" + f + "\\b"), j = f && !i.test(h.join()),
                        k = function (a) {
                            var b = ("" + a).match(/(?:\.(\d+))?$/);
                            return b && b[1] ? b[1].length : 0
                        }, l = function (a) {
                            return Math.round(a * Math.pow(10, e))
                        }, m = !0;
                    if (j) throw new Error(g);
                    return e = k(d), (k(b) > e || l(b) % l(d) !== 0) && (m = !1), this.optional(c) || m
                }, equalTo: function (b, c, d) {
                    var e = a(d);
                    return this.settings.onfocusout && e.not(".validate-equalTo-blur").length && e.addClass("validate-equalTo-blur").on("blur.validate-equalTo", function () {
                        a(c).valid()
                    }), b === e.val()
                }, remote: function (b, c, d, e) {
                    if (this.optional(c)) return "dependency-mismatch";
                    e = "string" == typeof e && e || "remote";
                    var f, g, h, i = this.previousValue(c, e);
                    return this.settings.messages[c.name] || (this.settings.messages[c.name] = {}), i.originalMessage = i.originalMessage || this.settings.messages[c.name][e], this.settings.messages[c.name][e] = i.message, d = "string" == typeof d && {url: d} || d, h = a.param(a.extend({data: b}, d.data)), i.old === h ? i.valid : (i.old = h, f = this, this.startRequest(c), g = {}, g[c.name] = b, a.ajax(a.extend(!0, {
                        mode: "abort",
                        port: "validate" + c.name,
                        dataType: "json",
                        data: g,
                        context: f.currentForm,
                        success: function (a) {
                            var d, g, h, j = a === !0 || "true" === a;
                            f.settings.messages[c.name][e] = i.originalMessage, j ? (h = f.formSubmitted, f.resetInternals(), f.toHide = f.errorsFor(c), f.formSubmitted = h, f.successList.push(c), f.invalid[c.name] = !1, f.showErrors()) : (d = {}, g = a || f.defaultMessage(c, {
                                method: e,
                                parameters: b
                            }), d[c.name] = i.message = g, f.invalid[c.name] = !0, f.showErrors(d)), i.valid = j, f.stopRequest(c, j)
                        }
                    }, d)), "pending")
                }
            }
        });
        var b, c = {};
        return a.ajaxPrefilter ? a.ajaxPrefilter(function (a, b, d) {
            var e = a.port;
            "abort" === a.mode && (c[e] && c[e].abort(), c[e] = d)
        }) : (b = a.ajax, a.ajax = function (d) {
            var e = ("mode" in d ? d : a.ajaxSettings).mode, f = ("port" in d ? d : a.ajaxSettings).port;
            return "abort" === e ? (c[f] && c[f].abort(), c[f] = b.apply(this, arguments), c[f]) : b.apply(this, arguments)
        }), a
    })
} catch (e) {
    console.log(e)
}
try {
    /*! mailcheck v1.1.2 @licence MIT */
    var Mailcheck = {
        domainThreshold: 2,
        secondLevelThreshold: 2,
        topLevelThreshold: 2,
        defaultDomains: ["msn.com", "bellsouth.net", "telus.net", "comcast.net", "optusnet.com.au", "earthlink.net", "qq.com", "sky.com", "icloud.com", "mac.com", "sympatico.ca", "googlemail.com", "att.net", "xtra.co.nz", "web.de", "cox.net", "gmail.com", "ymail.com", "aim.com", "rogers.com", "verizon.net", "rocketmail.com", "google.com", "optonline.net", "sbcglobal.net", "aol.com", "me.com", "btinternet.com", "charter.net", "shaw.ca"],
        defaultSecondLevelDomains: ["yahoo", "hotmail", "mail", "live", "outlook", "gmx"],
        defaultTopLevelDomains: ["com", "com.au", "com.tw", "ca", "co.nz", "co.uk", "de", "fr", "it", "ru", "net", "org", "edu", "gov", "jp", "nl", "kr", "se", "eu", "ie", "co.il", "us", "at", "be", "dk", "hk", "es", "gr", "ch", "no", "cz", "in", "net", "net.au", "info", "biz", "mil", "co.jp", "sg", "hu", "uk"],
        run: function (a) {
            a.domains = a.domains || Mailcheck.defaultDomains, a.secondLevelDomains = a.secondLevelDomains || Mailcheck.defaultSecondLevelDomains, a.topLevelDomains = a.topLevelDomains || Mailcheck.defaultTopLevelDomains, a.distanceFunction = a.distanceFunction || Mailcheck.sift4Distance;
            var b = function (a) {
                    return a
                }, c = a.suggested || b, d = a.empty || b,
                e = Mailcheck.suggest(Mailcheck.encodeEmail(a.email), a.domains, a.secondLevelDomains, a.topLevelDomains, a.distanceFunction);
            return e ? c(e) : d()
        },
        suggest: function (a, b, c, d, e) {
            a = a.toLowerCase();
            var f = this.splitEmail(a);
            if (c && d && -1 !== c.indexOf(f.secondLevelDomain) && -1 !== d.indexOf(f.topLevelDomain)) return !1;
            var g = this.findClosestDomain(f.domain, b, e, this.domainThreshold);
            if (g) return g == f.domain ? !1 : {address: f.address, domain: g, full: f.address + "@" + g};
            var h = this.findClosestDomain(f.secondLevelDomain, c, e, this.secondLevelThreshold),
                i = this.findClosestDomain(f.topLevelDomain, d, e, this.topLevelThreshold);
            if (f.domain) {
                g = f.domain;
                var j = !1;
                if (h && h != f.secondLevelDomain && (g = g.replace(f.secondLevelDomain, h), j = !0), i && i != f.topLevelDomain && "" !== f.secondLevelDomain && (g = g.replace(new RegExp(f.topLevelDomain + "$"), i), j = !0), j) return {
                    address: f.address,
                    domain: g,
                    full: f.address + "@" + g
                }
            }
            return !1
        },
        findClosestDomain: function (a, b, c, d) {
            d = d || this.topLevelThreshold;
            var e, f = 1 / 0, g = null;
            if (!a || !b) return !1;
            c || (c = this.sift4Distance);
            for (var h = 0; h < b.length; h++) {
                if (a === b[h]) return a;
                e = c(a, b[h]), f > e && (f = e, g = b[h])
            }
            return d >= f && null !== g ? g : !1
        },
        sift4Distance: function (a, b, c) {
            if (void 0 === c && (c = 5), !a || !a.length) return b ? b.length : 0;
            if (!b || !b.length) return a.length;
            for (var d = a.length, e = b.length, f = 0, g = 0, h = 0, i = 0, j = 0, k = []; d > f && e > g;) {
                if (a.charAt(f) == b.charAt(g)) {
                    i++;
                    for (var l = !1, m = 0; m < k.length;) {
                        var n = k[m];
                        if (f <= n.c1 || g <= n.c2) {
                            l = Math.abs(g - f) >= Math.abs(n.c2 - n.c1), l ? j++ : n.trans || (n.trans = !0, j++);
                            break
                        }
                        f > n.c2 && g > n.c1 ? k.splice(m, 1) : m++
                    }
                    k.push({c1: f, c2: g, trans: l})
                } else {
                    h += i, i = 0, f != g && (f = g = Math.min(f, g));
                    for (var o = 0; c > o && (d > f + o || e > g + o); o++) {
                        if (d > f + o && a.charAt(f + o) == b.charAt(g)) {
                            f += o - 1, g--;
                            break
                        }
                        if (e > g + o && a.charAt(f) == b.charAt(g + o)) {
                            f--, g += o - 1;
                            break
                        }
                    }
                }
                f++, g++, (f >= d || g >= e) && (h += i, i = 0, f = g = Math.min(f, g))
            }
            return h += i, Math.round(Math.max(d, e) - h + j)
        },
        splitEmail: function (a) {
            a = null !== a ? a.replace(/^\s*/, "").replace(/\s*$/, "") : null;
            var b = a.split("@");
            if (b.length < 2) return !1;
            for (var c = 0; c < b.length; c++) if ("" === b[c]) return !1;
            var d = b.pop(), e = d.split("."), f = "", g = "";
            if (0 === e.length) return !1;
            if (1 == e.length) g = e[0]; else {
                f = e[0];
                for (var h = 1; h < e.length; h++) g += e[h] + ".";
                g = g.substring(0, g.length - 1)
            }
            return {topLevelDomain: g, secondLevelDomain: f, domain: d, address: b.join("@")}
        },
        encodeEmail: function (a) {
            var b = encodeURI(a);
            return b = b.replace("%20", " ").replace("%25", "%").replace("%5E", "^").replace("%60", "`").replace("%7B", "{").replace("%7C", "|").replace("%7D", "}")
        }
    };
    "undefined" != typeof module && module.exports && (module.exports = Mailcheck), "function" == typeof define && define.amd && define("mailcheck", [], function () {
        return Mailcheck
    }), "undefined" != typeof window && window.jQuery && !function (a) {
        a.fn.mailcheck = function (a) {
            var b = this;
            if (a.suggested) {
                var c = a.suggested;
                a.suggested = function (a) {
                    c(b, a)
                }
            }
            if (a.empty) {
                var d = a.empty;
                a.empty = function () {
                    d.call(null, b)
                }
            }
            a.email = this.val(), Mailcheck.run(a)
        }
    }(jQuery)
} catch (e) {
    console.log(e)
}
try {
    'use strict';
    var wpforms = window.wpforms || (function (document, window, $) {
        var app = {
            init: function () {
                $(app.ready);
                $(window).on('load', app.load);
                app.bindUIActions();
                app.bindOptinMonster();
            }, ready: function () {
                app.clearUrlQuery();
                app.setUserIndentifier();
                app.loadValidation();
                app.loadDatePicker();
                app.loadTimePicker();
                app.loadInputMask();
                app.loadSmartPhoneField();
                app.loadPayments();
                app.loadMailcheck();
                app.loadChoicesJS();
                $('.wpforms-randomize').each(function () {
                    var $list = $(this), $listItems = $list.children();
                    while ($listItems.length) {
                        $list.append($listItems.splice(Math.floor(Math.random() * $listItems.length), 1)[0]);
                    }
                });
                $('.wpforms-page-button').prop('disabled', false);
                $(document).trigger('wpformsReady');
            }, load: function () {
            }, clearUrlQuery: function () {
                var loc = window.location, query = loc.search;
                if (query.indexOf('wpforms_form_id=') !== -1) {
                    query = query.replace(/([&?]wpforms_form_id=[0-9]*$|wpforms_form_id=[0-9]*&|[?&]wpforms_form_id=[0-9]*(?=#))/, '');
                    history.replaceState({}, null, loc.origin + loc.pathname + query);
                }
            }, loadValidation: function () {
                if (typeof $.fn.validate !== 'undefined') {
                    $('.wpforms-input-temp-name').each(function (index, el) {
                        var random = Math.floor(Math.random() * 9999) + 1;
                        $(this).attr('name', 'wpf-temp-' + random);
                    });
                    $('.wpforms-validate input[type=url]').change(function () {
                        var url = $(this).val();
                        if (!url) {
                            return false;
                        }
                        if (url.substr(0, 7) !== 'http://' && url.substr(0, 8) !== 'https://') {
                            $(this).val('http://' + url);
                        }
                    });
                    $.validator.messages.required = wpforms_settings.val_required;
                    $.validator.messages.url = wpforms_settings.val_url;
                    $.validator.messages.email = wpforms_settings.val_email;
                    $.validator.messages.number = wpforms_settings.val_number;
                    if (typeof $.fn.payment !== 'undefined') {
                        $.validator.addMethod('creditcard', function (value, element) {
                            var valid = $.payment.validateCardNumber(value);
                            return this.optional(element) || valid;
                        }, wpforms_settings.val_creditcard);
                    }
                    $.validator.addMethod('extension', function (value, element, param) {
                        param = 'string' === typeof param ? param.replace(/,/g, '|') : 'png|jpe?g|gif';
                        return this.optional(element) || value.match(new RegExp('\\.(' + param + ')$', 'i'));
                    }, wpforms_settings.val_fileextension);
                    $.validator.addMethod('maxsize', function (value, element, param) {
                        var maxSize = param, optionalValue = this.optional(element), i, len, file;
                        if (optionalValue) {
                            return optionalValue;
                        }
                        if (element.files && element.files.length) {
                            i = 0;
                            len = element.files.length;
                            for (; i < len; i++) {
                                file = element.files[i];
                                if (file.size > maxSize) {
                                    return false;
                                }
                            }
                        }
                        return true;
                    }, wpforms_settings.val_filesize);
                    $.validator.methods.email = function (value, element) {
                        return this.optional(element) || /^[a-z0-9.!#$%&'*+\/=?^_`{|}~-]+@((?=[a-z0-9-]{1,63}\.)(xn--)?[a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,63}$/i.test(value);
                    };
                    $.validator.addMethod('restricted-email', function (value, element) {
                        var validator = this, $el = $(element), $field = $el.closest('.wpforms-field'),
                            $form = $el.closest('.wpforms-form');
                        if (!$el.val().length) {
                            return true;
                        }
                        this.startRequest(element);
                        $.post({
                            url: wpforms_settings.ajaxurl,
                            type: 'post',
                            async: false,
                            data: {
                                'token': $form.data('token'),
                                'action': 'wpforms_restricted_email',
                                'form_id': $form.data('formid'),
                                'field_id': $field.data('field-id'),
                                'email': $el.val(),
                            },
                            dataType: 'json',
                            success: function (response) {
                                var isValid = response.success && response.data, errors = {};
                                if (isValid) {
                                    validator.resetInternals();
                                    validator.toHide = validator.errorsFor(element);
                                    validator.showErrors();
                                } else {
                                    errors[element.name] = wpforms_settings.val_email_restricted;
                                    validator.showErrors(errors);
                                }
                                validator.stopRequest(element, isValid);
                            },
                        });
                        return 'pending';
                    }, wpforms_settings.val_email_restricted);
                    $.validator.addMethod('confirm', function (value, element, param) {
                        return $.validator.methods.equalTo.call(this, value, element, param);
                    }, wpforms_settings.val_confirm);
                    $.validator.addMethod('required-payment', function (value, element) {
                        return app.amountSanitize(value) > 0;
                    }, wpforms_settings.val_requiredpayment);
                    $.validator.addMethod('time12h', function (value, element) {
                        return this.optional(element) || /^((0?[1-9]|1[012])(:[0-5]\d){1,2}(\ ?[AP]M))$/i.test(value);
                    }, wpforms_settings.val_time12h);
                    $.validator.addMethod('time24h', function (value, element) {
                        return this.optional(element) || /^(([0-1]?[0-9])|([2][0-3])):([0-5]?[0-9])(\ ?[AP]M)?$/i.test(value);
                    }, wpforms_settings.val_time24h);
                    $.validator.addMethod('check-limit', function (value, element) {
                        var $ul = $(element).closest('ul'), $checked = $ul.find('input[type="checkbox"]:checked'),
                            choiceLimit = parseInt($ul.attr('data-choice-limit') || 0, 10);
                        if (0 === choiceLimit) {
                            return true;
                        }
                        return $checked.length <= choiceLimit;
                    }, function (params, element) {
                        var choiceLimit = parseInt($(element).closest('ul').attr('data-choice-limit') || 0, 10);
                        return wpforms_settings.val_checklimit.replace('{#}', choiceLimit);
                    });
                    if (typeof $.fn.intlTelInput !== 'undefined') {
                        $.validator.addMethod('smart-phone-field', function (value, element) {
                            if (value.match(/[^\d()\-+\s]/)) {
                                return false;
                            }
                            return this.optional(element) || $(element).intlTelInput('isValidNumber');
                        }, wpforms_settings.val_phone);
                    }
                    $.validator.addMethod('empty-blanks', function (value, element) {
                        if (typeof $.fn.inputmask === 'undefined') {
                            return true;
                        }
                        return !(value.indexOf(element.inputmask.opts.placeholder) + 1);
                    }, wpforms_settings.val_empty_blanks);
                    $.validator.addMethod('us-phone-field', function (value, element) {
                        if (value.match(/[^\d()\-+\s]/)) {
                            return false;
                        }
                        return this.optional(element) || value.replace(/[^\d]/g, '').length === 10;
                    }, wpforms_settings.val_phone);
                    $.validator.addMethod('int-phone-field', function (value, element) {
                        if (value.match(/[^\d()\-+\s]/)) {
                            return false;
                        }
                        return this.optional(element) || value.replace(/[^\d]/g, '').length > 0;
                    }, wpforms_settings.val_phone);
                    $('.wpforms-validate').each(function () {
                        var form = $(this), formID = form.data('formid'), properties;
                        if (typeof window['wpforms_' + formID] !== 'undefined' && window['wpforms_' + formID].hasOwnProperty('validate')) {
                            properties = window['wpforms_' + formID].validate;
                        } else if (typeof wpforms_validate !== 'undefined') {
                            properties = wpforms_validate;
                        } else {
                            properties = {
                                errorClass: 'wpforms-error',
                                validClass: 'wpforms-valid',
                                errorPlacement: function (error, element) {
                                    if (app.isLikertScaleField(element)) {
                                        element.closest('table').hasClass('single-row') ? element.closest('.wpforms-field').append(error) : element.closest('tr').find('th').append(error);
                                    } else if (app.isWrappedField(element)) {
                                        element.closest('.wpforms-field').append(error);
                                    } else if (app.isDateTimeField(element)) {
                                        app.dateTimeErrorPlacement(element, error);
                                    } else if (app.isFieldInColumn(element)) {
                                        element.parent().append(error);
                                    } else {
                                        error.insertAfter(element);
                                    }
                                },
                                highlight: function (element, errorClass, validClass) {
                                    var $element = $(element), $field = $element.closest('.wpforms-field'),
                                        inputName = $element.attr('name');
                                    if ('radio' === $element.attr('type') || 'checkbox' === $element.attr('type')) {
                                        $field.find('input[name="' + inputName + '"]').addClass(errorClass).removeClass(validClass);
                                    } else {
                                        $element.addClass(errorClass).removeClass(validClass);
                                    }
                                    $field.addClass('wpforms-has-error');
                                },
                                unhighlight: function (element, errorClass, validClass) {
                                    var $element = $(element), $field = $element.closest('.wpforms-field'),
                                        inputName = $element.attr('name');
                                    if ('radio' === $element.attr('type') || 'checkbox' === $element.attr('type')) {
                                        $field.find('input[name="' + inputName + '"]').addClass(validClass).removeClass(errorClass);
                                    } else {
                                        $element.addClass(validClass).removeClass(errorClass);
                                    }
                                    $field.removeClass('wpforms-has-error');
                                },
                                submitHandler: function (form) {
                                    var $form = $(form), $submit = $form.find('.wpforms-submit'),
                                        altText = $submit.data('alt-text'), recaptchaID = $submit.get(0).recaptchaID;
                                    if ($form.data('token') && 0 === $('.wpforms-token', $form).length) {
                                        $('<input type="hidden" class="wpforms-token" name="wpforms[token]" />').val($form.data('token')).appendTo($form);
                                    }
                                    $submit.prop('disabled', true);
                                    $form.find('#wpforms-field_recaptcha-error').remove();
                                    if (altText) {
                                        $submit.text(altText);
                                    }
                                    if (!app.empty(recaptchaID) || recaptchaID === 0) {
                                        grecaptcha.execute(recaptchaID).then(null, function (reason) {
                                            reason = (null === reason) ? '' : '<br>' + reason;
                                            $form.find('.wpforms-recaptcha-container').append('<label id="wpforms-field_recaptcha-error" class="wpforms-error"> ' + wpforms_settings.val_recaptcha_fail_msg + reason + '</label>');
                                            $submit.prop('disabled', false);
                                        });
                                        return false;
                                    }
                                    $('.wpforms-input-temp-name').removeAttr('name');
                                    app.formSubmit($form);
                                },
                                invalidHandler: function (event, validator) {
                                    if (typeof validator.errorList[0] !== 'undefined') {
                                        app.scrollToError($(validator.errorList[0].element));
                                    }
                                },
                                onkeyup: function (element, event) {
                                    var excludedKeys = [16, 17, 18, 20, 35, 36, 37, 38, 39, 40, 45, 144, 225];
                                    if ($(element).hasClass('wpforms-novalidate-onkeyup')) {
                                        return;
                                    }
                                    if (9 === event.which && '' === this.elementValue(element) || $.inArray(event.keyCode, excludedKeys) !== -1) {
                                        return;
                                    } else if (element.name in this.submitted || element.name in this.invalid) {
                                        this.element(element);
                                    }
                                },
                                onfocusout: function (element) {
                                    var validate = false;
                                    if ($(element).hasClass('wpforms-novalidate-onkeyup') && !element.value) {
                                        validate = true;
                                    }
                                    if (!this.checkable(element) && (element.name in this.submitted || !this.optional(element))) {
                                        validate = true;
                                    }
                                    if (validate) {
                                        this.element(element);
                                    }
                                },
                                onclick: function (element) {
                                    var validate = false, type = (element || {}).type, $el = $(element);
                                    if (['checkbox', 'radio'].indexOf(type) > -1) {
                                        if ($el.hasClass('wpforms-likert-scale-option')) {
                                            $el = $el.closest('tr');
                                        } else {
                                            $el = $el.closest('.wpforms-field');
                                        }
                                        $el.find('label.wpforms-error').remove();
                                        validate = true;
                                    }
                                    if (validate) {
                                        this.element(element);
                                    }
                                },
                            };
                        }
                        form.validate(properties);
                    });
                }
            }, isFieldInColumn(element) {
                return element.parent().hasClass('wpforms-one-half') || element.parent().hasClass('wpforms-two-fifths') || element.parent().hasClass('wpforms-one-fifth');
            }, isDateTimeField(element) {
                return element.hasClass('wpforms-timepicker') || element.hasClass('wpforms-datepicker') || (element.is('select') && element.attr('class').match(/date-month|date-day|date-year/));
            }, isWrappedField(element) {
                return 'checkbox' === element.attr('type') || 'radio' === element.attr('type') || 'range' === element.attr('type') || 'select' === element.is('select') || element.parent().hasClass('iti') || element.hasClass('wpforms-validation-group-member') || element.hasClass('choicesjs-select') || element.hasClass('wpforms-net-promoter-score-option');
            }, isLikertScaleField(element) {
                return element.hasClass('wpforms-likert-scale-option');
            }, dateTimeErrorPlacement(element, error) {
                var $wrapper = element.closest('.wpforms-field-row-block');
                if ($wrapper.length) {
                    if (!$wrapper.find('label.wpforms-error').length) {
                        $wrapper.append(error);
                    }
                } else {
                    element.closest('.wpforms-field').append(error);
                }
            }, loadDatePicker: function () {
                if (typeof $.fn.flatpickr !== 'undefined') {
                    $('.wpforms-datepicker-wrap').each(function () {
                        var element = $(this), $input = element.find('input'), form = element.closest('.wpforms-form'),
                            formID = form.data('formid'), fieldID = element.closest('.wpforms-field').data('field-id'),
                            properties;
                        if (typeof window['wpforms_' + formID + '_' + fieldID] !== 'undefined' && window['wpforms_' + formID + '_' + fieldID].hasOwnProperty('datepicker')) {
                            properties = window['wpforms_' + formID + '_' + fieldID].datepicker;
                        } else if (typeof window['wpforms_' + formID] !== 'undefined' && window['wpforms_' + formID].hasOwnProperty('datepicker')) {
                            properties = window['wpforms_' + formID].datepicker;
                        } else if (typeof wpforms_datepicker !== 'undefined') {
                            properties = wpforms_datepicker;
                        } else {
                            properties = {disableMobile: true,};
                        }
                        if (!properties.hasOwnProperty('locale') && typeof wpforms_settings !== 'undefined' && wpforms_settings.hasOwnProperty('locale')) {
                            properties.locale = wpforms_settings.locale;
                        }
                        properties.wrap = true;
                        properties.dateFormat = $input.data('date-format');
                        if ($input.data('disable-past-dates') === 1) {
                            properties.minDate = 'today';
                        }
                        var limitDays = $input.data('limit-days'),
                            weekDays = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
                        if (limitDays && limitDays !== '') {
                            limitDays = limitDays.split(',');
                            properties.disable = [function (date) {
                                var limitDay;
                                for (var i in limitDays) {
                                    limitDay = weekDays.indexOf(limitDays[i]);
                                    if (limitDay === date.getDay()) {
                                        return false;
                                    }
                                }
                                return true;
                            }];
                        }
                        properties.onChange = function (selectedDates, dateStr, instance) {
                            var display = dateStr === '' ? 'none' : 'block';
                            element.find('.wpforms-datepicker-clear').css('display', display);
                        };
                        element.flatpickr(properties);
                    });
                }
            }, loadTimePicker: function () {
                if (typeof $.fn.timepicker !== 'undefined') {
                    $('.wpforms-timepicker').each(function () {
                        var element = $(this), form = element.closest('.wpforms-form'), formID = form.data('formid'),
                            fieldID = element.closest('.wpforms-field').data('field-id'), properties;
                        if (typeof window['wpforms_' + formID + '_' + fieldID] !== 'undefined' && window['wpforms_' + formID + '_' + fieldID].hasOwnProperty('timepicker')) {
                            properties = window['wpforms_' + formID + '_' + fieldID].timepicker;
                        } else if (typeof window['wpforms_' + formID] !== 'undefined' && window['wpforms_' + formID].hasOwnProperty('timepicker')) {
                            properties = window['wpforms_' + formID].timepicker;
                        } else if (typeof wpforms_timepicker !== 'undefined') {
                            properties = wpforms_timepicker;
                        } else {
                            properties = {scrollDefault: 'now', forceRoundTime: true,};
                        }
                        element.timepicker(properties);
                    });
                }
            }, loadInputMask: function () {
                if (typeof $.fn.inputmask === 'undefined') {
                    return;
                }
                $('.wpforms-masked-input').inputmask();
            }, loadSmartPhoneField: function () {
                if (typeof $.fn.intlTelInput === 'undefined') {
                    return;
                }
                var inputOptions = {};
                if (!wpforms_settings.gdpr) {
                    inputOptions.geoIpLookup = app.currentIpToCountry;
                }
                if (wpforms_settings.gdpr) {
                    var lang = this.getFirstBrowserLanguage(),
                        countryCode = lang.indexOf('-') > -1 ? lang.split('-').pop() : '';
                }
                if (countryCode) {
                    var countryData = window.intlTelInputGlobals.getCountryData();
                    countryData = countryData.filter(function (country) {
                        return country.iso2 === countryCode.toLowerCase();
                    });
                    countryCode = countryData.length ? countryCode : '';
                }
                inputOptions.initialCountry = wpforms_settings.gdpr && countryCode ? countryCode : 'auto';
                $('.wpforms-smart-phone-field').each(function (i, el) {
                    var $el = $(el);
                    inputOptions.hiddenInput = $el.closest('.wpforms-field-phone').data('field-id');
                    inputOptions.utilsScript = wpforms_settings.wpforms_plugin_url + 'pro/assets/js/vendor/jquery.intl-tel-input-utils.js';
                    $el.intlTelInput(inputOptions);
                    $el.attr('name', 'wpf-temp-' + $el.attr('name'));
                    $el.addClass('wpforms-input-temp-name');
                    $el.on('blur input', function () {
                        if ($el.intlTelInput('isValidNumber') || !app.empty(window.WPFormsEditEntry)) {
                            $el.siblings('input[type="hidden"]').val($el.intlTelInput('getNumber'));
                        }
                    });
                });
                $('.wpforms-form').on('wpformsBeforeFormSubmit', function () {
                    $(this).find('.wpforms-smart-phone-field').trigger('input');
                });
            }, loadPayments: function () {
                $('.wpforms-payment-total').each(function (index, el) {
                    app.amountTotal(this);
                });
                if (typeof $.fn.payment !== 'undefined') {
                    $('.wpforms-field-credit-card-cardnumber').payment('formatCardNumber');
                    $('.wpforms-field-credit-card-cardcvc').payment('formatCardCVC');
                }
            }, loadMailcheck: function () {
                if (!wpforms_settings.mailcheck_enabled) {
                    return;
                }
                if (typeof $.fn.mailcheck === 'undefined') {
                    return;
                }
                if (wpforms_settings.mailcheck_domains.length > 0) {
                    Mailcheck.defaultDomains = Mailcheck.defaultDomains.concat(wpforms_settings.mailcheck_domains);
                }
                if (wpforms_settings.mailcheck_toplevel_domains.length > 0) {
                    Mailcheck.defaultTopLevelDomains = Mailcheck.defaultTopLevelDomains.concat(wpforms_settings.mailcheck_toplevel_domains);
                }
                $(document).on('blur', '.wpforms-field-email input', function () {
                    var $t = $(this), id = $t.attr('id');
                    $t.mailcheck({
                        suggested: function (el, suggestion) {
                            $('#' + id + '_suggestion').remove();
                            var sugg = '<a href="#" class="mailcheck-suggestion" data-id="' + id + '" title="' + wpforms_settings.val_email_suggestion_title + '">' + suggestion.full + '</a>';
                            sugg = wpforms_settings.val_email_suggestion.replace('{suggestion}', sugg);
                            $(el).parent().append('<label class="wpforms-error mailcheck-error" id="' + id + '_suggestion">' + sugg + '</label>');
                        }, empty: function () {
                            $('#' + id + '_suggestion').remove();
                        },
                    });
                });
                $(document).on('click', '.wpforms-field-email .mailcheck-suggestion', function (e) {
                    var $t = $(this), id = $t.attr('data-id');
                    e.preventDefault();
                    $('#' + id).val($t.text());
                    $t.parent().remove();
                });
            }, loadChoicesJS: function () {
                if (!$.isFunction(window.Choices)) {
                    return;
                }
                $('.wpforms-field-select-style-modern .choicesjs-select, .wpforms-field-payment-select .choicesjs-select').each(function (idx, el) {
                    var args = window.wpforms_choicesjs_config || {};
                    args.callbackOnInit = function () {
                        var self = this, $element = $(self.passedElement.element), $input = $(self.input.element),
                            sizeClass = $element.data('size-class');
                        $element.removeAttr('hidden').addClass(self.config.classNames.input + '--hidden');
                        if (sizeClass) {
                            $(self.containerOuter.element).addClass(sizeClass);
                        }
                        if ($element.prop('multiple')) {
                            if (self.getValue(true).length) {
                                $input.addClass(self.config.classNames.input + '--hidden');
                            }
                        }
                        $element.on('change', function () {
                            var validator;
                            if ($element.prop('multiple')) {
                                self.getValue(true).length > 0 ? $input.addClass(self.config.classNames.input + '--hidden') : $input.removeClass(self.config.classNames.input + '--hidden');
                            }
                            validator = $element.closest('form').data('validator');
                            if (!validator) {
                                return;
                            }
                            validator.element($element);
                        });
                    };
                    args.callbackOnCreateTemplates = function () {
                        var self = this, $element = $(self.passedElement.element);
                        return {
                            option: function (item) {
                                var opt = Choices.defaults.templates.option.call(this, item);
                                if ('undefined' !== typeof item.placeholder && true === item.placeholder) {
                                    opt.classList.add('placeholder');
                                }
                                if ($element.hasClass('wpforms-payment-price') && 'undefined' !== typeof item.customProperties && null !== item.customProperties) {
                                    opt.dataset.amount = item.customProperties;
                                }
                                return opt;
                            },
                        };
                    };
                    $(el).data('choicesjs', new Choices(el, args));
                });
            }, bindUIActions: function () {
                $(document).on('click', '.wpforms-page-button', function (event) {
                    event.preventDefault();
                    app.pagebreakNav(this);
                });
                $(document).on('change input', '.wpforms-payment-price', function () {
                    app.amountTotal(this, true);
                });
                $(document).on('input', '.wpforms-payment-user-input', function () {
                    var $this = $(this), amount = $this.val();
                    $this.val(amount.replace(/[^0-9.,]/g, ''));
                });
                $(document).on('focusout', '.wpforms-payment-user-input', function () {
                    var $this = $(this), amount = $this.val(), sanitized = app.amountSanitize(amount),
                        formatted = app.amountFormat(sanitized);
                    $this.val(formatted);
                });
                $(document).on('wpformsProcessConditionals', function (e, el) {
                    app.amountTotal(el, true);
                });
                $(function () {
                    $('.wpforms-field-radio .wpforms-image-choices-item input:checked').change();
                    $('.wpforms-field-payment-multiple .wpforms-image-choices-item input:checked').change();
                    $('.wpforms-field-checkbox .wpforms-image-choices-item input').change();
                    $('.wpforms-field-payment-checkbox .wpforms-image-choices-item input').change();
                });
                $('.wpforms-field-rating-item').hover(function () {
                    $(this).parent().find('.wpforms-field-rating-item').removeClass('selected hover');
                    $(this).prevAll().addBack().addClass('hover');
                }, function () {
                    $(this).parent().find('.wpforms-field-rating-item').removeClass('selected hover');
                    $(this).parent().find('input:checked').parent().prevAll().addBack().addClass('selected');
                });
                $(document).on('change', '.wpforms-field-rating-item input', function () {
                    var $this = $(this), $wrap = $this.closest('.wpforms-field-rating-items'),
                        $items = $wrap.find('.wpforms-field-rating-item');
                    $items.removeClass('hover selected');
                    $this.parent().prevAll().addBack().addClass('selected');
                });
                $(function () {
                    $('.wpforms-field-rating-item input:checked').change();
                });
                $(document).on('keypress', '.wpforms-image-choices-item label', function (event) {
                    var $this = $(this), $field = $this.closest('.wpforms-field');
                    if ($field.hasClass('wpforms-conditional-hide')) {
                        event.preventDefault();
                        return false;
                    }
                    if (13 === event.which) {
                        $('#' + $this.attr('for')).click();
                    }
                });
                if (window.document.documentMode) {
                    $(document).on('click', '.wpforms-image-choices-item img', function () {
                        $(this).closest('label').find('input').click();
                    });
                }
                $(document).on('change', '.wpforms-field-checkbox input, .wpforms-field-radio input, .wpforms-field-payment-multiple input, .wpforms-field-payment-checkbox input, .wpforms-field-gdpr-checkbox input', function (event) {
                    var $this = $(this), $field = $this.closest('.wpforms-field');
                    if ($field.hasClass('wpforms-conditional-hide')) {
                        event.preventDefault();
                        return false;
                    }
                    switch ($this.attr('type')) {
                        case'radio':
                            $this.closest('ul').find('li').removeClass('wpforms-selected').find('input[type=radio]').removeProp('checked');
                            $this.prop('checked', true).closest('li').addClass('wpforms-selected');
                            break;
                        case'checkbox':
                            if ($this.is(':checked')) {
                                $this.closest('li').addClass('wpforms-selected');
                                $this.prop('checked', true);
                            } else {
                                $this.closest('li').removeClass('wpforms-selected');
                                $this.prop('checked', false);
                            }
                            break;
                    }
                });
                $(document).on('change', '.wpforms-field-file-upload input[type=file]:not(".dropzone-input")', function () {
                    var $this = $(this),
                        $uploads = $this.closest('form.wpforms-form').find('.wpforms-field-file-upload input:not(".dropzone-input")'),
                        totalSize = 0, postMaxSize = Number(wpforms_settings.post_max_size),
                        errorMsg = '<div class="wpforms-error-container-post_max_size">' + wpforms_settings.val_post_max_size + '</div>',
                        errorCntTpl = '<div class="wpforms-error-container">{errorMsg}</span></div>',
                        $submitCnt = $this.closest('form.wpforms-form').find('.wpforms-submit-container'),
                        $submitBtn = $submitCnt.find('button.wpforms-submit'), $errorCnt = $submitCnt.prev();
                    $uploads.each(function () {
                        var $upload = $(this), i = 0, len = $upload[0].files.length;
                        for (; i < len; i++) {
                            totalSize += $upload[0].files[i].size;
                        }
                    });
                    if (totalSize > postMaxSize) {
                        totalSize = Number((totalSize / 1048576).toFixed(3));
                        postMaxSize = Number((postMaxSize / 1048576).toFixed(3));
                        errorMsg = errorMsg.replace(/{totalSize}/, totalSize).replace(/{maxSize}/, postMaxSize);
                        if ($errorCnt.hasClass('wpforms-error-container')) {
                            $errorCnt.find('.wpforms-error-container-post_max_size').remove();
                            $errorCnt.append(errorMsg);
                        } else {
                            $submitCnt.before(errorCntTpl.replace(/{errorMsg}/, errorMsg));
                        }
                        $submitBtn.prop('disabled', true);
                    } else {
                        $errorCnt.find('.wpforms-error-container-post_max_size').remove();
                        $submitBtn.prop('disabled', false);
                    }
                });
                $(document).on('change input', '.wpforms-field-number-slider input[type=range]', function (event) {
                    var hintEl = $(event.target).siblings('.wpforms-field-number-slider-hint');
                    hintEl.html(hintEl.data('hint').replace('{value}', '<b>' + event.target.value + '</b>'));
                });
                $(document).on('keydown', '.wpforms-form input', function (e) {
                    if (e.keyCode !== 13) {
                        return;
                    }
                    var $t = $(this), $page = $t.closest('.wpforms-page');
                    if ($page.length === 0) {
                        return;
                    }
                    if (['text', 'tel', 'number', 'email', 'url', 'radio', 'checkbox'].indexOf($t.attr('type')) < 0) {
                        return;
                    }
                    if ($t.hasClass('wpforms-datepicker')) {
                        $t.flatpickr('close');
                    }
                    e.preventDefault();
                    if ($page.hasClass('last')) {
                        $page.closest('.wpforms-form').find('.wpforms-submit').click();
                        return;
                    }
                    $page.find('.wpforms-page-next').click();
                });
                $(document).on('keypress', '.wpforms-field-number input', function (e) {
                    return /^[-0-9.]+$/.test(String.fromCharCode(e.keyCode || e.which));
                });
            }, scrollToError: function ($el) {
                if ($el.length === 0) {
                    return;
                }
                var $field = $el.find('.wpforms-field.wpforms-has-error');
                if ($field.length === 0) {
                    $field = $el.closest('.wpforms-field');
                }
                if ($field.length === 0) {
                    return;
                }
                var offset = $field.offset();
                if (typeof offset === 'undefined') {
                    return;
                }
                app.animateScrollTop(offset.top - 75, 750).done(function () {
                    var $error = $field.find('.wpforms-error').first();
                    if (app.isFunction($error.focus)) {
                        $error.focus();
                    }
                });
            }, pagebreakNav: function (el) {
                var $this = $(el), valid = true, action = $this.data('action'), page = $this.data('page'), page2 = page,
                    next = page + 1, prev = page - 1, formID = $this.data('formid'),
                    $form = $this.closest('.wpforms-form'), $page = $form.find('.wpforms-page-' + page),
                    $submit = $form.find('.wpforms-submit-container'),
                    $indicator = $form.find('.wpforms-page-indicator'),
                    $reCAPTCHA = $form.find('.wpforms-recaptcha-container'), pageScroll = false;
                if (false === window.wpforms_pageScroll) {
                    pageScroll = false;
                } else if (!app.empty(window.wpform_pageScroll)) {
                    pageScroll = window.wpform_pageScroll;
                } else {
                    pageScroll = $indicator.data('scroll') !== 0 ? 75 : false;
                }
                if ('next' === action) {
                    if (typeof $.fn.validate !== 'undefined') {
                        $page.find(':input').each(function (index, el) {
                            if (!$(el).attr('name')) {
                                return;
                            }
                            if (!$(el).valid()) {
                                valid = false;
                            }
                        });
                        app.scrollToError($page);
                    }
                    if (valid) {
                        page2 = next;
                        $page.hide();
                        var $nextPage = $form.find('.wpforms-page-' + next);
                        $nextPage.show();
                        if ($nextPage.hasClass('last')) {
                            $reCAPTCHA.show();
                            $submit.show();
                        }
                        if (pageScroll) {
                            app.animateScrollTop($form.offset().top - pageScroll, 750);
                        }
                        $this.trigger('wpformsPageChange', [page2, $form]);
                    }
                } else if ('prev' === action) {
                    page2 = prev;
                    $page.hide();
                    $form.find('.wpforms-page-' + prev).show();
                    $reCAPTCHA.hide();
                    $submit.hide();
                    if (pageScroll) {
                        app.animateScrollTop($form.offset().top - pageScroll);
                    }
                    $this.trigger('wpformsPageChange', [page2, $form]);
                }
                if ($indicator) {
                    var theme = $indicator.data('indicator'), color = $indicator.data('indicator-color');
                    if ('connector' === theme || 'circles' === theme) {
                        $indicator.find('.wpforms-page-indicator-page').removeClass('active');
                        $indicator.find('.wpforms-page-indicator-page-' + page2).addClass('active');
                        $indicator.find('.wpforms-page-indicator-page-number').removeAttr('style');
                        $indicator.find('.active .wpforms-page-indicator-page-number').css('background-color', color);
                        if ('connector' === theme) {
                            $indicator.find('.wpforms-page-indicator-page-triangle').removeAttr('style');
                            $indicator.find('.active .wpforms-page-indicator-page-triangle').css('border-top-color', color);
                        }
                    } else if ('progress' === theme) {
                        var $pageTitle = $indicator.find('.wpforms-page-indicator-page-title'),
                            $pageSep = $indicator.find('.wpforms-page-indicator-page-title-sep'),
                            totalPages = $form.find('.wpforms-page').length, width = (page2 / totalPages) * 100;
                        $indicator.find('.wpforms-page-indicator-page-progress').css('width', width + '%');
                        $indicator.find('.wpforms-page-indicator-steps-current').text(page2);
                        if ($pageTitle.data('page-' + page2 + '-title')) {
                            $pageTitle.css('display', 'inline').text($pageTitle.data('page-' + page2 + '-title'));
                            $pageSep.css('display', 'inline');
                        } else {
                            $pageTitle.css('display', 'none');
                            $pageSep.css('display', 'none');
                        }
                    }
                }
            }, bindOptinMonster: function () {
                document.addEventListener('om.Campaign.load', function (event) {
                    app.ready();
                    app.optinMonsterRecaptchaReset(event.detail.Campaign.data.id);
                });
                $(document).on('OptinMonsterOnShow', function (event, data, object) {
                    app.ready();
                    app.optinMonsterRecaptchaReset(data.optin);
                });
            }, optinMonsterRecaptchaReset: function (optinId) {
                var $form = $('#om-' + optinId).find('.wpforms-form'),
                    $recaptchaContainer = $form.find('.wpforms-recaptcha-container'),
                    $recaptcha = $form.find('.g-recaptcha'), recaptchaSiteKey = $recaptcha.attr('data-sitekey'),
                    recaptchaID = 'recaptcha-' + Date.now();
                if ($form.length && $recaptcha.length) {
                    $recaptcha.remove();
                    $recaptchaContainer.prepend('<div class="g-recaptcha" id="' + recaptchaID + '" data-sitekey="' + recaptchaSiteKey + '"></div>');
                    grecaptcha.render(recaptchaID, {
                        sitekey: recaptchaSiteKey, callback: function () {
                            wpformsRecaptchaCallback($('#' + recaptchaID));
                        },
                    });
                }
            }, amountTotal: function (el, validate) {
                validate = validate || false;
                var $form = $(el).closest('.wpforms-form'), total = 0, totalFormatted, totalFormattedSymbol,
                    currency = app.getCurrency();
                $('.wpforms-payment-price', $form).each(function (index, el) {
                    var amount = 0, $this = $(this);
                    if ($this.closest('.wpforms-field-payment-single').hasClass('wpforms-conditional-hide')) {
                        return;
                    }
                    if ('text' === $this.attr('type') || 'hidden' === $this.attr('type')) {
                        amount = $this.val();
                    } else if (('radio' === $this.attr('type') || 'checkbox' === $this.attr('type')) && $this.is(':checked')) {
                        amount = $this.data('amount');
                    } else if ($this.is('select') && $this.find('option:selected').length > 0) {
                        amount = $this.find('option:selected').data('amount');
                    }
                    if (!app.empty(amount)) {
                        amount = app.amountSanitize(amount);
                        total = Number(total) + Number(amount);
                    }
                });
                totalFormatted = app.amountFormat(total);
                if ('left' === currency.symbol_pos) {
                    totalFormattedSymbol = currency.symbol + ' ' + totalFormatted;
                } else {
                    totalFormattedSymbol = totalFormatted + ' ' + currency.symbol;
                }
                $form.find('.wpforms-payment-total').each(function (index, el) {
                    if ('hidden' === $(this).attr('type') || 'text' === $(this).attr('type')) {
                        $(this).val(totalFormattedSymbol);
                        if ('text' === $(this).attr('type') && validate && $form.data('validator')) {
                            $(this).valid();
                        }
                    } else {
                        $(this).text(totalFormattedSymbol);
                    }
                });
            }, amountSanitize: function (amount) {
                var currency = app.getCurrency();
                amount = amount.toString().replace(/[^0-9.,]/g, '');
                if (',' === currency.decimal_sep && (amount.indexOf(currency.decimal_sep) !== -1)) {
                    if ('.' === currency.thousands_sep && amount.indexOf(currency.thousands_sep) !== -1) {
                        amount = amount.replace(currency.thousands_sep, '');
                    } else if ('' === currency.thousands_sep && amount.indexOf('.') !== -1) {
                        amount = amount.replace('.', '');
                    }
                    amount = amount.replace(currency.decimal_sep, '.');
                } else if (',' === currency.thousands_sep && (amount.indexOf(currency.thousands_sep) !== -1)) {
                    amount = amount.replace(currency.thousands_sep, '');
                }
                return app.numberFormat(amount, 2, '.', '');
            }, amountFormat: function (amount) {
                var currency = app.getCurrency();
                amount = String(amount);
                if (',' === currency.decimal_sep && (amount.indexOf(currency.decimal_sep) !== -1)) {
                    var sepFound = amount.indexOf(currency.decimal_sep), whole = amount.substr(0, sepFound),
                        part = amount.substr(sepFound + 1, amount.strlen - 1);
                    amount = whole + '.' + part;
                }
                if (',' === currency.thousands_sep && (amount.indexOf(currency.thousands_sep) !== -1)) {
                    amount = amount.replace(',', '');
                }
                if (app.empty(amount)) {
                    amount = 0;
                }
                return app.numberFormat(amount, 2, currency.decimal_sep, currency.thousands_sep);
            }, getCurrency: function () {
                var currency = {code: 'USD', thousands_sep: ',', decimal_sep: '.', symbol: '$', symbol_pos: 'left',};
                if (typeof wpforms_settings.currency_code !== 'undefined') {
                    currency.code = wpforms_settings.currency_code;
                }
                if (typeof wpforms_settings.currency_thousands !== 'undefined') {
                    currency.thousands_sep = wpforms_settings.currency_thousands;
                }
                if (typeof wpforms_settings.currency_decimal !== 'undefined') {
                    currency.decimal_sep = wpforms_settings.currency_decimal;
                }
                if (typeof wpforms_settings.currency_symbol !== 'undefined') {
                    currency.symbol = wpforms_settings.currency_symbol;
                }
                if (typeof wpforms_settings.currency_symbol_pos !== 'undefined') {
                    currency.symbol_pos = wpforms_settings.currency_symbol_pos;
                }
                return currency;
            }, numberFormat: function (number, decimals, decimalSep, thousandsSep) {
                number = (number + '').replace(/[^0-9+\-Ee.]/g, '');
                var n = !isFinite(+number) ? 0 : +number;
                var prec = !isFinite(+decimals) ? 0 : Math.abs(decimals);
                var sep = ('undefined' === typeof thousandsSep) ? ',' : thousandsSep;
                var dec = ('undefined' === typeof decimalSep) ? '.' : decimalSep;
                var s;
                var toFixedFix = function (n, prec) {
                    var k = Math.pow(10, prec);
                    return '' + (Math.round(n * k) / k).toFixed(prec);
                };
                s = (prec ? toFixedFix(n, prec) : '' + Math.round(n)).split('.');
                if (s[0].length > 3) {
                    s[0] = s[0].replace(/\B(?=(?:\d{3})+(?!\d))/g, sep);
                }
                if ((s[1] || '').length < prec) {
                    s[1] = s[1] || '';
                    s[1] += new Array(prec - s[1].length + 1).join('0');
                }
                return s.join(dec);
            }, empty: function (mixedVar) {
                var undef;
                var key;
                var i;
                var len;
                var emptyValues = [undef, null, false, 0, '', '0'];
                for (i = 0, len = emptyValues.length; i < len; i++) {
                    if (mixedVar === emptyValues[i]) {
                        return true;
                    }
                }
                if ('object' === typeof mixedVar) {
                    for (key in mixedVar) {
                        if (mixedVar.hasOwnProperty(key)) {
                            return false;
                        }
                    }
                    return true;
                }
                return false;
            }, setUserIndentifier: function () {
                if (((!window.hasRequiredConsent && typeof wpforms_settings !== 'undefined' && wpforms_settings.uuid_cookie) || (window.hasRequiredConsent && window.hasRequiredConsent())) && !app.getCookie('_wpfuuid')) {
                    var s = new Array(36), hexDigits = '0123456789abcdef', uuid;
                    for (var i = 0; i < 36; i++) {
                        s[i] = hexDigits.substr(Math.floor(Math.random() * 0x10), 1);
                    }
                    s[14] = '4';
                    s[19] = hexDigits.substr((s[19] & 0x3) | 0x8, 1);
                    s[8] = s[13] = s[18] = s[23] = '-';
                    uuid = s.join('');
                    app.createCookie('_wpfuuid', uuid, 3999);
                }
            }, createCookie: function (name, value, days) {
                var expires = '';
                if (days) {
                    if ('-1' === days) {
                        expires = '';
                    } else {
                        var date = new Date();
                        date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
                        expires = '; expires=' + date.toGMTString();
                    }
                } else {
                    expires = '; expires=Thu, 01 Jan 1970 00:00:01 GMT';
                }
                document.cookie = name + '=' + value + expires + '; path=/; samesite=strict';
            }, getCookie: function (name) {
                var nameEQ = name + '=', ca = document.cookie.split(';');
                for (var i = 0; i < ca.length; i++) {
                    var c = ca[i];
                    while (' ' === c.charAt(0)) {
                        c = c.substring(1, c.length);
                    }
                    if (0 === c.indexOf(nameEQ)) {
                        return c.substring(nameEQ.length, c.length);
                    }
                }
                return null;
            }, removeCookie: function (name) {
                app.createCookie(name, '', -1);
            }, getFirstBrowserLanguage: function () {
                var nav = window.navigator,
                    browserLanguagePropertyKeys = ['language', 'browserLanguage', 'systemLanguage', 'userLanguage'], i,
                    language;
                if (Array.isArray(nav.languages)) {
                    for (i = 0; i < nav.languages.length; i++) {
                        language = nav.languages[i];
                        if (language && language.length) {
                            return language;
                        }
                    }
                }
                for (i = 0; i < browserLanguagePropertyKeys.length; i++) {
                    language = nav[browserLanguagePropertyKeys[i]];
                    if (language && language.length) {
                        return language;
                    }
                }
                return '';
            }, currentIpToCountry: function (callback) {
                var fallback = function () {
                    $.get('https://ipapi.co/jsonp', function () {
                    }, 'jsonp').always(function (resp) {
                        var countryCode = (resp && resp.country) ? resp.country : '';
                        if (!countryCode) {
                            var lang = app.getFirstBrowserLanguage();
                            countryCode = lang.indexOf('-') > -1 ? lang.split('-').pop() : '';
                        }
                        callback(countryCode);
                    });
                };
                $.get('https://geo.wpforms.com/v3/geolocate/json').done(function (resp) {
                    if (resp && resp.country_iso) {
                        callback(resp.country_iso);
                    } else {
                        fallback();
                    }
                }).fail(function (resp) {
                    fallback();
                });
            }, formSubmit: function ($form) {
                $form.trigger('wpformsBeforeFormSubmit');
                if ($form.hasClass('wpforms-ajax-form') && typeof FormData !== 'undefined') {
                    app.formSubmitAjax($form);
                } else {
                    app.formSubmitNormal($form);
                }
            }, formSubmitNormal: function ($form) {
                if (!$form.length) {
                    return;
                }
                var $submit = $form.find('.wpforms-submit'), recaptchaID = $submit.get(0).recaptchaID;
                if (!app.empty(recaptchaID) || recaptchaID === 0) {
                    $submit.get(0).recaptchaID = false;
                }
                $form.get(0).submit();
            }, resetFormRecaptcha: function ($form) {
                if (!$form || !$form.length) {
                    return;
                }
                if (typeof grecaptcha === 'undefined') {
                    return;
                }
                var recaptchaID;
                recaptchaID = $form.find('.wpforms-submit').get(0).recaptchaID;
                if (app.empty(recaptchaID) && recaptchaID !== 0) {
                    recaptchaID = $form.find('.g-recaptcha').data('recaptcha-id');
                }
                if (!app.empty(recaptchaID) || recaptchaID === 0) {
                    grecaptcha.reset(recaptchaID);
                }
            }, consoleLogAjaxError: function (error) {
                if (error) {
                    console.error('WPForms AJAX submit error:\n%imaews', error);
                } else {
                    console.error('WPForms AJAX submit error');
                }
            }, displayFormAjaxErrors: function ($form, errors) {
                if ('string' === typeof errors) {
                    app.displayFormAjaxGeneralErrors($form, errors);
                    return;
                }
                errors = errors && ('errors' in errors) ? errors.errors : null;
                if (app.empty(errors) || (app.empty(errors.general) && app.empty(errors.field))) {
                    app.consoleLogAjaxError();
                    return;
                }
                if (!app.empty(errors.general)) {
                    app.displayFormAjaxGeneralErrors($form, errors.general);
                }
                if (!app.empty(errors.field)) {
                    app.displayFormAjaxFieldErrors($form, errors.field);
                }
            }, displayFormAjaxGeneralErrors: function ($form, errors) {
                if (!$form || !$form.length) {
                    return;
                }
                if (app.empty(errors)) {
                    return;
                }
                if ('string' === typeof errors) {
                    $form.find('.wpforms-submit-container').before('<div class="wpforms-error-container">' + errors + '</div>');
                    return;
                }
                $.each(errors, function (type, html) {
                    switch (type) {
                        case'header':
                            $form.prepend(html);
                            break;
                        case'footer':
                            $form.find('.wpforms-submit-container').before(html);
                            break;
                        case'recaptcha':
                            $form.find('.wpforms-recaptcha-container').append(html);
                            break;
                    }
                });
            }, clearFormAjaxGeneralErrors: function ($form) {
                $form.find('.wpforms-error-container').remove();
                $form.find('#wpforms-field_recaptcha-error').remove();
            }, displayFormAjaxFieldErrors: function ($form, errors) {
                if (!$form || !$form.length) {
                    return;
                }
                if (app.empty(errors)) {
                    return;
                }
                var validator = $form.data('validator');
                if (!validator) {
                    return;
                }
                validator.showErrors(errors);
                validator.focusInvalid();
            }, formSubmitAjax: function ($form) {
                if (!$form.length) {
                    return $.Deferred().reject();
                }
                var $container = $form.closest('.wpforms-container'), $spinner = $form.find('.wpforms-submit-spinner'),
                    $confirmationScroll, formData, args;
                $container.css('opacity', 0.6);
                $spinner.show();
                app.clearFormAjaxGeneralErrors($form);
                formData = new FormData($form.get(0));
                formData.append('action', 'wpforms_submit');
                formData.append('page_url', window.location.href);
                args = {
                    type: 'post',
                    dataType: 'json',
                    url: wpforms_settings.ajaxurl,
                    data: formData,
                    cache: false,
                    contentType: false,
                    processData: false,
                };
                args.success = function (json) {
                    if (!json) {
                        app.consoleLogAjaxError();
                        return;
                    }
                    if (json.data && json.data.action_required) {
                        $form.trigger('wpformsAjaxSubmitActionRequired', json);
                        return;
                    }
                    if (!json.success) {
                        app.resetFormRecaptcha($form);
                        app.displayFormAjaxErrors($form, json.data);
                        $form.trigger('wpformsAjaxSubmitFailed', json);
                        return;
                    }
                    $form.trigger('wpformsAjaxSubmitSuccess', json);
                    if (!json.data) {
                        return;
                    }
                    if (json.data.redirect_url) {
                        $form.trigger('wpformsAjaxSubmitBeforeRedirect', json);
                        window.location = json.data.redirect_url;
                        return;
                    }
                    if (json.data.confirmation) {
                        $container.html(json.data.confirmation);
                        $confirmationScroll = $container.find('div.wpforms-confirmation-scroll');
                        if ($confirmationScroll.length) {
                            app.animateScrollTop($confirmationScroll.offset().top - 100);
                        }
                    }
                };
                args.error = function (jqHXR, textStatus, error) {
                    app.consoleLogAjaxError(error);
                    $form.trigger('wpformsAjaxSubmitError', [jqHXR, textStatus, error]);
                };
                args.complete = function (jqHXR, textStatus) {
                    if (jqHXR.responseJSON && jqHXR.responseJSON.data && jqHXR.responseJSON.data.action_required) {
                        return;
                    }
                    var $submit = $form.find('.wpforms-submit'), submitText = $submit.data('submit-text');
                    if (submitText) {
                        $submit.text(submitText);
                    }
                    $submit.prop('disabled', false);
                    $container.css('opacity', '');
                    $spinner.hide();
                    $form.trigger('wpformsAjaxSubmitCompleted', [jqHXR, textStatus]);
                };
                $form.trigger('wpformsAjaxBeforeSubmit');
                return $.ajax(args);
            }, animateScrollTop: function (position, duration, complete) {
                duration = duration || 1000;
                complete = app.isFunction(complete) ? complete : function () {
                };
                return $('html, body').animate({scrollTop: parseInt(position, 10)}, {
                    duration: duration,
                    complete: complete
                }).promise();
            }, isFunction: function (object) {
                return !!(object && object.constructor && object.call && object.apply);
            },
        };
        return app;
    }(document, window, jQuery));
    wpforms.init()
} catch (e) {
    console.log(e)
}