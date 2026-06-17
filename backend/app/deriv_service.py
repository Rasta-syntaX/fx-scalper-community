from __future__ import annotations

import json
from typing import Optional
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

import requests
from websocket import create_connection


DEFAULT_REST_URL = "https://api.derivws.com"
DEFAULT_WS_URL = "wss://ws.derivws.com/websockets/v3"


class DerivServiceError(RuntimeError):
    pass


class DerivCommunityClient:
    def __init__(
        self,
        *,
        app_id: str,
        token: str,
        rest_url: str = DEFAULT_REST_URL,
        ws_url: str = DEFAULT_WS_URL,
        options_account_mode: str = "demo",
        options_account_id: str = "",
    ) -> None:
        self.app_id = self._normalize_app_id(app_id)
        self.token = self._normalize_token(token)
        self.rest_url = (str(rest_url or DEFAULT_REST_URL).strip() or DEFAULT_REST_URL).rstrip("/")
        self.ws_url = str(ws_url or DEFAULT_WS_URL).strip() or DEFAULT_WS_URL
        self.options_account_mode = str(options_account_mode or "demo").strip().lower() or "demo"
        self.options_account_id = str(options_account_id or "").strip()
        self.ws = None
        self._otp_auth = False
        self._selected_account: Optional[dict] = None

    @staticmethod
    def _normalize_app_id(value: object) -> str:
        raw = str(value or "").strip()
        return raw if raw.isdigit() else "1089"

    @staticmethod
    def _normalize_token(value: object) -> str:
        token = str(value or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        token = token.replace("\u200b", "").replace("\ufeff", "")
        token = "".join(token.split())
        return token

    @property
    def token_mode(self) -> str:
        return "pat" if self.token.startswith("pat_") else "legacy"

    def close(self) -> None:
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
        self.ws = None

    def _ensure_credentials(self) -> None:
        if not self.token:
            raise DerivServiceError("Missing Deriv API token.")
        if not self.app_id:
            raise DerivServiceError("Missing Deriv app ID.")

    def _rest_headers(self) -> dict:
        self._ensure_credentials()
        return {
            "Deriv-App-ID": self.app_id,
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    def _rest_call(self, method: str, path: str, payload: Optional[dict] = None) -> dict:
        url = f"{self.rest_url.rstrip('/')}/{path.lstrip('/')}"
        headers = self._rest_headers()
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = requests.request(method.upper(), url, headers=headers, json=payload, timeout=15)
        except Exception as exc:
            raise DerivServiceError(f"Deriv REST request failed: {exc}") from exc
        try:
            data = response.json() if response.content else {}
        except Exception:
            data = {}
        if response.status_code >= 400:
            message = None
            errors = data.get("errors") if isinstance(data, dict) else None
            if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                message = errors[0].get("message")
            raise DerivServiceError(message or f"Deriv REST error {response.status_code} for {path}")
        return data if isinstance(data, dict) else {}

    def _options_accounts(self) -> list[dict]:
        payload = self._rest_call("GET", "/trading/v1/options/accounts")
        data = payload.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            nested = data.get("accounts") or data.get("items")
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
            return [data]
        return []

    def _create_options_account(self, account_type: str) -> dict:
        payload = self._rest_call(
            "POST",
            "/trading/v1/options/accounts",
            {
                "currency": "USD",
                "group": "row",
                "account_type": account_type,
            },
        )
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        if isinstance(data, dict):
            return data
        raise DerivServiceError("Deriv did not return an options account after create request.")

    @staticmethod
    def _account_id(account: object) -> str:
        if not isinstance(account, dict):
            return ""
        for key in ("account_id", "accountId", "id"):
            value = account.get(key)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _account_type(account: object) -> str:
        if not isinstance(account, dict):
            return ""
        for key in ("account_type", "accountType", "type"):
            value = account.get(key)
            if value:
                return str(value).strip().lower()
        return ""

    def _select_options_account(self) -> dict:
        accounts = self._options_accounts()
        if self.options_account_id:
            for account in accounts:
                if self._account_id(account) == self.options_account_id:
                    return account
        if self.options_account_mode in {"demo", "real"}:
            for account in accounts:
                if self._account_type(account) == self.options_account_mode:
                    return account
        if accounts:
            return accounts[0]
        if self.options_account_mode in {"demo", "real"}:
            return self._create_options_account(self.options_account_mode)
        raise DerivServiceError("No Deriv options account is available for this token.")

    def _otp_ws_url(self, account_id: str) -> str:
        payload = self._rest_call("POST", f"/trading/v1/options/accounts/{account_id}/otp")
        data = payload.get("data")
        ws_url = data.get("url") if isinstance(data, dict) else None
        if not ws_url:
            raise DerivServiceError("Deriv OTP response did not include a WebSocket URL.")
        return str(ws_url)

    def _ws_url_with_app_id(self) -> str:
        parsed = urlparse(self.ws_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["app_id"] = self.app_id
        return urlunparse(parsed._replace(query=urlencode(query)))

    def connect(self) -> dict:
        self.close()
        self._ensure_credentials()
        try:
            if self.token_mode == "pat":
                account = self._select_options_account()
                account_id = self._account_id(account)
                if not account_id:
                    raise DerivServiceError("Unable to resolve a Deriv options account ID.")
                ws_url = self._otp_ws_url(account_id)
                self.ws = create_connection(ws_url, timeout=15)
                self.ws.settimeout(15)
                self._otp_auth = True
                self._selected_account = account
            else:
                self.ws = create_connection(self._ws_url_with_app_id(), timeout=15)
                self.ws.settimeout(15)
                authorize = self.send({"authorize": self.token})
                if "error" in authorize:
                    raise DerivServiceError(authorize["error"].get("message", "Authorization failed."))
                self._selected_account = authorize.get("authorize") or {}
                self._otp_auth = False
            return self.account_snapshot()
        except Exception as exc:
            self.close()
            if isinstance(exc, DerivServiceError):
                raise
            raise DerivServiceError(f"Deriv connection failed: {exc}") from exc

    def send(self, payload: dict) -> dict:
        if self.ws is None:
            raise DerivServiceError("Deriv WebSocket is not connected.")
        try:
            self.ws.send(json.dumps(payload))
            response = self.ws.recv()
            data = json.loads(response)
        except Exception as exc:
            raise DerivServiceError(f"Deriv WebSocket request failed: {exc}") from exc
        if isinstance(data, dict) and "error" in data:
            raise DerivServiceError(data["error"].get("message", "Deriv returned an error."))
        return data if isinstance(data, dict) else {}

    def get_balance(self) -> dict:
        return self.send({"balance": 1}).get("balance") or {}

    def get_active_symbols(self) -> list[dict]:
        return self.send({"active_symbols": "brief", "product_type": "basic"}).get("active_symbols") or []

    def account_snapshot(self) -> dict:
        account = self._selected_account or {}
        balance_info: dict = {}
        try:
            balance_info = self.get_balance()
        except Exception:
            balance_info = {}
        return {
            "token_mode": self.token_mode,
            "app_id": self.app_id,
            "loginid": account.get("loginid") or self._account_id(account),
            "balance": balance_info.get("balance", account.get("balance")),
            "currency": balance_info.get("currency", account.get("currency", "USD")),
            "account_type": account.get("account_type") or self._account_type(account) or ("options" if self._otp_auth else "legacy"),
            "options_account_id": self._account_id(account),
            "connected": True,
        }

    def propose(
        self,
        *,
        symbol: str,
        contract_type: str,
        amount: float,
        duration: int,
        duration_unit: str,
        currency: str,
        basis: str = "stake",
    ) -> dict:
        payload = {
            "proposal": 1,
            "amount": float(amount),
            "basis": basis,
            "contract_type": str(contract_type).strip().upper(),
            "currency": str(currency).strip().upper(),
            "duration": int(duration),
            "duration_unit": str(duration_unit).strip().lower(),
            "underlying_symbol": str(symbol).strip(),
        }
        try:
            return self.send(payload).get("proposal") or {}
        except DerivServiceError as exc:
            if "underlying_symbol" not in str(exc):
                raise
            fallback = dict(payload)
            fallback["symbol"] = fallback.pop("underlying_symbol")
            return self.send(fallback).get("proposal") or {}

    def buy(self, proposal_id: str, price: float) -> dict:
        return self.send({"buy": proposal_id, "price": float(price)}).get("buy") or {}

