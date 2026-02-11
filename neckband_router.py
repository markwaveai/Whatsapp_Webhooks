from fastapi import APIRouter, Header, Body, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
import os
import requests
from datetime import datetime
from db_client import es, PERISKOPE_API_KEY, PERISKOPE_ORG_PHONE, PERISKOPE_API_BASE_URL

# Router setup
router = APIRouter()

# Configuration
NECKBAND_INDEX = os.getenv("ELASTICSEARCH_NECKBAND_INDEX", "neckband_alerts")
API_TOKEN = os.getenv("API_TOKEN", "neckband-secret-token")
NECKBAND_RECIPIENTS_STR = os.getenv("NECKBAND_ALERT_RECIPIENTS", "918897399266")
NECKBAND_RECIPIENTS = [r.strip().strip("[]\"'") for r in NECKBAND_RECIPIENTS_STR.split(",") if r.strip()]

def send_whatsapp_alert(target: str, text: str):
    """
    Send WhatsApp alert to a target (chat_id or phone number).
    Handies formatting chat_id correctly.
    """
    if not PERISKOPE_API_KEY or not PERISKOPE_ORG_PHONE:
        return False

    is_group = "@g.us" in target or "@c.us" in target
    final_chat_id = target
    
    # If it's a plain number (not a group/chat id), format it
    if not is_group:
        # Standardize: remove + if present
        cleaned = target.replace("+", "")
        # Add 91 if it looks like a 10-digit Indian number and doesn't have it
        if len(cleaned) == 10 and cleaned.isdigit():
             final_chat_id = "91" + cleaned
        else:
             final_chat_id = cleaned

    url = f"{PERISKOPE_API_BASE_URL}message/send"
    headers = {
        "Authorization": f"Bearer {PERISKOPE_API_KEY}",
        "x-phone": PERISKOPE_ORG_PHONE,
        "Content-Type": "application/json"
    }
    
    payload = {
        "chat_id": final_chat_id,
        "message": text
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        return response.ok
    except Exception as e:
        print(f"Error sending WhatsApp alert: {e}")
        return False

def send_neckband_notifications(payload: dict):
    # Format message
    message = "🚨 *Neckband Alert*\n\n"
    for k, v in payload.items():
        if k not in ["timestamp", "event_type"]: # skip internal fields if desired
            message += f"*{k}*: {v}\n"
    
    # Add timestamp if present
    if "timestamp" in payload:
        message += f"\n_Time: {payload['timestamp']}_"

    for recipient in NECKBAND_RECIPIENTS:
        if send_whatsapp_alert(recipient, message):
            print(f"Alert sent to {recipient}")
        else:
            print(f"Failed to send alert to {recipient}")

@router.post("/api/neckband/alerts")
async def receive_neckband_alert(
    background_tasks: BackgroundTasks,
    payload: dict = Body(...),
    x_token: str = Header(None, alias="X-API-Token")
):
    # Debug logging
    print(f"Neckband Alert Request. Token provided: {x_token is not None}")
    
    # Fixed token authentication
    if x_token != API_TOKEN:
        print(f"Authentication failed. Expected {API_TOKEN}, got {x_token}")
        return JSONResponse(
            status_code=401, 
            content={"detail": "Invalid authentication token", "status": "error"}
        )

    try:
        # Ensure timestamp
        if "timestamp" not in payload:
            payload["timestamp"] = datetime.utcnow().isoformat()
            
        # Store in Elasticsearch
        resp = es.index(index=NECKBAND_INDEX, document=payload)
        doc_id = resp['_id']
        print(f"Neckband alert stored: {doc_id}")
        
    except Exception as e:
        print(f"Error storing neckband alert: {e}")
        #raise HTTPException(status_code=500, detail="Failed to store alert")
        return JSONResponse(
            status_code=500, 
            content={"detail": "Failed to store alert", "status": "error"}
        )

    # Send notifications
    #background_tasks.add_task(send_neckband_notifications, payload)

    return {
        "status": "success",
        "message": "Alert received and processing",
        "id": doc_id
    }
