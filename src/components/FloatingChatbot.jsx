import React, { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const API_URL =
  new URLSearchParams(window.location.search).get("api_url") ||
  window.CHATBOT_API_URL ||
  document.currentScript?.getAttribute("api_url") ||
  import.meta.env.VITE_API_BASE_URL ||
  "http://localhost:8001";

const AUTH_TOKEN =
  new URLSearchParams(window.location.search).get("token") || "";

const PARENT_ORIGIN =
  new URLSearchParams(window.location.search).get("parent_origin") || "http://127.0.0.1:8000";

const FloatingChatbot = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState([
    { sender: "bot", text: "Welcome to InfiIoT" },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef(null);

  // WebSocket escalation state
  const [isEscalated, setIsEscalated] = useState(false);

  // Pending redirection URL state
  const [pendingRedirectUrl, setPendingRedirectUrl] = useState(null);

  const wsRef = useRef(null);

  const toggleChat = () => {
    const newState = !isOpen;
    setIsOpen(newState);
    // Send message to parent iframe loader to resize
    window.parent.postMessage({ type: 'CHATBOT_RESIZE', isOpen: newState }, '*');
  };

  const closeChat = () => {
    setIsOpen(false);
    window.parent.postMessage({ type: 'CHATBOT_RESIZE', isOpen: false }, '*');
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Cleanup WebSocket on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  // Connect to WebSocket for escalation
  const connectWebSocket = (escId) => {
    const baseUrl = API_URL.replace(/^https?:\/\//, "").replace(/\/$/, "");
    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProtocol}//${baseUrl}/ws/escalation/${escId}/user`;

    console.log("Connecting to WebSocket:", wsUrl);
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log("WebSocket connected");
      setMessages((prev) => [
        ...prev,
        {
          sender: "system",
          text: "Connecting you to the human assistant… please wait.",
        },
      ]);
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      console.log("WebSocket message:", data);

      if (data.type === "message" && data.role === "admin") {
        // Message from admin
        setMessages((prev) => [
          ...prev,
          {
            sender: "admin",
            text: data.message,
          },
        ]);
      } else if (data.type === "system") {
        // System notification (admin connected/disconnected)
        setMessages((prev) => [
          ...prev,
          {
            sender: "system",
            text: `${data.message}`,
          },
        ]);
      }
      // type === "message_sent" is just confirmation, no need to display
    };

    ws.onclose = () => {
      console.log("WebSocket closed");
      setMessages((prev) => [
        ...prev,
        {
          sender: "system",
          text: "This chat session has ended. I’m here whenever you need help again.",
        },
      ]);
      setIsEscalated(false);

    };

    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
      setMessages((prev) => [
        ...prev,
        {
          sender: "system",
          text: "❌ Connection error. Please try again.",
        },
      ]);
    };

    wsRef.current = ws;
  };

  const sendMessage = async () => {
    if (!input.trim()) return;

    const userMsgText = input.trim().toLowerCase();

    // Intercept yes/no locally if there is a pending redirection URL
    if (pendingRedirectUrl && (userMsgText === "yes" || userMsgText === "sure" || userMsgText === "ok" || userMsgText === "confirm" || userMsgText === "proceed" || userMsgText === "yees" || userMsgText === "ho")) {
      const userMessage = { sender: "user", text: input };
      setMessages((prev) => [...prev, userMessage]);
      setInput("");

      // Extract the pending target URL and clear state immediately
      const targetUrl = pendingRedirectUrl;
      setPendingRedirectUrl(null);

      // Append bot local redirecting response
      setMessages((prev) => [...prev, { sender: "bot", text: "Great! Redirecting you to your new dashboard now..." }]);

      // Perform redirection safely and securely across origins!
      setTimeout(() => {
        try {
          // 1. Tell parent iframe loader to redirect
          window.parent.postMessage({ type: 'CHATBOT_REDIRECT', url: targetUrl }, '*');
          
          // 2. Fallback direct browser-level parent frame redirection
          window.open(targetUrl, "_parent");
        } catch (err) {
          console.error("Redirection failed, fallback to location change:", err);
          window.location.href = targetUrl;
        }
      }, 1000);
      return;
    }

    if (pendingRedirectUrl && (userMsgText === "no" || userMsgText === "cancel" || userMsgText === "naka" || userMsgText === "nako")) {
      const userMessage = { sender: "user", text: input };
      setMessages((prev) => [...prev, userMessage]);
      setInput("");
      setPendingRedirectUrl(null);

      setMessages((prev) => [...prev, { sender: "bot", text: "Alright! Let me know if you need anything else." }]);
      return;
    }

    const userMessage = { sender: "user", text: input };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");

    // If escalated, send via WebSocket
    if (isEscalated && wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ message: userMessage.text }));
      return;
    }

    // Otherwise, use normal HTTP API
    setIsLoading(true);

    try {
      const headers = { "Content-Type": "application/json" };
      if (AUTH_TOKEN) {
        headers["Authorization"] = `Bearer ${AUTH_TOKEN}`;
        headers["token"] = AUTH_TOKEN;
      }

      const res = await fetch(`${API_URL.replace(/\/$/, "")}/chatbot`, {
        method: "POST",
        headers: headers,
        body: JSON.stringify({ user_message: userMessage.text }),
      });

      const data = await res.json();

      // Check if escalation is triggered
      if (data.escalation_required && data.escalation_id) {

        setIsEscalated(true);

        // Add the AI's last message before escalation
        setMessages((prev) => [
          ...prev,
          { sender: "bot", text: data.response },
        ]);

        // Connect to WebSocket
        connectWebSocket(data.escalation_id);
      } else {
        // Normal flow
        const botMessage = { sender: "bot", text: data.response };
        setMessages((prev) => [...prev, botMessage]);

        // Auto-detect newly created dashboard if URL pattern matches
        const redirectMatch = data.response.match(/\/dashboard\/\?dashboard_id=(\d+)/);
        if (redirectMatch) {
          const dashboardId = redirectMatch[1];
          const targetUrl = `${PARENT_ORIGIN}/dashboard/?dashboard_id=${dashboardId}`;
          console.log("Detected dashboard redirection link. Storing pending redirect URL:", targetUrl);
          setPendingRedirectUrl(targetUrl);
        }
      }
    } catch (error) {
      console.error("Error:", error);
      setMessages((prev) => [
        ...prev,
        { sender: "bot", text: "I am facing some technical issues at the moment please visit after sometime" },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // Get message styling based on sender
  const getMessageStyle = (sender) => {
    switch (sender) {
      case "user":
        return "bg-orange-500 text-white self-end rounded-br-none";
      case "admin":
        return "bg-green-500 text-white self-start rounded-bl-none";
      case "system":
        return "bg-yellow-100 text-yellow-800 self-center text-center italic text-sm";
      default: // bot
        return "bg-gray-100 text-gray-950 font-medium self-start rounded-bl-none";
    }
  };

  return (
    <div className="fixed inset-0 z-[1000] flex flex-col justify-end items-end pointer-events-none">
      {/* Chat Window — fills the iframe when open */}
      {isOpen && (
        <div className="w-full h-full bg-white rounded-xl flex flex-col overflow-hidden border border-gray-200 animate-slide-up pointer-events-auto">
          {/* Header - changes based on escalation status */}
          <div
            className={`text-white p-4 flex justify-between items-center ${isEscalated
              ? "bg-gradient-to-br from-green-500 to-green-700"
              : "bg-gradient-to-br from-orange-500 to-orange-700"
              }`}
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-white bg-opacity-20 rounded-full flex items-center justify-center text-xl">
                {isEscalated ? "👨‍💼" : "🤖"}
              </div>
              <div>
                <h3 className="text-base font-semibold m-0">
                  {isEscalated ? "Live Support" : "AI Assistant"}
                </h3>
                <span className="text-xs opacity-100 font-medium">
                  {isEscalated ? "Connected to Admin" : "Online"}
                </span>
              </div>
            </div>
            <button
              className="bg-transparent border-none text-white cursor-pointer p-1 rounded transition-transform duration-300 hover:scale-125"
              onClick={closeChat}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                <path
                  d="M18 6L6 18M6 6L18 18"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>

          {/* Messages */}
          <div className="flex-1 p-4 overflow-y-auto flex flex-col gap-3">
            {messages.map((msg, index) => (
              <div
                key={index}
                className={`flex flex-col ${msg.sender === "user"
                  ? "self-end items-end"
                  : msg.sender === "system"
                    ? "self-center items-center"
                    : "self-start items-start"
                  }`}
              >
                <div
                  className={`px-4 py-3 rounded-2xl leading-relaxed [overflow-wrap:break-word] w-fit min-w-[60px] max-w-[85%] ${getMessageStyle(
                    msg.sender
                  )} markdown-content`}
                >
                  <ReactMarkdown 
                    remarkPlugins={[remarkGfm]}
                    components={{
                      a: ({ node, href, ...props }) => {
                        const isRelative = href && href.startsWith("/");
                        const targetHref = isRelative ? `${PARENT_ORIGIN}${href}` : href;
                        return (
                          <a 
                            {...props} 
                            href={targetHref}
                            target="_parent" 
                            className="text-orange-600 hover:text-orange-800 underline font-semibold transition-colors"
                          />
                        );
                      }
                    }}
                  >
                    {msg.text.replace(/\[[^\]]*\]\(\/dashboard\/\?dashboard_id=\d+\)/g, "")}
                  </ReactMarkdown>
                </div>
              </div>
            ))}
            {isLoading && (
              <div className="text-gray-500 text-sm italic mt-2">Just a moment… I’m finding the best information for you. </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="p-4 border-t border-gray-200 flex gap-2 items-end">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyPress}
              placeholder={
                isEscalated ? "Message admin..." : "Type your message..."
              }
              rows="1"
              className="flex-1 border border-gray-300 rounded-2xl px-4 py-3 resize-none text-sm outline-none transition-colors min-h-[20px] max-h-[100px] focus:border-orange-500"
            />
            <button
              onClick={sendMessage}
              disabled={isLoading}
              className={`border-none rounded-full w-10 h-10 text-white cursor-pointer flex items-center justify-center transition-colors disabled:opacity-50 ${isEscalated
                ? "bg-green-500 hover:bg-green-700"
                : "bg-orange-500 hover:bg-orange-700"
                }`}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                <path
                  d="M22 2L11 13M22 2L15 22L11 13M22 2L2 9L11 13"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          </div>
        </div>
      )}

      {/* Toggle Button — hidden when chat is open */}
      {!isOpen && (
        <div
          className={`w-[60px] h-[60px] mt-[10px] rounded-full flex items-center justify-center cursor-pointer shadow-lg transition-all duration-300 text-white pointer-events-auto ${isOpen
            ? "bg-gradient-to-br from-red-500 to-red-700 hover:shadow-xl"
            : isEscalated
              ? "bg-gradient-to-br from-green-500 to-green-700 hover:shadow-xl"
              : "bg-gradient-to-br from-orange-500 to-orange-700 hover:shadow-xl"
            }`}
          onClick={toggleChat}
        >
          <svg
            width="26"
            height="26"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            className="transition-transform duration-300"
          >
            {isOpen ? (
              <path
                d="M18 6L6 18M6 6L18 18"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            ) : (
              <>
                <path
                  d="M20 2H4C2.9 2 2 2.9 2 4V22L6 18H20C21.1 18 22 17.1 22 16V4C22 2.9 21.1 2 20 2ZM20 16H5.17L4 17.17V4H20V16Z"
                  fill="currentColor"
                />
                <circle cx="8" cy="10" r="1" fill="currentColor" />
                <circle cx="12" cy="10" r="1" fill="currentColor" />
                <circle cx="16" cy="10" r="1" fill="currentColor" />
              </>
            )}
          </svg>
        </div>)}
    </div>
  );
};

export default FloatingChatbot;
