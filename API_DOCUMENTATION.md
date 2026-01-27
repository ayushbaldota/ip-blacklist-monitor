# IP Blacklist Monitor API Documentation

## Overview

The IP Blacklist Monitor is a RESTful API service that monitors IP addresses against DNS-based blacklists (DNSBLs). Built with FastAPI, it provides comprehensive IP monitoring, blacklist checking, and alerting capabilities.

**Base URL:** `/api/v1`

**Built-in Documentation:**
- Swagger UI: `/docs`
- ReDoc: `/redoc`
- OpenAPI Schema: `/openapi.json`

---

## Authentication

All endpoints (except `/health` and `/`) require API key authentication.

### Header

```
X-API-Key: <your-api-key>
```

### Permissions

| Permission | Description |
|------------|-------------|
| `read` | Access to GET endpoints |
| `write` | Access to POST/DELETE endpoints |

---

## Rate Limiting

| Endpoint | Limit |
|----------|-------|
| `POST /ips` | 30/minute |
| `POST /ips/bulk` | 10/minute |
| `POST /ips/{ip_id}/check` | 10/minute |
| `DELETE /ips/{ip_id}` | 30/minute |
| All other endpoints | 60/minute |

When rate limited, the API returns `429 Too Many Requests`.

---

## Response Format

### Success Response

```json
{
  "data": { },
  "message": "Optional success message"
}
```

### Error Response

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message",
    "details": { }
  },
  "request_id": "unique-request-id"
}
```

### HTTP Status Codes

| Code | Description |
|------|-------------|
| 200 | Successful GET operation |
| 201 | Resource created |
| 202 | Async operation queued |
| 400 | Validation error |
| 401 | Missing/invalid API key |
| 403 | Insufficient permissions |
| 404 | Resource not found |
| 409 | Resource already exists |
| 429 | Rate limit exceeded |
| 500 | Internal server error |

---

## Endpoints

### Root

#### `GET /`

Returns basic API information.

**Authentication:** Not required

**Response:**

```json
{
  "name": "IP Blacklist Monitor",
  "version": "1.0.0",
  "docs": "/docs",
  "health": "/api/v1/health"
}
```

---

### Health & Statistics

#### `GET /api/v1/health`

Check the health status of all system components.

**Authentication:** Not required

**Response:**

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2024-01-27T10:00:00+00:00",
  "checks": {
    "database": {
      "status": "healthy",
      "latency_ms": 5,
      "error": null,
      "next_run": null
    },
    "scheduler": {
      "status": "healthy",
      "latency_ms": null,
      "error": null,
      "next_run": "2024-01-27T13:00:00+00:00"
    },
    "slack": {
      "status": "healthy",
      "latency_ms": null,
      "error": null,
      "next_run": null
    }
  }
}
```

---

#### `GET /api/v1/stats`

Get aggregate statistics about monitored IPs and checks.

**Authentication:** Required (read permission)

**Response:**

```json
{
  "data": {
    "ips": {
      "total": 5,
      "active": 5,
      "clean": 3,
      "blacklisted": 1,
      "pending": 1
    },
    "checks": {
      "last_run": "2024-01-27T09:00:00+00:00",
      "next_run": "2024-01-27T12:00:00+00:00",
      "checks_today": 5,
      "status_changes_today": 1
    },
    "providers": {
      "total": 14,
      "zones": [
        "zen.spamhaus.org",
        "dnsbl-1.uceprotect.net",
        "bl.spamcop.net",
        "..."
      ]
    }
  }
}
```

---

### IP Management

#### `POST /api/v1/ips`

Add a new IP address to monitor.

**Authentication:** Required (write permission)

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `ip_address` | string | Yes | IPv4 or IPv6 address |
| `description` | string | No | Description (max 255 chars) |

**Example Request:**

```json
{
  "ip_address": "192.168.1.1",
  "description": "Mail server"
}
```

**Response (201 Created):**

```json
{
  "data": {
    "id": 1,
    "ip_address": "192.168.1.1",
    "ip_version": 4,
    "description": "Mail server",
    "status": "pending",
    "last_checked": null,
    "blacklist_sources": [],
    "is_active": true,
    "created_at": "2024-01-27T10:00:00+00:00",
    "updated_at": "2024-01-27T10:00:00+00:00"
  },
  "message": "IP address added successfully"
}
```

**Errors:**

| Code | Description |
|------|-------------|
| 400 | Invalid IP address format |
| 409 | IP address already exists |

---

#### `POST /api/v1/ips/bulk`

Add multiple IP addresses in a single request.

**Authentication:** Required (write permission)

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `ips` | array | Yes | Array of IP objects (1-100 items) |
| `ips[].ip_address` | string | Yes | IPv4 or IPv6 address |
| `ips[].description` | string | No | Description (max 255 chars) |

**Example Request:**

```json
{
  "ips": [
    { "ip_address": "192.168.1.1", "description": "Server 1" },
    { "ip_address": "10.0.0.1", "description": "Server 2" }
  ]
}
```

**Response (201 Created):**

```json
{
  "data": {
    "added": 2,
    "skipped": 0,
    "results": [
      {
        "ip_address": "192.168.1.1",
        "status": "added",
        "id": 1,
        "reason": null
      },
      {
        "ip_address": "10.0.0.1",
        "status": "added",
        "id": 2,
        "reason": null
      }
    ]
  },
  "message": "Bulk operation completed"
}
```

---

#### `GET /api/v1/ips`

List all monitored IP addresses with filtering and pagination.

**Authentication:** Required (read permission)

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | int | 1 | Page number (min: 1) |
| `per_page` | int | 20 | Items per page (1-100) |
| `status` | string | - | Filter: `pending`, `clean`, `blacklisted` |
| `is_active` | bool | true | Filter by active status |
| `sort_by` | string | `created_at` | Sort field |
| `sort_order` | string | `desc` | `asc` or `desc` |
| `search` | string | - | Search in IP or description |

**Example Request:**

```
GET /api/v1/ips?status=blacklisted&page=1&per_page=10
```

**Response (200 OK):**

```json
{
  "data": {
    "items": [
      {
        "id": 1,
        "ip_address": "192.168.1.1",
        "ip_version": 4,
        "description": "Mail server",
        "status": "clean",
        "last_checked": "2024-01-27T09:00:00+00:00",
        "blacklist_sources": [],
        "is_active": true,
        "created_at": "2024-01-27T08:00:00+00:00",
        "updated_at": "2024-01-27T09:00:00+00:00"
      }
    ],
    "pagination": {
      "page": 1,
      "per_page": 20,
      "total_items": 5,
      "total_pages": 1,
      "has_next": false,
      "has_prev": false
    }
  }
}
```

---

#### `GET /api/v1/ips/lookup`

Look up an IP address by its value.

**Authentication:** Required (read permission)

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `ip` | string | Yes | IP address to look up |

**Example Request:**

```
GET /api/v1/ips/lookup?ip=192.168.1.1
```

**Response (200 OK):**

```json
{
  "data": {
    "id": 1,
    "ip_address": "192.168.1.1",
    "ip_version": 4,
    "description": "Mail server",
    "status": "clean",
    "last_checked": "2024-01-27T09:00:00+00:00",
    "blacklist_sources": [],
    "is_active": true,
    "created_at": "2024-01-27T08:00:00+00:00",
    "updated_at": "2024-01-27T09:00:00+00:00"
  }
}
```

**Errors:**

| Code | Description |
|------|-------------|
| 400 | Invalid IP address format |
| 404 | IP address not found |

---

#### `GET /api/v1/ips/{ip_id}`

Get a specific IP address by its database ID.

**Authentication:** Required (read permission)

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `ip_id` | int | IP record ID |

**Response (200 OK):**

```json
{
  "data": {
    "id": 1,
    "ip_address": "192.168.1.1",
    "ip_version": 4,
    "description": "Mail server",
    "status": "clean",
    "last_checked": "2024-01-27T09:00:00+00:00",
    "blacklist_sources": [],
    "is_active": true,
    "created_at": "2024-01-27T08:00:00+00:00",
    "updated_at": "2024-01-27T09:00:00+00:00"
  }
}
```

**Errors:**

| Code | Description |
|------|-------------|
| 404 | IP address not found |

---

#### `DELETE /api/v1/ips/{ip_id}`

Remove an IP address from monitoring.

**Authentication:** Required (write permission)

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `ip_id` | int | IP record ID |

**Response (200 OK):**

```json
{
  "data": {
    "id": 1,
    "ip_address": "192.168.1.1",
    "deleted_at": "2024-01-27T10:00:00+00:00"
  },
  "message": "IP address removed successfully"
}
```

**Errors:**

| Code | Description |
|------|-------------|
| 404 | IP address not found |

---

### Check History

#### `GET /api/v1/ips/{ip_id}/history`

Get the blacklist check history for an IP address.

**Authentication:** Required (read permission)

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `ip_id` | int | IP record ID |

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | int | 1 | Page number (min: 1) |
| `per_page` | int | 50 | Items per page (1-200) |
| `from_date` | datetime | - | Filter from this date (ISO 8601) |
| `to_date` | datetime | - | Filter to this date (ISO 8601) |

**Response (200 OK):**

```json
{
  "data": {
    "ip_id": 1,
    "ip_address": "192.168.1.1",
    "current_status": "clean",
    "history": [
      {
        "id": 1,
        "status": "clean",
        "blacklist_sources": [],
        "check_duration_ms": 1234,
        "checked_at": "2024-01-27T09:00:00+00:00"
      }
    ],
    "pagination": {
      "page": 1,
      "per_page": 50,
      "total_items": 1,
      "total_pages": 1,
      "has_next": false,
      "has_prev": false
    },
    "summary": {
      "total_checks": 1,
      "times_blacklisted": 0,
      "times_clean": 1,
      "first_check": "2024-01-27T09:00:00+00:00",
      "blacklist_rate_percent": 0.0
    }
  }
}
```

**Errors:**

| Code | Description |
|------|-------------|
| 404 | IP address not found |

---

### Manual Checks

#### `POST /api/v1/ips/{ip_id}/check`

Trigger an immediate blacklist check for an IP address.

**Authentication:** Required (write permission)

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `ip_id` | int | IP record ID |

**Response (202 Accepted):**

```json
{
  "data": {
    "id": 1,
    "ip_address": "192.168.1.1",
    "check_id": "chk_abc1234567890",
    "status": "queued"
  },
  "message": "Blacklist check queued"
}
```

The check runs asynchronously. Query the IP or its history to get results.

**Errors:**

| Code | Description |
|------|-------------|
| 404 | IP address not found |

---

## Data Models

### IP Status Values

| Status | Description |
|--------|-------------|
| `pending` | IP added but not yet checked |
| `clean` | Not found on any blacklist |
| `blacklisted` | Found on one or more blacklists |

### Blacklist Source Object

When an IP is blacklisted, the `blacklist_sources` array contains:

```json
{
  "zone": "zen.spamhaus.org",
  "listed": true,
  "response": "127.0.0.2",
  "checked_at": "2024-01-27T09:00:00+00:00"
}
```

---

## DNSBL Providers

The service checks against 14 DNS-based blacklists:

| Provider | Zone |
|----------|------|
| Spamhaus | zen.spamhaus.org |
| UCEProtect L1 | dnsbl-1.uceprotect.net |
| UCEProtect L2 | dnsbl-2.uceprotect.net |
| UCEProtect L3 | dnsbl-3.uceprotect.net |
| SpamRATS Dyna | dyna.spamrats.com |
| SpamRATS NoPtr | noptr.spamrats.com |
| SpamRATS Spam | spam.spamrats.com |
| Barracuda | b.barracudacentral.org |
| SpamCop | bl.spamcop.net |
| SORBS | dnsbl.sorbs.net |
| PSBL | psbl.surriel.com |
| CBL | cbl.abuseat.org |
| Blocklist.de | bl.blocklist.de |
| DroneBL | dnsbl.dronebl.org |

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | development | Environment mode |
| `DEBUG` | false | Enable debug mode |
| `API_HOST` | 0.0.0.0 | Server host |
| `API_PORT` | 8000 | Server port |
| `DATABASE_URL` | - | PostgreSQL connection string |
| `DNSBL_TIMEOUT` | 5 | DNS query timeout (seconds) |
| `SLACK_ENABLED` | false | Enable Slack notifications |
| `SLACK_WEBHOOK_URL` | - | Slack webhook URL |
| `SCHEDULER_ENABLED` | true | Enable automatic checks |
| `CHECK_INTERVAL_HOURS` | 3 | Check interval |
| `RATE_LIMIT_PER_MINUTE` | 60 | Default rate limit |
| `HISTORY_RETENTION_DAYS` | 7 | History retention period |

---

## Examples

### cURL Examples

**Add an IP:**

```bash
curl -X POST "http://localhost:8000/api/v1/ips" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"ip_address": "192.168.1.1", "description": "Mail server"}'
```

**List blacklisted IPs:**

```bash
curl "http://localhost:8000/api/v1/ips?status=blacklisted" \
  -H "X-API-Key: your-api-key"
```

**Trigger a check:**

```bash
curl -X POST "http://localhost:8000/api/v1/ips/1/check" \
  -H "X-API-Key: your-api-key"
```

**Check health:**

```bash
curl "http://localhost:8000/api/v1/health"
```

---

## Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `VALIDATION_ERROR` | 400 | Request validation failed |
| `INVALID_IP_FORMAT` | 400 | Invalid IP address format |
| `UNAUTHORIZED` | 401 | Missing or invalid API key |
| `FORBIDDEN` | 403 | Insufficient permissions |
| `NOT_FOUND` | 404 | Resource not found |
| `IP_ALREADY_EXISTS` | 409 | IP address already monitored |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many requests |
| `INTERNAL_ERROR` | 500 | Internal server error |
