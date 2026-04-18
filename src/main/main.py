from fastapi import FastAPI, Request, Query, HTTPException, Response
from settings import WHATSAPP_TOKEN, PHONE_NUMBER_ID
from src.Workflow.workflow import workflow
from src.Uploader.upload_api import upload
import httpx
import re

VERIFICATION_TOKEN = "my_super_secret_token_987"

# query_agent = create_query_agent(api_key=GOOGLE_API_KEY)

app = FastAPI()

@app.post("/upload")
def upload_file():
    return upload()

# --- Health check ---
@app.get("/")
def root():
    return {"status": "ok"}

# --- Webhook verification (GET) ---
@app.get("/webhook")
def verify_whatsapp(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFICATION_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Invalid verification token")

# --- Webhook receiver (POST) ---
@app.post("/webhook")
async def receive_whatsapp(request: Request):
    data = await request.json()
    print("Incoming webhook:", data)  # debug log

    value = (
        data.get("entry", [{}])[0]
            .get("changes", [{}])[0]
            .get("value", {})
    )
    messages = value.get("messages")
    if not messages:
        return Response(status_code=200)  # must ACK quickly

    msg = messages[0]
    sender = msg.get("from")  # customer's phone in E.164
    message_id = msg.get("id")  # WhatsApp message ID

    # Extract text depending on message type
    text = None
    mtype = msg.get("type")

    if mtype == "text":
        text = msg.get("text", {}).get("body")
    elif mtype == "button":
        text = msg.get("button", {}).get("text")
    elif mtype == "interactive":
        itype = msg.get("interactive", {}).get("type")
        if itype == "button_reply":
            text = msg["interactive"]["button_reply"].get("title")
        elif itype == "list_reply":
            text = msg["interactive"]["list_reply"].get("title")
    elif mtype == "image":
        text = msg.get("caption")  # optional fallback

    if not text:
        await send_whatsapp_message(sender, "Please send a text message, I can't understand anything other than text messages!")
        return Response(status_code=200)

    # Mark as read + show typing indicator
    await mark_read_and_typing(message_id)

    # Call your AI agent
    try:
        initial_state = {
            "user_query": text,
            "query_response": "",
            "evaluation_state": "",
            "retry_count": 0,
            "instruction": ""
        }
        final_state = workflow.invoke(initial_state, config={"verbose": True})
        print(final_state)
        query_response = final_state["query_response"]
        if "ValidationOutcome" in query_response:
            # IMPROVED: More robust regex to handle escaped quotes and content until closing quote
            # Captures content inside validated_output="...", handling escaped chars
            pattern = r'validated_output="((?:[^"\\]|\\.)*)"'
            match = re.search(pattern, query_response)
            if match:
                answer = match.group(1).replace('\\n', '\n').replace('\\"', '"').strip()  # Unescape and clean
            else:
                # FIXED: For fallback, use regex to extract validated_output specifically until the closing quote before the comma
                fallback_pattern = r'validated_output=\'([^\']*)\'[, ]'
                fallback_match = re.search(fallback_pattern, query_response)
                if fallback_match:
                    answer = fallback_match.group(1).replace('\\n', '\n').replace('\\"', '"').replace("\\'", "'").strip()
                else:
                    # Ultimate fallback: Manual split and slice up to the next comma after the value
                    start_idx = query_response.find("validated_output='") + len("validated_output='")
                    end_idx = query_response.find("',\n    reask=", start_idx)
                    if end_idx != -1:
                        raw_content = query_response[start_idx:end_idx]
                        answer = raw_content.replace('\\n', '\n').replace('\\"', '"').replace("\\'", "'").strip()
                    else:
                        answer = "Error parsing validated output."
        else:
            # FIXED: For direct LLM responses, strip leading/trailing single quotes and whitespace
            answer = query_response.replace("'","").strip().strip("'").strip()  # Remove ' at start/end, then extra whitespace
        
        # FINAL CLEANUP: Remove any trailing newlines or extra whitespace
        answer = re.sub(r'\n+$', '', answer).strip()
    except Exception as e:
        print("Agent error:", e)
        answer = "⚠️ Oops, something went wrong. Please try again."

    # Send reply back to user (this automatically dismisses typing indicator)
    await send_whatsapp_message(sender, answer)

    return Response(status_code=200)

# --- Helper: Mark as read + show typing ---
async def mark_read_and_typing(message_id: str):
    """Mark message as read and show typing indicator in one API call"""
    url = f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {
            "type": "text"
        }
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, headers=headers, json=payload)
            print(">>> Mark read + typing response:", r.status_code)
    except Exception as e:
        print("Error setting read + typing:", e)

# --- Helper: Send WhatsApp message ---
async def send_whatsapp_message(to: str, message: str):
    url = f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": message}
    }

    print(">>> Using TOKEN:", WHATSAPP_TOKEN[:30], "...")  # log first 30 chars
    print(">>> Using PHONE_NUMBER_ID:", PHONE_NUMBER_ID)

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, headers=headers, json=payload)
        print(">>> Response:", r.text)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            print("WhatsApp API error:", e.response.text)

# python -m uvicorn src.main.main:app --reload