# Structural Validation API Specification

This API allows developers to integrate SOoL structural validation into their applications.  It exposes endpoints for checking Minimum Legal Chain (MLC) completeness and detecting contradiction types.

## Base URL

```
POST /api/v1
```

## Authentication

Authentication is left to the implementer.  In secure deployments, use OAuth or API keys.

## Endpoints

### POST `/mlc/validate`

Validate an MLC record against the completeness criteria and detect contradictions.

- **Request Body:** JSON object conforming to `MLC-schema.json`.
- **Response:**

```json
{
  "complete": true,
  "validity": {
    "authority": true,
    "jurisdiction": true,
    "role": false,
    "norm": true,
    "process": true,
    "event": true,
    "recognition": true,
    "remedy": true
  },
  "contradictions": [
    {
      "type": "Type 3",
      "name": "Role Contradiction",
      "family": "Authority",
      "message": "Actor does not hold required role."
    }
  ]
}
```

- **HTTP Status Codes:**
  - `200 OK` – validation completed.
  - `400 Bad Request` – invalid JSON or missing fields.

### GET `/health`

Returns a simple status to confirm the service is running.

```json
{ "status": "ok" }
```

## Data Formats

- Input and output are `application/json`.
- JSON schema is provided in `Module2_MLC/MLC-schema.json` for request validation.

## Error Handling

Errors return an object with `error` and `message` fields.  For example:

```json
{ "error": "ValidationError", "message": "Missing property: role" }
```

## Integration Tips

- Validate your JSON client-side against the schema before sending.
- Use the contradiction messages to inform users of specific structural issues.
- To support linked data, consider exposing RDF representations with SHACL validation reports.

