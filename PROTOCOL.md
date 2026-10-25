# Urja Meter Ops — Reverse-Engineered Protocol & Architectural Analysis

## 1. Executive Summary

This document details the internal architecture, authentication lifecycle, API endpoints, and data anomalies discovered while reverse-engineering the **Urja Meter Ops** legacy web portal (`https://urja-ops.flockenergy.tech`).

Although the portal was built without a publicly documented developer API, runtime inspection of the browser's network traffic and frontend JavaScript bundles revealed that it is a hybrid **SvelteKit** application powered by an internal JSON RPC / REST subsystem and session-based authentication managed by **Better-Auth**.

---

## 2. System Architecture & Tech Stack

Through network analysis and client-side bundle inspection, the legacy stack was identified as:

| Layer | Implementation Details |
| :--- | :--- |
| **Frontend Framework** | SvelteKit (evidenced by `x-sveltekit-action` headers, `__data.json` routes, and `/_app/immutable/` bundles). |
| **Authentication Engine**| `better-auth` using HTTP-only session cookies. |
| **Internal Data Layer** | Internal JSON endpoints prefixed under `/portal/` and SvelteKit `devalue` serialized page state. |
| **Security Controls** | Origin/Referer CSRF protection on form actions; HMAC-SHA256 request signatures on bulk export endpoints. |

---

## 3. Authentication & Session Lifecycle

### 3.1 Login Flow
The authentication endpoint operates as a standard SvelteKit form action:

* **Method & URL:** `POST https://urja-ops.flockenergy.tech/login`
* **Content-Type:** `application/x-www-form-urlencoded`
* **Required Headers:**
  * `x-sveltekit-action: true`
  * `Origin: https://urja-ops.flockenergy.tech` *(Mandatory: SvelteKit blocks requests lacking matching origin with HTTP 403 `Cross-site POST form submissions are forbidden`)*
  * `Referer: https://urja-ops.flockenergy.tech/login`
* **Request Payload:**
  ```urlencoded
  email=operator%40urja.local&password=urja-ops-2026
  ```
* **Response:**
  * HTTP 200 with JSON payload: `{"type": "redirect", "status": 303, "location": "/meters"}`
  * Sets cookie: `__Secure-better-auth.session_token=<token>; Max-Age=3600; Path=/; HttpOnly; Secure; SameSite=Lax`

### 3.2 Session Persistence & Token Expiry
* The session cookie `__Secure-better-auth.session_token` has a `Max-Age` of **3,600 seconds (1 hour)**.
* **Failure Mode:** When a request is made with an expired or missing session cookie, the server responds with:
  ```json
  HTTP/1.1 401 Unauthorized
  {"error": "unauthorized", "message": "A valid session is required."}
  ```
* **Client Adaptation:** Our API adapter implements transparent re-authentication: if any upstream call returns an HTTP 401, it invokes `login()` and automatically retries the failed request once.

---

## 4. Discovered Upstream Endpoints

### 4.1 Meter Search & Pagination
* **Endpoint:** `GET /portal/meters/search?q={query}&page={page}`
* **Auth:** Requires active session cookie.
* **Query Parameters:**
  * `q` *(string, optional)*: Substring search filter against meter ID or serial number.
  * `page` *(integer, default 1)*: 1-based page index.
* **Response Sample (HTTP 200):**
  ```json
  {
    "data": [
      {
        "meterId": "J100000",
        "serialNo": "SE33962",
        "make": "HPL",
        "phaseType": "single",
        "installStatus": "Decommissioned",
        "dtCode": "DT-001"
      }
    ],
    "page": 1,
    "pageSize": 20,
    "total": 403
  }
  ```
* **Notes:** Capped at 20 items per page (21 total pages). Omits deep hierarchy (zone, feeder, substation).

### 4.2 Consumption Telemetry
* **Endpoint:** `GET /portal/meters/{meter_id}/energy`
* **Auth:** Requires active session cookie.
* **Behavior:** Returns a fixed window of **7 consecutive days of 30-minute interval readings** (337 chronological data points).
* **Response Sample (HTTP 200):**
  ```json
  {
    "data": [
      {
        "timestamp": "23/06/2026 23:30",
        "kwh": "48438.74",
        "kvah": "52313.84",
        "voltR": "226"
      }
    ]
  }
  ```
* **Quirks:** Numeric fields are serialized as strings. Timestamps are formatted as `DD/MM/YYYY HH:mm` (local Indian Standard Time) without timezone indicators.

### 4.3 Distribution Transformers (DTs)
* **Endpoint:** `GET /portal/dts?page={page}`
* **Auth:** Requires active session cookie.
* **Response Sample (HTTP 200):**
  ```json
  {
    "data": [
      {
        "code": "DT-001",
        "name": "Malviya Nagar DT 1",
        "feederCode": "F-001",
        "capacityKva": 100
      }
    ],
    "total": 40,
    "page": 1,
    "pageSize": 20
  }
  ```

### 4.4 Meter Geographic Coordinates
* **Endpoint:** `GET /portal/meters/{meter_id}/geo`
* **Auth:** Requires active session cookie.
* **Behavior:** Returns standalone GPS coordinates for a specific smart meter on the Jaipur electrical grid.
* **Response Sample (HTTP 200):**
  ```json
  {
    "data": {
      "latitude": "26.938961002479868",
      "longitude": "75.83095696146852"
    }
  }
  ```
* **Quirks:** Latitude and longitude are serialized as strings. Returns HTTP 404 `{"error": "not_found", "message": "Meter not found"}` for non-existent meter IDs.

### 4.5 Bulk Export & HMAC-SHA256 Signing Handshake
The portal UI features an "Export all meters" button on the Transformers screen. Decompilation of the client chunk `/_app/immutable/nodes/4.2Bgc2kUI.js` revealed an anti-tamper/anti-replay signing protocol:

1. **Key Fetch:** The browser calls `GET /portal/keys` to retrieve a dynamic secret:
   ```json
   {"data": {"signingSecret": "I3dZPPf5CgTp7JyGNMI8i6z8LFR7TmSR"}}
   ```
2. **Payload Construction:** A signature string is assembled:
   $$\text{Message} = \text{METHOD} + \texttt{"\\n"} + \text{PATH} + \texttt{"\\n"} + \text{QUERY} + \texttt{"\\n"} + \text{TIMESTAMP}$$
   Example:
   ```
   GET
   /portal/export
   page=1
   1792944751
   ```
3. **HMAC Calculation:** The message is hashed using `HMAC-SHA256` with the `signingSecret` and encoded as a lowercase hexadecimal digest.
4. **Execution:** The request is dispatched with custom headers:
   ```http
   GET /portal/export?page=1 HTTP/1.1
   Cookie: __Secure-better-auth.session_token=...
   x-timestamp: 1792944751
   x-signature: 22e624d60a43937fc26260e261fd45736516f053f94d22c34e6df9cd4aa9be0d
   ```
5. **Output:** Returns all **403 smart meters in a single JSON payload**, including complete 7-level hierarchy and geographic coordinates.

---

## 5. Data Quirks & Real-World Inconsistencies

During data audit of the full 403-meter dataset, several data anomalies were identified:

### 5.1 Empty String Hierarchy Codes & Names
Multiple meters contain empty string values `""` instead of `null` or valid identifiers:
* **Missing Circle Codes (6 meters):** Meters `J100011`, `J100074`, `J100097`, `J100116`, `J100170`, `J100265` report `"circle": {"name": "Circle 6", "code": ""}`.
* **Missing Circle Names (5 meters):** Meters `J100218` (`code: "C-01"`), `J100248` (`code: "C-03"`), `J100306` (`code: "C-03"`), `J100370` (`code: "C-05"`), and `J100371` (`code: "C-06"`) have `"circle": {"name": "", "code": "..."}`.
* **Missing Feeder Codes (5 meters):** Meters `J100044`, `J100078`, `J100134`, `J100210`, `J100268` have `"feeder": {"name": "Feeder 5", "code": ""}`.
* **Missing Feeder Names (3 meters):** Meters `J100162` (`code: "F-003"`), `J100257` (`code: "F-018"`), and `J100372` (`code: "F-013"`) have `"feeder": {"name": "", "code": "..."}`.
* **Missing Substation Codes (3 meters):** Meters `J100153`, `J100228`, `J100302` have `"substation": {"name": "Substation 16", "code": ""}`.

**Normalization Applied:** Our schema validator (`models.py`) converts empty/whitespace strings to `null` to avoid downstream validation errors.

### 5.2 DT Naming Collision (`DT-007`)
* In the standard transformer directory, `DT-007` is officially named **`"Sanganer DT 7"`**.
* However, meters `J100400`, `J100401`, and `J100402` associate `dtCode: "DT-007"` with name **`"Old Malviya Nagar Xfmr"`**.
* **Normalization Applied:** The service indexes meters by `dt_code` and preserves the specific sub-network label on the individual meter while mapping the transformer correctly in the grid tree.

### 5.3 Serial Number Syntax
* Multiple meters feature unescaped ampersands in their physical serial numbers (e.g. `L&84997`, `L&34861`).
* Serials for newer meters `J100400`–`402` switch to a `GN...` prefix (Genus), while legacy meters use `SE...`, `GE...`, `HP...`, and `AL...`.

### 5.4 Telemetry Data Types
* In `/portal/meters/{id}/energy`, telemetry values (`kwh`, `kvah`, `voltR`) are returned as strings (`"48438.74"`, `"226"`).
* **Normalization Applied:** Converted to real floating-point numbers (`48438.74`, `226.0`).
* Timestamps (`"23/06/2026 23:30"`) in Indian Standard Time (IST, UTC+05:30) are parsed with `Asia/Kolkata` timezone awareness and converted to standard ISO-8601 UTC strings (`2026-06-23T18:00:00Z`).

---

## 6. Architecture & Integration Strategy

Rather than scraping HTML via brittle DOM selectors, our API adapter wraps the portal's native JSON RPC layer:
1. **Startup / Refresh:** Replicates the verified HMAC export handshake to ingest the complete catalog into memory in under **300ms**.
2. **Resilience / Fallback:** If the bulk route is altered or disabled, the adapter gracefully falls back to paginating `/portal/meters/search` and `/portal/dts`.
3. **Telemetry on Demand:** Telemetry readings are fetched per meter via `/portal/meters/{id}/energy` with clean type conversions.
