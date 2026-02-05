from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import re
import hmac
import hashlib
import json
import os
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
import requests
from datetime import datetime, timedelta, timezone

import jwt
import random
import string
import time
from fastapi.security import OAuth2PasswordBearer
from fastapi import Depends, Body

load_dotenv()

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


SIGNING_SECRET = os.getenv("PERISKOPE_SIGNING_SECRET")
if not SIGNING_SECRET:
    raise ValueError("PERISKOPE_SIGNING_SECRET environment variable is required")

# Periskope API setup
PERISKOPE_API_KEY = os.getenv("PERISKOPE_API_KEY")
PERISKOPE_ORG_PHONE = os.getenv("PERISKOPE_ORG_PHONE")
PERISKOPE_API_BASE_URL = "https://api.periskope.app/v1/"

if not PERISKOPE_API_KEY or not PERISKOPE_ORG_PHONE:
    print("WARNING: PERISKOPE_API_KEY or PERISKOPE_ORG_PHONE not set. Chat name enrichment will be disabled.")

# Elasticsearch setup
ES_HOST = os.getenv("ELASTICSEARCH_HOST", "http://localhost:9200")
ES_USER = os.getenv("ELASTICSEARCH_USER")
ES_PASSWORD = os.getenv("ELASTICSEARCH_PASSWORD")
INDEX_NAME = os.getenv("ELASTICSEARCH_INDEX", "whatsapp_messages")
CACHE_INDEX = os.getenv("ELASTICSEARCH_CACHE_INDEX", "whatsapp_group_names")
USERS_INDEX = "users"

if ES_USER and ES_PASSWORD:
    es = Elasticsearch([ES_HOST], basic_auth=(ES_USER, ES_PASSWORD))
else:
    es = Elasticsearch([ES_HOST])

# Auth Setup
JWT_SECRET = os.getenv("JWT_SECRET", "supersecret")
JWT_ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# OTP Store (In-memory for simplicity)
otp_store = {}

def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

def send_periskope_message(phone: str, text: str):
    if not PERISKOPE_API_KEY or not PERISKOPE_ORG_PHONE:
        print("Periskope credentials missing, cannot send OTP")
        return False
    
    url = f"{PERISKOPE_API_BASE_URL}message/send"
    headers = {
        "Authorization": f"Bearer {PERISKOPE_API_KEY}",
        "x-phone": PERISKOPE_ORG_PHONE,
        "Content-Type": "application/json"
    }
    payload = {
        "chat_id": "91"+phone,
        "message": text
    }
    try:
        # Add timeout to prevent hanging
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if not response.ok:
            print(f"API Error Response: {response.text}")
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Error sending message: {e}")
        return False

def get_current_user_phone(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        phone: str = payload.get("sub")
        if phone is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return phone
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def init_cache_index():
    """Initialize Elasticsearch index for chat name cache"""
    try:
        # Check if index exists
        if not es.indices.exists(index=CACHE_INDEX):
            # Create index with mapping
            es.indices.create(
                index=CACHE_INDEX,
                body={
                    "mappings": {
                        "properties": {
                            "chat_id": {"type": "keyword"},
                            "chat_name": {"type": "text"},
                            "@timestamp": {"type": "date"},  # Default Elasticsearch timestamp field
                            "updated_at": {"type": "date"}
                        }
                    }
                }
            )
            print(f"Created Elasticsearch cache index: {CACHE_INDEX}")
        else:
            print(f"Using existing Elasticsearch cache index: {CACHE_INDEX}")
    except Exception as e:
        print(f"Error initializing cache index: {str(e)}")

# Initialize cache index on startup
init_cache_index()

def init_users_index():
    """Initialize Elasticsearch index for users"""
    try:
        if not es.indices.exists(index=USERS_INDEX):
            es.indices.create(
                index=USERS_INDEX,
                body={
                    "mappings": {
                        "properties": {
                            "phone": {"type": "keyword"},
                            "role": {"type": "keyword"},
                            "name": {"type": "text"},
                            "groups": {"type": "keyword"},
                            "created_at": {"type": "date"},
                            "updated_at": {"type": "date"}
                        }
                    }
                }
            )
            print(f"Created Elasticsearch users index: {USERS_INDEX}")
        else:
            print(f"Using existing Elasticsearch users index: {USERS_INDEX}")
    except Exception as e:
        print(f"Error initializing users index: {str(e)}")

init_users_index()

def get_chat_name_from_cache(chat_id: str) -> str | None:
    """Fetch chat name from Elasticsearch cache"""
    try:
        response = es.get(index=CACHE_INDEX, id=chat_id, ignore=[404])
        if response.get('found'):
            return response['_source'].get('chat_name')
        return None
    except Exception as e:
        print(f"Error reading from cache: {str(e)}")
        return None

def save_chat_name_to_cache(chat_id: str, chat_name: str):
    """Save chat name to Elasticsearch cache"""
    try:
        now = datetime.now().isoformat()
        es.index(
            index=CACHE_INDEX,
            id=chat_id,
            document={
                "chat_id": chat_id,
                "chat_name": chat_name,
                "@timestamp": now,  # Elasticsearch default timestamp field
                "updated_at": now
            }
        )
        print(f"Saved to cache: {chat_id} -> {chat_name}")
    except Exception as e:
        print(f"Error saving to cache: {str(e)}")

def get_chat_name(chat_id: str) -> str:
    """
    Fetch chat name from Elasticsearch cache first, then from Periskope API if not found
    Also caches member contact names if available in the response
    Returns the chat name or the chat_id if both fail
    """
    # First, check Elasticsearch cache for exact match
    cached_name = get_chat_name_from_cache(chat_id)
    if cached_name:
        print(f"Using cached chat name for {chat_id}: {cached_name}")
        return cached_name
    
    # If not found and chat_id is numeric (phone number), try with @c.us suffix
    if chat_id.isdigit():
        cached_name_suffix = get_chat_name_from_cache(f"{chat_id}@c.us")
        if cached_name_suffix:
            print(f"Using cached chat name for {chat_id}@c.us: {cached_name_suffix}")
            return cached_name_suffix
    
    # If not in cache and API is configured, fetch from Periskope API
    if not PERISKOPE_API_KEY or not PERISKOPE_ORG_PHONE:
        return chat_id
    
    try:
        headers = {
            "Authorization": f"Bearer {PERISKOPE_API_KEY}",
            "x-phone": PERISKOPE_ORG_PHONE
        }
        
        response = requests.get(
            f"{PERISKOPE_API_BASE_URL}chat/{chat_id}",
            headers=headers,
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Extract chat/group name
            chat_name = data.get("chat_name", chat_id)
            print(f"Fetched chat name from API for {chat_id}: {chat_name}")
            
            # Save chat name to Elasticsearch cache
            save_chat_name_to_cache(chat_id, chat_name)
            
            # Also cache member contact names if available (for groups)
            members = data.get("members", {})
            if members:
                for contact_id, member_info in members.items():
                    contact_name = member_info.get("contact_name")
                    if contact_name and contact_id:
                        # Check if already cached to avoid unnecessary writes
                        existing = get_chat_name_from_cache(contact_id)
                        if not existing:
                            save_chat_name_to_cache(contact_id, contact_name)
                            print(f"Cached member: {contact_id} -> {contact_name}")
            
            return chat_name
        else:
            print(f"Failed to fetch chat name for {chat_id}: {response.status_code}")
            return chat_id
    except Exception as e:
        print(f"Error fetching chat name for {chat_id}: {str(e)}")
        return chat_id

def bulk_fetch_and_cache_groups() -> dict:
    """
    Fetch all groups/chats from Periskope API and cache them in Elasticsearch
    Also caches member contact names for each chat
    This can be called on startup or manually to pre-populate the cache
    """
    if not PERISKOPE_API_KEY or not PERISKOPE_ORG_PHONE:
        return {"error": "Periskope API credentials not configured"}
    
    try:
        headers = {
            "Authorization": f"Bearer {PERISKOPE_API_KEY}",
            "x-phone": PERISKOPE_ORG_PHONE
        }
        
        # Fetch all chats from Periskope API
        response = requests.get(
            f"{PERISKOPE_API_BASE_URL}chats",
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            chats = response.json()
            cached_chats = 0
            cached_members = 0
            
            # Cache each chat and its members
            for chat in chats:
                chat_id = chat.get("chat_id")
                chat_name = chat.get("chat_name")
                
                # Cache chat name
                if chat_id and chat_name:
                    existing = get_chat_name_from_cache(chat_id)
                    if not existing:
                        save_chat_name_to_cache(chat_id, chat_name)
                        cached_chats += 1
                        print(f"Cached chat: {chat_id} -> {chat_name}")
                
                # Cache member names
                members = chat.get("members", {})
                if members:
                    for contact_id, member_info in members.items():
                        contact_name = member_info.get("contact_name")
                        if contact_name and contact_id:
                            existing = get_chat_name_from_cache(contact_id)
                            if not existing:
                                save_chat_name_to_cache(contact_id, contact_name)
                                cached_members += 1
                                print(f"Cached member: {contact_id} -> {contact_name}")
            
            total_chats = len(chats)
            print(f"Bulk cache completed: {cached_chats} new chats, {cached_members} new members")
            return {
                "status": "success",
                "total_chats": total_chats,
                "newly_cached_chats": cached_chats,
                "newly_cached_members": cached_members,
                "already_cached": total_chats - cached_chats
            }
        else:
            error_msg = f"Failed to fetch chats from Periskope API: {response.status_code}"
            print(error_msg)
            return {"error": error_msg, "status_code": response.status_code}
    except Exception as e:
        error_msg = f"Error in bulk fetch: {str(e)}"
        print(error_msg)
        return {"error": error_msg}

@app.get("/")
async def root():
    return {"message": "Webhook server is running"}

@app.get("/refresh-cache")
async def refresh_cache():
    """
    Endpoint to manually trigger cache refresh
    Fetches all groups from Periskope API and caches them
    """
    result = bulk_fetch_and_cache_groups()
    return result

    return result

@app.post("/auth/login-otp")
async def login_otp(payload: dict):
    phone = payload.get("phone")
    if not phone:
        raise HTTPException(status_code=400, detail="Phone number required")
    
    otp = generate_otp()
    otp_store[phone] = {
        "otp": otp,
        "expires": time.time() + 300  # 5 minutes
    }
    
    # Send OTP via Periskope
    message = f"Your Markwave Messaging App Login OTP is: {otp}\n\nLogin at https://messaging.markwave.com/"
    otp_sent = send_periskope_message(phone, message)
    
    # Fallback/Dev mode: Always print OTP for testing if API fails or just for visibility
    if not otp_sent:
        print(f"⚠️  [DEV MODE] Failed to send OTP via API to {phone}. The OTP is: {otp}")
        # For development purposes, allow proceeding even if SMS fails
        # In PROD, you should restart this logic to strictly return 500
        return {"message": "OTP failed to send (Check Server Logs for Code)", "dev_otp": otp}
    
    return {"message": "OTP sent successfully"}

@app.post("/auth/verify-otp")
async def verify_otp(payload: dict):
    phone = payload.get("phone")
    otp = payload.get("otp")
    
    if not phone or not otp:
        raise HTTPException(status_code=400, detail="Phone and OTP required")
        
    stored_data = otp_store.get(phone)
    if not stored_data:
        raise HTTPException(status_code=400, detail="OTP not requested or expired")
        
    if time.time() > stored_data["expires"]:
        del otp_store[phone]
        raise HTTPException(status_code=400, detail="OTP expired")
        
    if stored_data["otp"] != otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")
        
    # Valid OTP
    del otp_store[phone]
    
    # Create/Update User in Elasticsearch
    role = "user"
    name = None
    try:
        # Search for user
        resp = es.search(index=USERS_INDEX, query={"term": {"phone": phone}}, size=1)
        if resp['hits']['hits']:
            # User exists
            user_doc = resp['hits']['hits'][0]['_source']
            role = user_doc.get('role', 'user')
            name = user_doc.get('name')
        else:
            # Create new user
            new_user = {
                "phone": phone,
                "role": "user",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "groups": []
            }
            es.index(index=USERS_INDEX, document=new_user, refresh='wait_for')
            role = "user"
            print(f"Created new user: {phone}")
        
    except Exception as e:
        print(f"Elasticsearch Error during login: {e}")
        raise HTTPException(status_code=500, detail="Service temporarily unavailable")
    
    # Generate JWT
    access_token_expires = timedelta(minutes=60*24) # 24 hours
    expire = datetime.utcnow() + access_token_expires
    to_encode = {"sub": phone, "role": role, "exp": expire}
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    
    return {"access_token": encoded_jwt, "token_type": "bearer", "role": role, "name": name}

@app.post("/auth/logout")
async def logout(current_user: str = Depends(get_current_user_phone)):
    # log_user_event(current_user, "LOGOUT")
    pass
    return {"message": "Logged out successfully"}

@app.get("/groups")
async def get_groups(current_user: str = Depends(get_current_user_phone)):
    # Get user role from ES
    role = "user"
    user_groups = []
    try:
        resp = es.search(index=USERS_INDEX, query={"term": {"phone": current_user}}, size=1)
        if resp['hits']['hits']:
            user_data = resp['hits']['hits'][0]['_source']
            role = user_data.get('role', 'user')
            user_groups = user_data.get('groups', [])
    except Exception as e:
        print(f"Error fetching user role: {e}")

    # Fetch all chats from cache or API
    # Here we reuse the bulk fetching logic but maybe we should just read from cache if possible.
    # But for simplicity, let's just fetch from API or Cache. 
    # Since we have get_chat_name_from_cache, but not get_all_chats_from_cache...
    # We can use ES search to get all chats.
    
    groups = []
    
    # FOR ADMIN: Return ALL groups from ES cache
    if role == 'admin':
        try:
            # Search ES for everything in CACHE_INDEX
            resp = es.search(index=CACHE_INDEX, size=1000, query={"match_all": {}})
            for hit in resp['hits']['hits']:
                source = hit['_source']
                chat_id = source.get('chat_id')
                if chat_id and chat_id.endswith('@g.us'):
                    groups.append(source)
            return groups
        except Exception as e:
            print(f"Error fetching from ES: {e}")
            return []

    # FOR USER: Return ONLY assigned groups from ES
    else:
        assigned_chat_ids = user_groups
        
        if not assigned_chat_ids:
            return []
            
        # Hydrate these IDs with details from Elasticsearch
        try:
            # Multi-get or Search with Terms
            resp = es.search(
                index=CACHE_INDEX, 
                size=1000, 
                query={
                    "terms": {
                        "chat_id.keyword": assigned_chat_ids
                    }
                }
            )
            for hit in resp['hits']['hits']:
                groups.append(hit['_source'])
            return groups
        except Exception as e:
             print(f"Error hydrating groups from ES: {e}")
             # If ES fails, at least return IDs so frontend doesn't crash? 
             # Or better, return empty list to avoid confusion.
             return []

    return groups
    
# --- Admin Endpoints ---

class UserSchema(dict): 
    # Quick schema for input
    pass

@app.post("/admin/setup")
async def create_initial_admin(payload: dict):
    """
    Backdoor to create the first admin user.
    Usage: POST /admin/setup { "phone": "919876543210", "secret_key": "YOUR_ADMIN_SECRET" }
    """
    phone = payload.get("phone")
    secret_key = payload.get("secret_key")
    
    # Simple protection for this endpoint using a hardcoded secret or env var
    # This prevents random public access
    ADMIN_SETUP_SECRET = os.getenv("ADMIN_SETUP_SECRET", "admin1234")
    
    if secret_key != ADMIN_SETUP_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin secret")
        
    if not phone:
        raise HTTPException(status_code=400, detail="Phone required")

    try:
        # Check if user exists
        resp = es.search(index=USERS_INDEX, query={"term": {"phone": phone}}, size=1)
        if resp['hits']['hits']:
            # Update
            doc_id = resp['hits']['hits'][0]['_id']
            es.update(index=USERS_INDEX, id=doc_id, body={"doc": {"role": "admin", "updated_at": datetime.now().isoformat()}})
        else:
            # Create
            doc = {
                "phone": phone,
                "role": "admin",
                "groups": [],
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            es.index(index=USERS_INDEX, document=doc)
        return {"message": f"User {phone} promoted to ADMIN"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/users")
async def create_user(payload: dict, current_user: str = Depends(get_current_user_phone)):
    """
    Admin only: Create a new user with 'user' role.
    """
    # 1. Verify Verification
    role = "user"
    try:
        resp = es.search(index=USERS_INDEX, query={"term": {"phone": current_user}}, size=1)
        if resp['hits']['hits']:
            role = resp['hits']['hits'][0]['_source'].get('role', 'user')
    except: pass
            
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
        
    new_user_phone = payload.get("phone")
    new_user_name = payload.get("name") # Optional name
    
    if not new_user_phone:
        raise HTTPException(status_code=400, detail="New user phone required")

    try:
        resp = es.search(index=USERS_INDEX, query={"term": {"phone": new_user_phone}}, size=1)
        if resp['hits']['hits']:
            # Update name if provided
            if new_user_name:
                doc_id = resp['hits']['hits'][0]['_id']
                es.update(index=USERS_INDEX, id=doc_id, body={"doc": {"name": new_user_name}})
        else:
            doc = {
                "phone": new_user_phone,
                "name": new_user_name,
                "role": "user",
                "groups": [],
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            es.index(index=USERS_INDEX, document=doc)
        return {"message": f"User {new_user_phone} created/ensured."}
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

@app.delete("/admin/users/{phone}")
async def delete_user(phone: str, current_user: str = Depends(get_current_user_phone)):
    """
    Admin only: Delete a user by phone number.
    """
    # 1. Verify Verification
    role = "user"
    try:
        resp = es.search(index=USERS_INDEX, query={"term": {"phone": current_user}}, size=1)
        if resp['hits']['hits']:
            role = resp['hits']['hits'][0]['_source'].get('role', 'user')
    except: pass
            
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
        
    try:
        es.delete_by_query(index=USERS_INDEX, body={"query": {"term": {"phone": phone}}})
    except Exception as e:
        print(f"Error deleting user: {e}")
            
    return {"message": f"User {phone} deleted"}

@app.post("/admin/assign-group")
async def assign_group(payload: dict, current_user: str = Depends(get_current_user_phone)):
    """
    Admin only: Assign a group (chat_id) OR a list of groups to a user.
    Also allows setting role (admin/user).
    """
    # 1. Verify Verification
    role = "user"
    try:
        resp = es.search(index=USERS_INDEX, query={"term": {"phone": current_user}}, size=1)
        if resp['hits']['hits']:
            role = resp['hits']['hits'][0]['_source'].get('role', 'user')
    except: pass

    if role != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
        
    target_user_phone = payload.get("phone")
    chat_ids = payload.get("chat_ids") # Expect list or single string
    target_role = payload.get("role") # 'admin' or 'user'
    
    if not target_user_phone:
        raise HTTPException(status_code=400, detail="phone required")
        
    try:
        resp = es.search(index=USERS_INDEX, query={"term": {"phone": target_user_phone}}, size=1)
        if not resp['hits']['hits']:
             raise HTTPException(status_code=404, detail="User not found")
        
        doc_id = resp['hits']['hits'][0]['_id']
        update_doc = {}
        
        if target_role:
            update_doc['role'] = target_role
            
        if chat_ids is not None: # check for None to allow omitting
             if isinstance(chat_ids, str):
                 chat_ids = [chat_ids]
             update_doc['groups'] = chat_ids
             
        if update_doc:
            update_doc['updated_at'] = datetime.now().isoformat()
            es.update(index=USERS_INDEX, id=doc_id, body={"doc": update_doc})
            
        return {"message": f"Updated {target_user_phone}"}
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

async def get_current_user_role(phone: str = Depends(get_current_user_phone)):
    if phone:
        try:
             resp = es.search(index=USERS_INDEX, query={"term": {"phone": phone}}, size=1)
             if resp['hits']['hits']:
                 return resp['hits']['hits'][0]['_source'].get('role', 'user')
        except: pass
    return "user"

@app.post("/admin/group-metadata")
async def update_group_metadata(current_user_role: str = Depends(get_current_user_role),
                                payload: dict = Body(...)):
    if current_user_role != "admin":
        raise HTTPException(status_code=403, detail="Admins only")

    chat_id = payload.get("chat_id")
    metadata = payload.get("metadata")

    if not chat_id or not metadata:
        raise HTTPException(status_code=400, detail="chat_id and metadata are required")

    try:
        es.update(
            index=CACHE_INDEX,
            id=chat_id,
            body={"doc": metadata}
        )
        return {"message": f"Group {chat_id} metadata updated successfully."}
    except Exception as e:
        print(f"Error updating group metadata in ES: {e}")
        raise HTTPException(status_code=500, detail="Failed to update group metadata")

@app.get("/admin/users")
async def list_users(current_user: str = Depends(get_current_user_phone)):
    """
    Admin only: List all users from Neo4j.
    """
    # 1. Verify Verification
    role = "user"
    try:
        resp = es.search(index=USERS_INDEX, query={"term": {"phone": current_user}}, size=1)
        if resp['hits']['hits']:
            role = resp['hits']['hits'][0]['_source'].get('role', 'user')
    except: pass

    if role != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
    
    users = []
    try:
        resp = es.search(index=USERS_INDEX, query={"match_all": {}}, size=1000)
        for hit in resp['hits']['hits']:
            users.append(hit['_source'])
    except Exception as e:
        print(f"Error listing users: {e}")
                
    return users

def verify_signature(raw_body: bytes, signature: str) -> bool:

    expected_signature = hmac.new(
        SIGNING_SECRET.encode(),
        raw_body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature)

async def process_webhook_message(event: str, data: dict):
    """Heavy lifting for webhook processing: enrichment, indexing, external posting, and broadcasting"""
    try:
        # Prepare document for Elasticsearch
        doc = {"event": event, **data}
        if 'id' in doc and isinstance(doc['id'], dict):
            doc['id_details'] = doc.pop('id')
        
        # **ENRICH DATA WITH CHAT NAMES**
        if 'chat_id' in doc:
            chat_id = doc['chat_id']
            chat_name = get_chat_name(chat_id)
            doc['chat_name'] = chat_name
            print(f"Enriched with chat_name: {chat_name}")
        
        if 'sender_phone' in doc and not doc.get('from_me', False):
            sender_phone = doc['sender_phone']
            sender_name = get_chat_name(sender_phone)
            doc['sender_name'] = sender_name
            print(f"Enriched with sender_name: {sender_name}")

        # **REPLACE MENTIONS IN BODY WITH NAMES**
        if 'body' in doc and doc['body']:
            try:
                mentions = re.findall(r'@(\d+)', doc['body'])
                if mentions:
                    for phone in mentions:
                        contact_name = get_chat_name(phone)
                        if contact_name and contact_name != phone:
                            doc['body'] = doc['body'].replace(f"@{phone}", contact_name)
            except Exception as e:
                print(f"Error processing mentions: {e}")
        # Index to Elasticsearch
        try:
            ES_INDEX = os.environ["ELASTICSEARCH_INDEX"]
            es.index(
                index=ES_INDEX,
                document=data
            )

            msg_id = doc.get('message_id') or doc.get('id')
            if msg_id:
                es.index(index=INDEX_NAME, id=msg_id, document=doc)
            else:
                es.index(index=INDEX_NAME, document=doc)
            print(f"Message indexed to Elasticsearch (id={msg_id})")
        except Exception as e:
            print("Error indexing to Elasticsearch:", str(e))
    except Exception as e:
        print(f"Error in background message processing: {e}")

@app.post("/periskopewebhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    # Get raw body for verification (optional depending on needs)
    raw_body = await request.body()
    # Parse JSON
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Handle the event
    event = payload.get("event") or payload.get("event_type")
    data = payload.get("data")

    if event in ["message.created", "message.ack.updated"] and data:
        # Offload heavy processing to background task to avoid timeout
        background_tasks.add_task(process_webhook_message, event, data)

    return {"status": "ok"}

@app.post("/api/whatsapp/ai-processed-data")
async def post_whatsapp_ai_processed_data(payload: dict = Body(...)):
    """
    Receive and process WhatsApp AI data for farm monitoring
    
    Expected payload format:
    {
    "class": "ammonium",
    "confidence": 95.0,
    "pond_name": "D6",
    "data": {
        "url": "https://storage.googleapis.com/periskope-attachments/1094fa55-ff57-4116-84a9-3ce7ca235d22%2F919866805070%40c.us%2F3EB042C39959D1054ABD0C%2F3EB042C39959D1054ABD0C.jpeg",
        "mimetype": "image/jpeg",
        "text": "Tank no:- D6\\nAmmonium:- 0.0\"",
        "value": 0.0
    },
    "message_id": "false_120363424160793064@g.us_3EB042C39959D1054ABD0C",
    "group_name": "AX COE - Tech",
    "group_id": "120363424160793064@g.us",
    "sender_name": "Bharath",
    "sender_phone": "919398495195"
    
   }
    """
    try:
        # Log the incoming request
        print(f"Processing WhatsApp AI data: {payload}", flush=True)

        # update the elk document
        try:
            msg_id = payload.get("message_id")
            if msg_id:
                # Filter payload for update: only include class, confidence, pond_name, and data
                update_doc = {
                    "class": payload.get("class"),
                    "confidence": payload.get("confidence"),
                    "pond_name": payload.get("pond_name"),
                    "data": payload.get("data")
                }
                es.update(index=INDEX_NAME, id=msg_id, doc=update_doc, doc_as_upsert=True)
                print(f"Data updated in Elasticsearch with AI processed data (id={msg_id})")
            else:
                print("No message_id found in payload, skipping ES update")
        except Exception as e:
            print("Error updating to Elasticsearch:", str(e))
            # You might want to raise an exception or log it
        return {
            "status": "success",
            "statuscode": 200,
            "message": "Data processed successfully"
        }
        
    except Exception as e:
        error_msg = f"Error processing request: {str(e)}"
        print(error_msg, flush=True)
        return {
            "status": "failed",
            "statuscode": 500,
            "error": error_msg
        }

@app.post("/api/whatsapp/approve-ai-data")
async def approve_ai_data(payload: dict = Body(...), user_phone: str = Depends(get_current_user_phone),isTestRun: bool = False):
    """
    Approve and finalize AI data.
    """
    try:
        # Log the incoming request
        print(f"Approving AI data: {payload}", flush=True)
        # Extract timestamp if present and parse to epoch (ms)
        timestamp_arg = None
        ts_str = payload.get("timestamp")
        if ts_str:
            try:
                # Handle ISO format "2025-12-24T10:13:08+00:00"
                dt = datetime.fromisoformat(ts_str)
                timestamp_arg = int(dt.timestamp() * 1000)
            except Exception as e:
                print(f"Error parsing timestamp {ts_str}: {e}")

        # Process the data through the AI pipeline
        result = process_ai_data(payload,user_phone,isTestRun, timestamp=timestamp_arg)
        if isinstance(result, dict) and result.get("status") == "error":
            return {
                "status": "failed",
                "statuscode": 500,
                "error": result.get("message")
            }

        # Get approver name - Try payload first (from frontend), then cache, then Neo4j
        approver_name = payload.get("approved_by_name") or ""

        # update the elk document
        try:
            msg_id = payload.get("message_id")
            if msg_id and result.get("status") == "success" and isTestRun==False:
                # Filter payload for update
                update_doc = {
                    "modified_class": payload.get("class"),
                    "modified_pond_name": payload.get("pond_name"),
                    "ai_approved": True,
                    "bubbleId": result.get("data",{}).get("bubbleId"),
                    "ai_approved_by": approver_name+"("+user_phone+")",
                    "ai_approved_at": datetime.now(timezone.utc).isoformat()
                }
                es.update(index=INDEX_NAME, id=msg_id, doc=update_doc, doc_as_upsert=True, refresh='true')
                print(f"Approved data updated in Elasticsearch (id={msg_id})")
            else:
                print("No message_id found in payload, skipping ES update")
        except Exception as e:
            print("Error updating to Elasticsearch:", str(e))
        
        return {
            "status": "success",
            "statuscode": 200,
            "message": "Data approved successfully",
            "data": result.get("data")
        }
        
    except Exception as e:
        error_msg = f"Error processing request: {str(e)}"
        print(error_msg, flush=True)
        return {
            "status": "failed",
            "statuscode": 500,
            "error": error_msg
        }

@app.post("/api/whatsapp/feedback")
async def submit_feedback(payload: dict, current_user: str = Depends(get_current_user_phone)):
    """
    Endpoint for users to provide feedback on AI processing (Correct/Incorrect).
    """
    message_id = payload.get("message_id")
    feedback = payload.get("feedback")
    reason = payload.get("reason")
    
    if not message_id or not feedback:
        raise HTTPException(status_code=400, detail="Missing message_id or feedback")
        
    if feedback not in ["correct", "incorrect"]:
        raise HTTPException(status_code=400, detail="Invalid feedback type")
        
    try:
        # Update Elasticsearch document
        update_doc = {
            "feedback": feedback,
            "feedback_reason": reason,
            "feedback_by": current_user,
            "feedback_at": datetime.utcnow().isoformat()
        }
        es.update(index=INDEX_NAME, id=message_id, doc=update_doc, doc_as_upsert=True, refresh='true')
        print(f"Feedback updated in Elasticsearch (id={message_id}, feedback={feedback})")
        
        return {"status": "success", "message": "Feedback submitted successfully"}
        
    except Exception as e:
        print(f"Error updating feedback to Elasticsearch: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to submit feedback: {str(e)}")


@app.post("/api/whatsapp/update-ocr-table")
async def update_ocr_table(payload: dict, current_user: str = Depends(get_current_user_phone)):
    message_id = payload.get("message_id")
    table = payload.get("table")
    table_type = payload.get("table_type") or "feed_table"

    if not message_id or table is None:
        raise HTTPException(status_code=400, detail="Missing message_id or table")

    try:
        update_doc = {
            "class": "ocr_tables",
            "data": {
                "table_type": table_type,
                "table": table
            },
            "ocr_table_edited_by": current_user,
            "ocr_table_edited_at": datetime.utcnow().isoformat()
        }

        es.update(index=INDEX_NAME, id=message_id, doc=update_doc, doc_as_upsert=True, refresh='true')
        print(f"OCR table updated in Elasticsearch (id={message_id})")
        return {"status": "success", "message": "OCR table updated successfully"}
    except Exception as e:
        print(f"Error updating OCR table to Elasticsearch: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update OCR table: {str(e)}")

# Optional: Pre-populate cache on startup
# Set CACHE_ON_STARTUP=true in .env to enable
if os.getenv("CACHE_ON_STARTUP", "false").lower() == "true":
    print("🚀 Pre-populating cache on startup...")
    try:
        from threading import Thread
        import time
        
        def populate_cache_on_startup():
            time.sleep(3)  # Wait for server to be fully up
            result = bulk_fetch_and_cache_groups()
            print(f"✅ Startup cache population completed: {result}")
        
        Thread(target=populate_cache_on_startup, daemon=True).start()
        print("📦 Cache population started in background thread")
    except Exception as e:
        print(f"❌ Error starting cache population: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="debug")



