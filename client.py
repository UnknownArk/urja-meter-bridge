import hashlib
import hmac
import logging
import os
import time
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger("urja_client")


class UrjaClient:
    """HTTP client adapter for the legacy Urja Meter Ops portal.

    Handles session lifecycle, CSRF protection headers, automated re-login,
    and optional HMAC-SHA256 signature generation for bulk exports.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        email: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 15.0,
    ):
        self.base_url = (base_url or os.getenv("URJA_BASE_URL", "https://urja-ops.flockenergy.tech")).rstrip("/")
        self.email = email or os.getenv("URJA_EMAIL", "operator@urja.local")
        self.password = password or os.getenv("URJA_PASSWORD", "urja-ops-2026")
        self.timeout = timeout
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            follow_redirects=True,
        )
        self._logged_in = False

    def login(self) -> bool:
        """Authenticate against SvelteKit Better-Auth endpoint."""
        login_url = f"{self.base_url}/login"
        headers = {
            "x-sveltekit-action": "true",
            "Origin": self.base_url,
            "Referer": login_url,
        }
        payload = {
            "email": self.email,
            "password": self.password,
        }

        try:
            res = self._client.post("/login", data=payload, headers=headers)
            if res.status_code == 200:
                self._logged_in = True
                logger.info("Successfully authenticated with Urja portal.")
                return True
            logger.error(f"Login failed with status {res.status_code}: {res.text[:150]}")
            return False
        except Exception as e:
            logger.error(f"Error connecting to login endpoint: {e}")
            return False

    def _ensure_authenticated(self) -> None:
        """Ensure an active session exists before executing requests."""
        if not self._logged_in:
            if not self.login():
                raise RuntimeError("Failed to establish session with Urja portal.")

    def _request_with_retry(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> httpx.Response:
        """Execute request with automatic re-login on 401 or session redirect."""
        self._ensure_authenticated()

        res = self._client.request(method, path, headers=headers, params=params)

        # Handle session expiration (401 or redirect back to /login)
        if res.status_code == 401 or (res.status_code == 200 and "/login" in str(res.url)):
            logger.warning("Session token expired or invalid. Re-authenticating...")
            if self.login():
                res = self._client.request(method, path, headers=headers, params=params)
            else:
                raise RuntimeError("Session renewal failed.")

        return res

    def fetch_bulk_export(self) -> List[Dict[str, Any]]:
        """Fetch all meters via the portal's HMAC-SHA256 signed export route."""
        self._ensure_authenticated()

        # Step 1: Retrieve temporary signing key
        keys_res = self._request_with_retry("GET", "/portal/keys")
        if keys_res.status_code != 200:
            raise RuntimeError(f"Failed to fetch signing key: {keys_res.status_code}")

        signing_secret = keys_res.json().get("data", {}).get("signingSecret")
        if not signing_secret:
            raise RuntimeError("Portal returned empty signing secret.")

        # Step 2: Generate HMAC-SHA256 signature
        method = "GET"
        path = "/portal/export"
        query = "page=1"
        timestamp = str(int(time.time()))
        message = f"{method}\n{path}\n{query}\n{timestamp}"

        sig = hmac.new(
            signing_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "x-timestamp": timestamp,
            "x-signature": sig,
        }

        # Step 3: Fetch full dataset
        export_res = self._request_with_retry("GET", f"{path}?{query}", headers=headers)
        if export_res.status_code != 200:
            raise RuntimeError(f"Bulk export request failed with {export_res.status_code}: {export_res.text[:150]}")

        return export_res.json().get("data", [])

    def fetch_meters_paged(self, query: str = "", page: int = 1) -> Dict[str, Any]:
        """Fetch paginated meters using the standard search endpoint (fallback)."""
        res = self._request_with_retry("GET", "/portal/meters/search", params={"q": query, "page": page})
        if res.status_code != 200:
            raise RuntimeError(f"Meter search failed with status {res.status_code}")
        return res.json()

    def fetch_dts_paged(self, page: int = 1) -> Dict[str, Any]:
        """Fetch distribution transformers (DTs) from the portal."""
        res = self._request_with_retry("GET", "/portal/dts", params={"page": page})
        if res.status_code != 200:
            raise RuntimeError(f"Transformers fetch failed with status {res.status_code}")
        return res.json()

    def fetch_energy(self, meter_id: str) -> List[Dict[str, Any]]:
        """Fetch 7-day 30-minute interval energy readings for a meter."""
        path = f"/portal/meters/{meter_id}/energy"
        res = self._request_with_retry("GET", path)

        if res.status_code == 404:
            return []
        if res.status_code != 200:
            raise RuntimeError(f"Energy readings fetch failed for {meter_id} with status {res.status_code}")

        return res.json().get("data", [])

    def fetch_geo(self, meter_id: str) -> Optional[Dict[str, float]]:
        """Fetch latitude and longitude coordinates for a meter."""
        path = f"/portal/meters/{meter_id}/geo"
        res = self._request_with_retry("GET", path)

        if res.status_code == 404:
            return None
        if res.status_code != 200:
            raise RuntimeError(f"Geo coordinates fetch failed for {meter_id} with status {res.status_code}")

        data = res.json().get("data", {})
        return {
            "latitude": float(data.get("latitude", 0.0)),
            "longitude": float(data.get("longitude", 0.0)),
        }

    def close(self) -> None:
        """Close underlying HTTP client connection pool."""
        self._client.close()
