(function loadEmojiPicker() {
  if (!customElements.get('emoji-picker')) {
    import('https://cdn.jsdelivr.net/npm/emoji-picker-element@^1/index.js')
      .catch(err => console.error('❌ Error al cargar Emoji Picker:', err));
  }
})();

function editorEmojiPicker(textareaId) {
    const textarea = document.getElementById(textareaId);
    if (!textarea || textarea.dataset.initialized === 'true') return;

    textarea.dataset.initialized = 'true';

    const container = document.createElement('div');
    container.className = 'whatsapp-editor-container';
    textarea.parentNode.insertBefore(container, textarea);
    container.appendChild(textarea);

    textarea.classList.add('form-control');
    textarea.style.paddingBottom = '3rem';

    const toolbar = document.createElement('div');
    toolbar.className = 'editor-toolbar-minimal';

    const botones = [
        { icon: 'fa-bold', wrap: '*', title: 'Negrita' },
        { icon: 'fa-italic', wrap: '_', title: 'Cursiva' },
        { icon: 'fa-underline', wrap: '~', title: 'Tachado' },
    ];

    botones.forEach(b => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn-icon';
        btn.title = b.title;
        btn.innerHTML = `<i class="fa ${b.icon}"></i>`;
        btn.onclick = () => formatearTextoWhatsApp(textarea, b.wrap);
        toolbar.appendChild(btn);
    });

    const emojiBtn = document.createElement('button');
    emojiBtn.type = 'button';
    emojiBtn.className = 'btn-icon';
    emojiBtn.title = 'Emoji';
    emojiBtn.innerHTML = '<i class="fa fa-smile"></i>';

    const emojiPicker = document.createElement('emoji-picker');
    emojiPicker.className = 'emoji-picker-popup light';
    emojiPicker.style.display = 'none';

    emojiBtn.onclick = () => {
        emojiPicker.style.display = emojiPicker.style.display === 'none' ? 'block' : 'none';
    };

    emojiPicker.addEventListener('emoji-click', e => {
        const emoji = e.detail.unicode;
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        textarea.setRangeText(emoji, start, end, 'end');
        textarea.focus();
        emojiPicker.style.display = 'none';
    });

    toolbar.appendChild(emojiBtn);
    container.appendChild(toolbar);
    container.appendChild(emojiPicker);
}

function formatearTextoWhatsApp(textarea, wrapChar) {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const texto = textarea.value.substring(start, end);
    const nuevo = `${wrapChar}${texto}${wrapChar}`;
    textarea.setRangeText(nuevo, start, end, 'end');
    textarea.focus();
}