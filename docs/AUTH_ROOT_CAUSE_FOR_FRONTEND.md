# Authentication Root Cause Analysis - For Frontend Team

**Date**: 2026-11-07  
**Issue**: 401 Unauthorized despite valid credentials  
**Status**: ✅ RESOLVED

## Root Cause

The application uses **Django REST Framework TokenAuthentication**, NOT JWT (JSON Web Tokens).

### ❌ What Was Wrong

**Attempted (Incorrect)**:
```bash
# JWT approach (WRONG)
POST /api/token/  # This endpoint doesn't exist
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### ✅ Correct Authentication Flow

**Correct DRF Token Flow**:
```bash
# Step 1: Login
POST /api/usuarios/login-proveedor/
Content-Type: application/json

{
  "username": "your_username",
  "password": "your_password"
}

# Response
{
  "token": "d49c0e7a5da18acc3d71c0b6e7f8a2b9c3d4e5f6",
  "user": {
    "id": 123,
    "username": "your_username",
    "email": "user@example.com",
    ...
  },
  "requiere_consentimiento": false,
  "version_documento_legal": "1.0"
}

# Step 2: Use Token
GET /api/ordenes/proveedor-ordenes/
Authorization: Token d49c0e7a5da18acc3d71c0b6e7f8a2b9c3d4e5f6
```

## Key Differences

| Aspect | JWT (❌ Incorrect) | DRF Token (✅ Correct) |
|--------|-------------------|----------------------|
| **Login Endpoint** | `/api/token/` or `/api/auth/login/` | `/api/usuarios/login-proveedor/` |
| **Token Format** | Three-part base64 (header.payload.signature) | Single hex string (40 chars) |
| **Header Prefix** | `Bearer` | `Token` |
| **Token Storage** | Generated with JWT library | Database model `authtoken_token` |
| **Expiration** | Built-in expiry (exp claim) | No expiry (rotate on login) |

## Backend Configuration

**File**: `mecanimovilapp/settings.py`

```python
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        # ⚠️ NOTE: NO JWT authentication configured
    ],
    ...
}
```

**No JWT packages installed or configured**. The app uses DRF's built-in Token model.

## Implementation Examples

### Python (requests)

```python
import requests

# Login
response = requests.post(
    'http://localhost:8000/api/usuarios/login-proveedor/',
    json={
        'username': 'test_taller',
        'password': 'test123'
    }
)
data = response.json()
token = data['token']

# Authenticated request
headers = {'Authorization': f'Token {token}'}
response = requests.get(
    'http://localhost:8000/api/ordenes/proveedor-ordenes/',
    headers=headers
)
```

### JavaScript (fetch)

```javascript
// Login
const loginResponse = await fetch('http://localhost:8000/api/usuarios/login-proveedor/', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    username: 'test_taller',
    password: 'test123'
  })
});
const { token, user } = await loginResponse.json();

// Authenticated request
const ordersResponse = await fetch('http://localhost:8000/api/ordenes/proveedor-ordenes/', {
  headers: {
    'Authorization': `Token ${token}`
  }
});
```

### cURL

```bash
# Login
TOKEN=$(curl -s -X POST http://localhost:8000/api/usuarios/login-proveedor/ \
  -H "Content-Type: application/json" \
  -d '{"username":"test_taller","password":"test123"}' \
  | jq -r '.token')

# Authenticated request
curl -H "Authorization: Token $TOKEN" \
  http://localhost:8000/api/ordenes/proveedor-ordenes/
```

## Login Endpoints

| User Type | Endpoint | Notes |
|-----------|----------|-------|
| **Taller/Workshop** | `/api/usuarios/login-proveedor/` | Main provider login |
| **Cliente/Customer** | `/api/usuarios/login/` | Customer app login |
| **Google OAuth** | `/api/usuarios/google-login/` | Google Sign-In |
| **Google OAuth (Provider)** | `/api/usuarios/google-login-proveedor/` | Google for providers |

**Use `/api/usuarios/login-proveedor/` for taller/workshop users.**

## Token Lifecycle

1. **Creation**: Token created on first login
2. **Rotation**: Previous token deleted, new one created on each login
3. **Persistence**: Token stored in database (`authtoken_token` table)
4. **Expiration**: No automatic expiry (unlike JWT)
5. **Invalidation**: Deleted on logout or new login

## Common Errors

### 401 Unauthorized

**Symptoms**:
```json
{
  "detail": "Las credenciales de autenticación no se proveyeron."
}
```

**Causes**:
1. Missing `Authorization` header
2. Wrong prefix (`Bearer` instead of `Token`)
3. Invalid/expired token
4. Token not in database

**Solution**: Use `Authorization: Token <key>` with valid token from login response.

### 403 Forbidden (Provider Login Rejected)

**Symptoms**:
```json
{
  "non_field_errors": [
    "Esta cuenta es de proveedor. Por favor, utiliza la aplicación de proveedores para iniciar sesión."
  ]
}
```

**Cause**: Trying to log in to customer endpoint (`/api/usuarios/login/`) with provider account.

**Solution**: Use `/api/usuarios/login-proveedor/` for taller/mechanic users.

## Verified Test Results

**File**: `scripts/login_and_test.py`

```
TEST 1: Login as Taller Owner ✅
TEST 2: List Orders (Authenticated) ✅
TEST 3: Accept Order ✅
TEST 4: Assign Technician ✅
TEST 5: Login as Mechanic ✅
```

All HTTP tests pass with correct Token authentication.

## Migration Guide

If your frontend code currently uses JWT:

### Before (JWT - ❌)
```javascript
// ❌ Wrong endpoint
const response = await fetch('/api/token/', {
  method: 'POST',
  body: JSON.stringify({ username, password })
});
const { access } = await response.json();

// ❌ Wrong header prefix
headers: { 'Authorization': `Bearer ${access}` }
```

### After (DRF Token - ✅)
```javascript
// ✅ Correct endpoint
const response = await fetch('/api/usuarios/login-proveedor/', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username, password })
});
const { token } = await response.json();

// ✅ Correct header prefix
headers: { 'Authorization': `Token ${token}` }
```

## Security Notes

1. **Transport**: Always use HTTPS in production
2. **Storage**: Store token securely (encrypted storage, not localStorage for sensitive apps)
3. **Rotation**: Token rotates on each login (old tokens invalidated)
4. **Logout**: Call `/api/usuarios/logout/` to delete token from server
5. **No Expiry**: Unlike JWT, DRF tokens don't expire automatically - implement app-level timeout if needed

## Test Credentials (Development Only)

```
Username: test_taller_http
Password: test123
Endpoint: POST /api/usuarios/login-proveedor/
```

**⚠️ These credentials are for localhost testing only. Never use in production.**

## Summary for Frontend Team

**Action Items**:
1. ✅ Change login endpoint to `/api/usuarios/login-proveedor/`
2. ✅ Extract `token` field from response (not `access` or `access_token`)
3. ✅ Use `Authorization: Token <key>` header (not `Bearer`)
4. ✅ Remove any JWT library dependencies (not needed)
5. ✅ Test against localhost:8000 with provided test credentials

**Expected Behavior**:
- Login returns `{ token: "...", user: {...} }`
- All subsequent requests use `Authorization: Token <token>`
- 200 OK responses for authenticated endpoints
- 401 only if token missing/invalid or user not provider

## Contact

If authentication still fails after implementing these changes:
1. Verify backend is running on correct port (8000)
2. Check network tab for actual request/response
3. Confirm `Authorization` header is present and correctly formatted
4. Test with provided test credentials first
5. Share exact error response for debugging

---

**Status**: Backend authentication fully working and verified.  
**Verified**: 2026-11-07 with localhost HTTP tests.  
**Test Suite**: 89/89 tests passing.
