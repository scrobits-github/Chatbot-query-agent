(function () {
    // Infer the base URL from the script's own src, so it works in both dev and prod
    const scriptTag = document.currentScript;
    const scriptSrc = scriptTag ? scriptTag.src : '';
    const scriptUrl = new URL(scriptSrc);
    const basePath = scriptUrl.pathname.substring(0, scriptUrl.pathname.lastIndexOf('/'));
    const baseOrigin = scriptUrl.origin;
    const IFRAME_URL = `${baseOrigin}${basePath}/chatbot.html`;

    const apiUrl = scriptTag.getAttribute('api_url') || '';

    // Create iframe
    const iframe = document.createElement('iframe');
    iframe.src = `${IFRAME_URL}?api_url=${encodeURIComponent(apiUrl)}`;
    iframe.setAttribute('allowtransparency', 'true');
    iframe.setAttribute('allow', 'clipboard-write');
    iframe.title = 'Chatbot Widget';

    // Styles for the iframe — starts as a small button-sized frame
    Object.assign(iframe.style, {
        position: 'fixed',
        bottom: '20px',
        right: '20px',
        width: '70px',
        height: '70px',
        border: 'none',
        zIndex: '999999',
        background: 'transparent',
        colorScheme: 'none',
        transition: 'width 0.3s ease, height 0.3s ease',
        overflow: 'hidden',
    });

    document.body.appendChild(iframe);

    // Listen for resize messages from the chatbot inside the iframe
    window.addEventListener('message', function (event) {
        if (event.origin !== baseOrigin) return;

        if (event.data.type === 'CHATBOT_RESIZE') {
            if (event.data.isOpen) {
                iframe.style.width = '400px';
                iframe.style.height = '620px';
            } else {
                iframe.style.width = '70px';
                iframe.style.height = '70px';
            }
        }
    });
})();
