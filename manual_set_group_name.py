import os
from elasticsearch import Elasticsearch
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Elasticsearch setup
ES_HOST = os.getenv("ELASTICSEARCH_HOST") or "http://localhost:9200"
ES_USER = os.getenv("ELASTICSEARCH_USER")
ES_PASSWORD = os.getenv("ELASTICSEARCH_PASSWORD")
CACHE_INDEX = os.getenv("ELASTICSEARCH_CACHE_INDEX", "whatsapp_group_names")

print(f"Connecting to Elasticsearch at {ES_HOST}...")

if ES_USER and ES_PASSWORD:
    es = Elasticsearch(
        [ES_HOST],
        basic_auth=(ES_USER, ES_PASSWORD),
        verify_certs=False,
        ssl_show_warn=False
    )
else:
    es = Elasticsearch(
        [ES_HOST],
        verify_certs=False,
        ssl_show_warn=False
    )

def set_group_name(chat_id, chat_name):
    try:
        if not es.ping():
            print("Error: Could not connect to Elasticsearch.")
            return

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
        print(f"✅ Successfully mapped {chat_id} -> '{chat_name}' in index '{CACHE_INDEX}'")
        print("Future messages from this ID will now use this name.")
        
    except Exception as e:
        print(f"❌ Error saving to cache: {str(e)}")

if __name__ == "__main__":
    print("--- Manual Group Name Setter ---")
    chat_id = input("Enter Chat ID (e.g., 12036...g.us): ").strip()
    chat_name = input("Enter Group Name: ").strip()
    
    if chat_id and chat_name:
        set_group_name(chat_id, chat_name)
    else:
        print("Operation cancelled. ID and Name are required.")
