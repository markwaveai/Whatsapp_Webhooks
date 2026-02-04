import os
from dotenv import load_dotenv
from elasticsearch import Elasticsearch

# Load environment variables
load_dotenv()

# Elasticsearch setup
ES_HOST = os.getenv("ELASTICSEARCH_HOST", "http://localhost:9200")
ES_USER = os.getenv("ELASTICSEARCH_USER")
ES_PASSWORD = os.getenv("ELASTICSEARCH_PASSWORD")
INDEX_NAME = os.getenv("ELASTICSEARCH_INDEX", "whatsapp_messages")

print(f"Connecting to Elasticsearch at {ES_HOST}...")
if ES_USER and ES_PASSWORD:
    es = Elasticsearch([ES_HOST], basic_auth=(ES_USER, ES_PASSWORD))
else:
    es = Elasticsearch([ES_HOST])

print(f"Updating settings for index: {INDEX_NAME}")

# Current limit is usually 1000
new_limit = 3000

try:
    # Update index settings
    es.indices.put_settings(
        index=INDEX_NAME,
        body={
            "index.mapping.total_fields.limit": new_limit
        }
    )
    print(f"Successfully updated 'index.mapping.total_fields.limit' to {new_limit} for index '{INDEX_NAME}'")
    
    # Verify
    settings = es.indices.get_settings(index=INDEX_NAME)
    current_limit = settings[INDEX_NAME]['settings']['index']['mapping']['total_fields']['limit']
    print(f"Verification: Current limit is now {current_limit}")

except Exception as e:
    print(f"Error updating limits: {e}")
