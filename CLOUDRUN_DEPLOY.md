# Cloud Run Deployment Guide

## Prerequisites

1. **Google Cloud Project** with billing enabled
2. **gcloud CLI** installed and authenticated
3. **Elasticsearch instance** accessible from Cloud Run (elkprod.aquaexchange.com)
4. **Periskope API credentials** (Bearer token and Org Phone)

## Quick Deploy

### 1. Set your project and region

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud config set run/region us-central1
```

### 2. Create environment variables file

PERISKOPE_SIGNING_SECRET: "your_signing_secret_here"
PERISKOPE_API_KEY: "your_bearer_token_here"
PERISKOPE_ORG_PHONE: 
ELASTICSEARCH_HOST: 

### 3. Deploy to Cloud Run

# Deploy using source-based deployment
gcloud run deploy whatsapp-webhook \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --env-vars-file env.yaml \
  --memory 512Mi \
  --cpu 1 \
  --timeout 60 \
  --max-instances 10
```

### 4. Get the service URL

```bash
gcloud run services describe whatsapp-webhook \
  --platform managed \
  --region us-central1 \
  --format 'value(status.url)'
```

### 5. Configure Periskope webhook

Go to your Periskope dashboard and set the webhook URL to:
```
https://your-cloud-run-url.run.app/whatsappwebhook
```

## Alternative: Docker-based Deployment

### 1. Build and push Docker image

```bash
# Set your project ID
PROJECT_ID=your-project-id

# Build the image
docker build -t gcr.io/$PROJECT_ID/whatsapp-webhook:latest .

# Push to Google Container Registry
docker push gcr.io/$PROJECT_ID/whatsapp-webhook:latest
```

### 2. Deploy the image

```bash
gcloud run deploy whatsapp-webhook \
  --image gcr.io/$PROJECT_ID/whatsapp-webhook:latest \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --env-vars-file env.yaml \
  --memory 512Mi \
  --cpu 1
```

## Configuration Options

### Memory and CPU

- **Default**: 512Mi memory, 1 CPU
- **High traffic**: Increase to 1Gi memory, 2 CPUs
- **Low traffic**: Can reduce to 256Mi memory, 1 CPU

### Concurrency

```bash
--concurrency 80  # Default: 80 requests per instance
```

### Min/Max Instances

```bash
--min-instances 0  # Scale to zero when idle
--max-instances 10  # Limit scaling
```

### Timeout

```bash
--timeout 60  # 60 seconds (default: 300)
```

## Monitoring

### View logs

```bash
gcloud run services logs read whatsapp-webhook \
  --platform managed \
  --region us-central1 \
  --limit 50
```

### Live tail logs

```bash
gcloud run services logs tail whatsapp-webhook \
  --platform managed \
  --region us-central1
```

## Testing

### Test the webhook locally

```bash
# Start locally with environment variables
uvicorn main:app --reload --port 8080
```

### Test the deployed service

```bash
curl https://your-cloud-run-url.run.app/
# Should return: {"message": "Webhook server is running"}
```

## Troubleshooting

### Check service status

```bash
gcloud run services describe whatsapp-webhook \
  --platform managed \
  --region us-central1
```

### Common Issues

1. **Elasticsearch connection fails**
   - Ensure Elasticsearch is publicly accessible or use Cloud VPC
   - Check firewall rules

2. **Cache index not created**
   - Check Elasticsearch credentials
   - Verify index creation permissions

3. **High latency**
   - Increase min-instances to avoid cold starts
   - Consider moving Elasticsearch to same region

## Cost Optimization

### Free Tier (as of 2024)
- 2 million requests/month
- 360,000 GB-seconds/month
- 180,000 vCPU-seconds/month

### Reduce Costs
1. Set `--min-instances 0` to scale to zero
2. Use `--memory 256Mi` for low traffic
3. Enable request timeout `--timeout 60`

## Security

### Restrict access

```bash
# Remove --allow-unauthenticated
# Add authentication
gcloud run services update whatsapp-webhook \
  --no-allow-unauthenticated \
  --region us-central1
```

### Use Secret Manager

```bash
# Create secrets
echo -n "your_api_key" | gcloud secrets create periskope-api-key --data-file=-

# Deploy with secrets
gcloud run deploy whatsapp-webhook \
  --source . \
  --update-secrets=PERISKOPE_API_KEY=periskope-api-key:latest \
  --region us-central1
```

## Architecture Benefits

✅ **Stateless**: No local storage, fully managed
✅ **Scalable**: Auto-scales from 0 to N instances
✅ **Reliable**: Elasticsearch cache shared across all instances
✅ **Cost-effective**: Pay only for requests
✅ **Persistent**: Cache survives deployments and restarts
