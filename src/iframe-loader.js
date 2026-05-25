(function () {
    // Infer the base URL from the script's own src, so it works in both dev and prod
    const scriptTag = document.currentScript;
    const scriptSrc = scriptTag ? scriptTag.src : '';
    const scriptUrl = new URL(scriptSrc);
    const basePath = scriptUrl.pathname.substring(0, scriptUrl.pathname.lastIndexOf('/'));
    const baseOrigin = scriptUrl.origin;
    const IFRAME_URL = `${baseOrigin}${basePath}/chatbot.html`;

    const apiUrl = scriptTag.getAttribute('api_url') || '';
    const token = localStorage.getItem('infiiot_token') || '';

    // Create iframe
    const iframe = document.createElement('iframe');
    const parentOrigin = window.location.origin;
    iframe.src = `${IFRAME_URL}?api_url=${encodeURIComponent(apiUrl)}&token=${encodeURIComponent(token)}&parent_origin=${encodeURIComponent(parentOrigin)}`;
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

    // Responsive sizing helper
    function getOpenSize() {
        const vw = window.innerWidth;
        if (vw <= 480) {
            // Mobile: floating chat window, not full screen
            return {
                width: 'calc(100vw - 32px)',
                height: '60vh',
                right: '16px',
                bottom: '16px'
            };
        } else if (vw <= 768) {
            // Tablet
            return { width: '380px', height: '580px', right: '20px', bottom: '20px' };
        } else {
            // Desktop
            return { width: '400px', height: '620px', right: '20px', bottom: '20px' };
        }
    }

    let isOpen = false;

    // Listen for messages from the chatbot inside the iframe
    window.addEventListener('message', function (event) {
        if (event.origin !== baseOrigin) return;

        if (event.data.type === 'CHATBOT_RESIZE') {
            isOpen = event.data.isOpen;
            if (isOpen) {
                const size = getOpenSize();
                iframe.style.width = size.width;
                iframe.style.height = size.height;
                iframe.style.right = size.right;
                iframe.style.bottom = size.bottom;
            } else {
                iframe.style.width = '70px';
                iframe.style.height = '70px';
                iframe.style.right = '20px';
                iframe.style.bottom = '20px';
            }
        } else if (event.data.type === 'CHATBOT_REDIRECT') {
            console.log("Redirecting parent page to:", event.data.url);
            window.location.href = event.data.url;
        }
    });

    // Re-adapt when the browser window resizes
    window.addEventListener('resize', function () {
        if (isOpen) {
            const size = getOpenSize();
            iframe.style.width = size.width;
            iframe.style.height = size.height;
            iframe.style.right = size.right;
            iframe.style.bottom = size.bottom;
        }
    });
})();
