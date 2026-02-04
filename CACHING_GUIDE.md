# Chat Name Caching - Usage Guide

## Overview

The webhook now features **intelligent group/chat name caching** using Elasticsearch. This eliminates repeated API calls to Periskope and ensures fast lookups.

## Features

✅ **Elasticsearch-based cache** stored in `whatsapp_chat_names` index  
✅ **Automatic caching** when new chats are encountered  
✅ **Bulk fetch endpoint** to pre-populate all group names  
✅ **Optional startup population** to cache all groups when server starts  
✅ **Cloud Run compatible** - fully stateless and scalable  

## How It Works

### 1. Automatic Caching (Default Behavior)

When a webhook message is received:
```
1. Check if chat_id exists in Elasticsearch cache
2. If NOT found → Call Periskope API /chats/{chat_id}
3. Save chat_id and chat_name to cache
4. Use chat_name to enrich the message
5. Index enriched message to Elasticsearch
```

**Result**: Each chat_id is only looked up via API **once**!

### 2. Manual Bulk Cache Population

You can manually trigger a bulk cache refresh by calling:

```bash
curl https://your-webhook-url.run.app/refresh-cache
```

This will:
- Fetch ALL chats from Periskope API (`GET /chats`)
- Cache each chat_id → chat_name mapping
- Return statistics about newly cached vs already cached chats

**Response example**:
```json
{
  "status": "success",
  "total_chats": 150,
  "newly_cached": 45,
  "already_cached": 105
}
```

### 3. Automatic Startup Population (Optional)

Enable in your `.env`:
```bash
CACHE_ON_STARTUP=true
```

When enabled, the server will:
1. Start normally
2. Wait 3 seconds for initialization
3. Fetch all chats from Periskope API in a background thread
4. Cache all group/chat names
5. Continue processing webhooks normally

**Benefits:**
- Cache is warm before first webhook arrives
- Zero latency for first messages
- Runs in background - doesn't block server startup

## Configuration

### Environment Variables

```bash
# Cache index name (matches your configuration)
ELASTICSEARCH_CACHE_INDEX=whatsapp_chat_names

# Optional: Enable startup population
CACHE_ON_STARTUP=true  # or false (default)
```

## API Endpoints

### 1. Root Endpoint
```
GET /
```
Returns: `{"message": "Webhook server is running"}`

### 2. Refresh Cache
```
GET /refresh-cache
```
Fetches all chats from Periskope and caches them.

**Response:**
```json
{
  "status": "success",
  "total_chats": 150,
  "newly_cached": 45,
  "already_cached": 105
}
```

### 3. Webhook Endpoint
```
POST /periskopewebhook
```
Receives Periskope webhooks, enriches with cached chat names.

## Cache Structure

### Elasticsearch Index: `whatsapp_chat_names`

**Document structure:**
```json
{
  "_id": "120363417563833505@g.us",  // chat_id as document ID
  "_source": {
    "chat_id": "120363417563833505@g.us",
    "chat_name": "Marketing Team",
    "@timestamp": "2025-12-10T15:57:00.000Z",
    "updated_at": "2025-12-10T15:57:00.000Z"
  }
}
```

**Index mapping:**
```json
{
  "mappings": {
    "properties": {
      "chat_id": {"type": "keyword"},
      "chat_name": {"type": "text"},
      "@timestamp": {"type": "date"},
      "updated_at": {"type": "date"}
    }
  }
}
```

**Note:** The `@timestamp` field is Elasticsearch's default timestamp field, making the index compatible with time-based queries and Kibana dashboards.

## Usage Scenarios

### Scenario 1: Fresh Deployment
```bash
# Set environment
CACHE_ON_STARTUP=true

# Deploy
uvicorn main:app --reload

# Output:
# 🚀 Pre-populating cache on startup...
# 📦 Cache population started in background thread
# ... (3 seconds later)
# Cached: 120363417563833505@g.us -> Marketing Team
# Cached: 918712645224@c.us -> John Doe
# ✅ Startup cache population completed: {"total_chats": 150, "newly_cached": 150}
```

### Scenario 2: Running System, Want to Refresh
```bash
# Call refresh endpoint
curl https://your-webhook-url/refresh-cache

# Response:
{
  "status": "success",
  "total_chats": 152,
  "newly_cached": 2,      # 2 new chats since last refresh
  "already_cached": 150   # 150 were already in cache
}
```

### Scenario 3: New Webhook Arrives
```
Webhook: message from chat_id = "120363046299481671@g.us"

1. Check cache: SELECT * FROM whatsapp_chat_names WHERE id = "120363046299481671@g.us"
2. If found: Use cached name "Support Team"
3. If not found:
   - Call Periskope API GET /chats/120363046299481671@g.us
   - Get chat_name = "Support Team"
   - Save to cache
4. Enrich message with chat_name = "Support Team"
5. Index to Elasticsearch
```

## Monitoring Cache Performance

### Check cache size
```bash
curl -X GET "/whatsapp_chat_names/_count" \
  -u elastic:password
```

### View cached chats
```bash
curl -X GET "/whatsapp_chat_names/_search?size=100" \
  -u elastic:password
```

### Check for specific chat
```bash
curl -X GET "/whatsapp_chat_names/_doc/120363417563833505@g.us" \
  -u elastic:password
```

## Best Practices

### 1. Enable Startup Cache for Production
```bash
CACHE_ON_STARTUP=true
```
- Ensures warm cache on deployment
- Reduces API calls
- No latency on first webhooks

### 2. Periodic Refresh
Set up a cron job or Cloud Scheduler to refresh cache weekly:
```bash
# Weekly refresh every Monday at 2 AM
0 2 * * 1 curl https://your-webhook/refresh-cache
```

### 3. Monitor Cache Hits
Add logging in your application to track:
- Cache hits vs misses
- API call frequency
- Cache refresh timing

## Troubleshooting

### Cache Not Populating
**Check:**
1. Periskope API credentials are correct
2. Elasticsearch is reachable
3. Index permissions allow writes
4. Check logs for errors

### Slow First Requests
**Solution:**
Enable `CACHE_ON_STARTUP=true`

### Cache Out of Date
**Solution:**
Call `/refresh-cache` endpoint manually or via cron

### Too Many API Calls
**Check:**
1. Cache index exists: `whatsapp_chat_names`
2. Verify cache reads are working
3. Check Elasticsearch connectivity

## Cloud Run Specific Notes

### Auto-scaling Behavior
- ✅ All instances share the same Elasticsearch cache
- ✅ New instances immediately have access to cached names
- ✅ No cold start issues with cache

### Startup Population
- Runs in background thread
- Doesn't block container startup
- Cloud Run health checks pass immediately

### Cost Optimization
- Reduces Periskope API usage significantly
- Minimal Elasticsearch storage cost (KB per chat)
- Fast lookups reduce request processing time
