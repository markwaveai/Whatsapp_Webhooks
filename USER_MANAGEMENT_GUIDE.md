# User Management & Authentication Guide

This system uses a **Role-Based Access Control (RBAC)** model backed by **Neo4j** for relationship management and **Elasticsearch** for message storage.

## 1. Architecture Overview

-   **Authentication**: OTP-based login via Periskope API (or Dev/Console fallback).
-   **Session**: JWT (JSON Web Tokens) containing `phone` and `role`.
-   **Database**:
    -   **Neo4j**: Stores `WUser` nodes, `Group` nodes, and `[:HAS_ACCESS]` relationships.
    -   **Elasticsearch**: Stores chat messages and group metadata.
-   **access Control**:
    -   **Admin**: Can see ALL groups and manage users.
    -   **User**: Can ONLY see groups explicitly assigned to them via `HAS_ACCESS`.

---

## 2. Setup & First Steps

### Prerequisites
 Ensure your `.env` file has the following:
```bash
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
JWT_SECRET=your_generated_secret_key
ADMIN_SETUP_SECRET=admin123  # Change this for production
```

### Step 1: Create the First Admin
Since there are no users initially, you must use the "backdoor" endpoint to promote a phone number to Admin.

**Request:**
```bash
curl -X POST http://localhost:8000/admin/setup \
   -H "Content-Type: application/json" \
   -d '{
     "phone": "919876543210", 
     "secret_key": "admin123"
   }'
```
*Replace `919876543210` with your actual phone number.*

### Step 2: Login as Admin
1.  Go to the frontend: `http://localhost:5173`
2.  Enter the Admin phone number.
3.  **Check the Backend Terminal**: You will see a log like:
    `⚠️ [DEV MODE] Failed to send OTP... The OTP is: 123456`
4.  Enter this OTP on the frontend.
5.  You are now logged in as **Admin**.

---

## 3. User Management (Admin Only)

Once you have an Admin token (or you can use `curl` with the JWT header), you can manage other users.

### Create a New User
Adds a user to Neo4j with the `user` role.

**Terminal Command (if you have the JWT):**
*It is often easier to use Postman or a script, but here is the curl format:*
```bash
curl -X POST http://localhost:8000/admin/users \
   -H "Authorization: Bearer YOUR_ADMIN_JWT_TOKEN" \
   -H "Content-Type: application/json" \
   -d '{"phone": "918888888888"}'
```

### Assign a Group to a User
Grants a specific user permission to view a specific WhatsApp group.
This creates the relationship: `(u:WUser)-[:HAS_ACCESS]->(g:Group)`

**Request:**
```bash
curl -X POST http://localhost:8000/admin/assign-group \
   -H "Authorization: Bearer YOUR_ADMIN_JWT_TOKEN" \
   -H "Content-Type: application/json" \
   -d '{
     "phone": "918888888888",
     "chat_id": "12036304859023@g.us"
   }'
```

---

## 4. Frontend Behavior

-   **Admins**: When `fetchGroups()` is called, the backend returns **all** groups found in Elasticsearch.
-   **Users**: When `fetchGroups()` is called:
    1.  The backend queries Neo4j: `MATCH (u:WUser)-[:HAS_ACCESS]->(g:Group)`.
    2.  It gets the list of allowed `chat_id`s.
    3.  It queries Elasticsearch **only** for those specific groups.
    4.  If the user has no assigned groups, they see an empty list.

## 5. Troubleshooting

**"Failed to send OTP via Periskope"**
-   This is expected in development if you haven't bought Periskope credits or configured credentials.
-   **Fix**: Look at the terminal running `uvicorn`. The code prints the OTP there explicitly for this reason.

**"Neo4j not connected"**
-   Ensure your Neo4j Docker container or Desktop app is running.
-   Verify `NEO4J_URI` (usually `bolt://localhost:7687`) and credentials in `.env`.

**"Admins only" Error**
-   The token you are using belongs to a user with `role: 'user'`.
-   Use the `/admin/setup` endpoint to promote your number to admin, then re-login to get a new token with the upgraded role.
