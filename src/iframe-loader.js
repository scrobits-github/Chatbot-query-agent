(function () {
    // Config
    // const CHATBOT_URL = 'http://localhost:5173/chatbot.html'; // For local dev
    const CHATBOT_URL = 'https://chatbot-ui-chi-beryl.vercel.app/chatbot.html'; // Production URL - catch 22, update this after deploy or make dynamic based on script src?
    // Ideally we infer the base URL from the script src so it works in both dev and prod
    const scriptTag = document.currentScript;
    const scriptSrc = scriptTag ? scriptTag.src : '';
    const baseUrl = scriptSrc ? new URL(scriptSrc).origin : 'https://chatbot-ui-chi-beryl.vercel.app';

    const IFRAME_URL = `${baseUrl}/chatbot.html`;

    const apiUrl = scriptTag.getAttribute('api_url') || '';

    // Create iframe
    const iframe = document.createElement('iframe');
    iframe.src = `${IFRAME_URL}?api_url=${encodeURIComponent(apiUrl)}`;

    // Styles for the iframe to float over the page
    Object.assign(iframe.style, {
        position: 'fixed',
        bottom: '20px',
        right: '25px', // Matching the React component's positioning approximately
        width: '450px', // Enough for the chat window + button
        height: '600px', // Enough for the chat window + button
        border: 'none',
        zIndex: '999999',
        background: 'transparent',
        pointerEvents: 'none', // Let clicks pass through when closed (we'll toggle this)
        transition: 'all 0.3s ease'
    });

    document.body.appendChild(iframe);

    // Communication with the iframe
    window.addEventListener('message', function (event) {
        if (event.origin !== baseUrl) return;

        // We can handle resize logic here if the iframe sends its size
        // For now, we just keep the iframe large enough to contain the open state
        // but pass-through clicks when it's "closed". 
        // Wait... if pointer-events is none, we can't click the open button inside the iframe!

        // Better approach: 
        // The iframe should be small (just the button size) when closed, 
        // and large when open.

        if (event.data.type === 'CHATBOT_RESIZE') {
            if (event.data.isOpen) {
                iframe.style.width = '400px';
                iframe.style.height = '600px';
                iframe.style.pointerEvents = 'auto';
            } else {
                iframe.style.width = '80px';
                iframe.style.height = '80px';
                iframe.style.pointerEvents = 'auto';
            }
        }
    });

    // Initial state - small button only
    iframe.style.width = '80px';
    iframe.style.height = '80px';
    iframe.style.pointerEvents = 'auto';

})();
