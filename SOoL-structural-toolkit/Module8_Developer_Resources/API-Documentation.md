# API Documentation

This document provides detailed technical documentation for implementing the SOoL structural validation API (see specification in Module 4).

## Endpoints

### POST `/mlc/validate`

Validate an MLC record and return the results.

- **URL:** `/mlc/validate`
- **Method:** `POST`
- **Content‑Type:** `application/json`
- **Request Body:** JSON conforming to `MLC-schema.json`.
- **Response Body:**

```json
{
  "complete": true,
  "validity": {
    "authority": true,
    "jurisdiction": true,
    "role": true,
    "norm": true,
    "process": true,
    "event": true,
    "recognition": true,
    "remedy": true
  },
  "contradictions": []
}
```

If any link is invalid, the `contradictions` array contains objects with fields `type`, `name`, `family`, and `message`.

### GET `/health`

Returns service status.

- **URL:** `/health`
- **Method:** `GET`
- **Response:** `{ "status": "ok" }`

## Error Codes

| Status | Meaning | JSON Body |
| --- | --- | --- |
| 400 | Bad request / invalid JSON | `{ "error": "ValidationError", "message": "Missing property: role" }` |
| 500 | Internal server error | `{ "error": "ServerError", "message": "Unexpected error" }` |

## Example Client

Python client using `requests`:

```python
import json
import requests

url = 'http://localhost:5000/mlc/validate'
with open('my_mlc_record.json') as f:
    payload = json.load(f)
response = requests.post(url, json=payload)
print(response.json())
```

Ensure you validate the JSON client‑side before making the call to reduce errors.

