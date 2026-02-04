# WhatsApp Webhook Server

This is a FastAPI server to receive webhooks from Periskope for WhatsApp messages and store them in Elasticsearch with enriched data.

## Features

- ✅ Receives WhatsApp message webhooks from Periskope
- ✅ **Automatically enriches messages** with real chat names and contact names using Periskope API
- ✅ Stores enriched data in Elasticsearch for better searchability
- ✅ **Uses Elasticsearch for caching** - Perfect for Cloud Run and containerized deployments
- ✅ **Stateless and scalable** - Works with Cloud Run auto-scaling

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and configure your settings:
   ```bash
   cp .env.example .env
   ```

3. Update your `.env` file with actual values:
   ```
   PERISKOPE_SIGNING_SECRET=your_actual_signing_secret
   PERISKOPE_API_KEY=your_bearer_token_here
   PERISKOPE_ORG_PHONE=
   
   ELASTICSEARCH_HOST=
   ELASTICSEARCH_INDEX=whatsapp_message_webhook
   ELASTICSEARCH_CACHE_INDEX=chat_names_cache
   ELASTICSEARCH_USER=elastic
   ELASTICSEARCH_PASSWORD=your_password_here
   ```

4. Ensure Elasticsearch is running and accessible.

5. Run the server:
   ```bash
   uvicorn main:app --reload
   ```

6. Configure the webhook URL in Periskope dashboard to point to `http://your-server:8000/periskopewebhook`

## Cloud Run Deployment

This webhook is **optimized for Google Cloud Run**:

✅ **Stateless design** - No local file storage
✅ **Elasticsearch caching** - Persistent across container restarts  
✅ **Auto-scaling ready** - All instances share the same cache
✅ **No volume mounts needed** - Everything in Elasticsearch

### Deploy to Cloud Run:

```bash
# Build and deploy
gcloud run deploy whatsapp-webhook \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars="$(cat .env | grep -v '^#' | xargs)"
```

## How It Works

### Data Enrichment

When a WhatsApp message is received via webhook, the server:

1. **Checks Elasticsearch Cache**: First looks up the chat_id in the `chat_names_cache` index
2. **Fetches Chat Name**: If not cached, calls Periskope API `GET /chats/{chat_id}` to get the real chat/group name
3. **Fetches Sender Name**: For incoming messages, calls the same API to get the contact name
4. **Saves to Elasticsearch**: Stores the mapping in Elasticsearch cache index for future use
5. **Stores Enriched Data**: Saves the message with `chat_name` and `sender_name` fields in Elasticsearch

**Benefits of Elasticsearch Cache:**
- ✅ **Persistent across deployments**: Cache survives container restarts and redeployments
- ✅ **Shared between instances**: All Cloud Run instances access the same cache
- ✅ **Minimal API calls**: Only calls Periskope API once per unique chat_id
- ✅ **Fast lookups**: Elasticsearch provides instant lookups
- ✅ **No API rate limit issues**: Significantly reduces API usage
- ✅ **Cloud Run compatible**: No local file storage needed

### Enriched Fields

Each message document in Elasticsearch will have:
- `chat_name`: Human-readable chat or group name (e.g., "John Doe", "Marketing Team")
- `sender_name`: Contact name of the sender (for incoming messages)
- All original webhook fields (chat_id, sender_phone, body, etc.)

## Webhook Events

Currently handles:
- `message.created` - New messages
- `message.ack.updated` - Message acknowledgment updates

You can extend the logic in the `/periskopewebhook` endpoint to process other events as needed.

## Frontend Integration

The enriched data makes the frontend display much cleaner:
- Shows actual contact/group names instead of phone numbers
- No complex formatting logic needed in the frontend
- Improved user experience with recognizable names
# webhooks
