import os
from dotenv import load_dotenv
from elasticsearch import Elasticsearch

load_dotenv()

# Periskope API setup
PERISKOPE_API_KEY = os.getenv("PERISKOPE_API_KEY")
PERISKOPE_ORG_PHONE = os.getenv("PERISKOPE_ORG_PHONE")
PERISKOPE_API_BASE_URL = "https://api.periskope.app/v1/"

if not PERISKOPE_API_KEY or not PERISKOPE_ORG_PHONE:
    print("WARNING: PERISKOPE_API_KEY or PERISKOPE_ORG_PHONE not set. Chat name enrichment will be disabled.")

# Elasticsearch setup
ES_HOST = os.getenv("ELASTICSEARCH_HOST") or "http://localhost:9200"
ES_USER = os.getenv("ELASTICSEARCH_USER")
ES_PASSWORD = os.getenv("ELASTICSEARCH_PASSWORD")
INDEX_NAME = os.getenv("ELASTICSEARCH_INDEX", "whatsapp_messages")
CACHE_INDEX = os.getenv("ELASTICSEARCH_CACHE_INDEX", "whatsapp_group_names")
USERS_INDEX = "users"

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
