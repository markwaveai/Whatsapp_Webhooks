import os
import requests
import json
from datetime import datetime
from elasticsearch import Elasticsearch
from dotenv import load_dotenv

load_dotenv()

# Periskope API setup
PERISKOPE_API_KEY = os.getenv("PERISKOPE_API_KEY")
PERISKOPE_ORG_PHONE = os.getenv("PERISKOPE_ORG_PHONE")
PERISKOPE_API_BASE_URL = "https://api.periskope.app/v1/"

# Elasticsearch setup
ES_HOST = os.getenv("ELASTICSEARCH_HOST") or "http://localhost:9200"
ES_USER = os.getenv("ELASTICSEARCH_USER")
ES_PASSWORD = os.getenv("ELASTICSEARCH_PASSWORD")
CACHE_INDEX = os.getenv("ELASTICSEARCH_CACHE_INDEX", "whatsapp_group_names")

print(f"Connecting to Elasticsearch at {ES_HOST}...")

# Initialize ES
if ES_USER and ES_PASSWORD:
    es = Elasticsearch([ES_HOST], basic_auth=(ES_USER, ES_PASSWORD), verify_certs=False, ssl_show_warn=False)
else:
    es = Elasticsearch([ES_HOST], verify_certs=False, ssl_show_warn=False)

def sync_all_groups():
    if not PERISKOPE_API_KEY or not PERISKOPE_ORG_PHONE:
        print("❌ Error: PERISKOPE_API_KEY or PERISKOPE_ORG_PHONE not set in .env")
        return

    print("🚀 Fetching all chats from Periskope API...")
    
    headers = {
        "Authorization": f"Bearer {PERISKOPE_API_KEY}",
        "x-phone": PERISKOPE_ORG_PHONE
    }
    
    try:
        response = requests.get(
            f"{PERISKOPE_API_BASE_URL}chats",
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            chats = response.json()
            print(f"✅ Found {len(chats)} chats. Updating cache...")
            
            count = 0
            for chat in chats:
                chat_id = chat.get("chat_id")
                chat_name = chat.get("chat_name")
                
                # Only cache if we have both, and chat_name isn't just the ID
                if chat_id and chat_name and chat_name != chat_id:
                    try:
                        now = datetime.now().isoformat()
                        es.index(
                            index=CACHE_INDEX,
                            id=chat_id,
                            document={
                                "chat_id": chat_id,
                                "chat_name": chat_name,
                                "@timestamp": now,
                                "updated_at": now
                            }
                        )
                        print(f"   Saved: {chat_id} -> {chat_name}")
                        count += 1
                    except Exception as e:
                        print(f"   ⚠️ Error saving {chat_id}: {e}")
            
            print(f"\n🎉 Sync Completed! Updated {count} group names in cache.")
            
        else:
            print(f"❌ API Error: Status {response.status_code}")
            print(f"Body: {response.text}")
            
    except Exception as e:
        print(f"❌ Network/Script Error: {e}")

if __name__ == "__main__":
    if not es.ping():
        print("❌ Could not connect to Elasticsearch. Check your settings.")
    else:
        sync_all_groups()
