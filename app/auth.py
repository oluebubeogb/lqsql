"""Single-admin auth: HMAC-signed, httpOnly, SameSite=Lax session cookie + custom header CSRF guard."""
import base64
import hashlib
import hmac
import json
import time
from collections import defaultdict, deque

COOKIE = "litesql_session"
CSRF_HEADER = "x-litesql"


class Auth:
    def __init__(self, settings):
        self.s = settings
        self._key = hashlib.sha256(("session:" + settings.secret_key).encode()).digest()
        self._fails: dict[str, deque] = defaultdict(deque)

    def check_password(self, user: str, pw: str) -> bool:
        u = hmac.compare_digest(user.encode(), self.s.admin_user.encode())
        p = hmac.compare_digest(pw.encode(), self.s.admin_password.encode())
        return u and p

    def locked(self, ip: str) -> bool:
        q = self._fails[ip]
        now = time.time()
        while q and now - q[0] > 600:
            q.popleft()
        return len(q) >= 8

    def fail(self, ip: str):
        self._fails[ip].append(time.time())

    def clear(self, ip: str):
        self._fails.pop(ip, None)

    def issue(self) -> str:
        payload = {"u": self.s.admin_user, "exp": int(time.time()) + self.s.session_hours * 3600}
        body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
        sig = hmac.new(self._key, body.encode(), hashlib.sha256).hexdigest()
        return f"{body}.{sig}"

    def verify(self, token: str | None) -> bool:
        if not token or "." not in token:
            return False
        body, sig = token.rsplit(".", 1)
        good = hmac.new(self._key, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good):
            return False
        try:
            data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except Exception:
            return False
        return data.get("u") == self.s.admin_user and int(data.get("exp", 0)) > time.time()
