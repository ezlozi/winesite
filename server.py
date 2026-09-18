"""WINN website and Discord OAuth2 backend with persistent SQLite profiles."""
import http.cookies
import json
import os
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "winn.db")


def load_dotenv():
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8-sig") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


load_dotenv()
CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "http://localhost:8000/auth/callback")
SERVER_ADDRESS = os.environ.get("MINECRAFT_SERVER_ADDRESS", "winnsmp.minerent.io")
MCSTAT_API_KEY = os.environ.get("MCSTAT_API_KEY", "")
MCSTAT_BASE_URL = "https://mcstat.org/api/v1/servers"
STATES = {}


def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with db() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                discord_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                global_name TEXT,
                avatar TEXT,
                email TEXT,
                hours_played INTEGER NOT NULL DEFAULT 0,
                builds_count INTEGER NOT NULL DEFAULT 0,
                server_rank TEXT NOT NULL DEFAULT '#—',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                discord_id TEXT NOT NULL REFERENCES users(discord_id),
                expires_at INTEGER NOT NULL
            );
        """)


def current_user(token):
    if not token:
        return None
    with db() as connection:
        row = connection.execute("""
            SELECT u.discord_id, u.username, u.global_name, u.avatar, u.email,
                   u.hours_played, u.builds_count, u.server_rank
            FROM sessions s JOIN users u ON u.discord_id = s.discord_id
            WHERE s.token = ? AND s.expires_at > ?
        """, (token, int(time.time()))).fetchone()
        return dict(row) if row else None


def create_session(discord_id):
    token = secrets.token_urlsafe(48)
    with db() as connection:
        connection.execute(
            "INSERT INTO sessions (token, discord_id, expires_at) VALUES (?, ?, ?)",
            (token, discord_id, int(time.time()) + 604800),
        )
    return token


class WinnHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def cookies(self):
        result = http.cookies.SimpleCookie()
        result.load(self.headers.get("Cookie", ""))
        return result

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/auth/discord":
            if not CLIENT_ID or not CLIENT_SECRET:
                self.send_json({"error": "OAuth не настроен. Проверьте .env"}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            state = secrets.token_urlsafe(32)
            STATES[state] = time.time()
            query = urllib.parse.urlencode({
                "client_id": CLIENT_ID, "response_type": "code",
                "redirect_uri": REDIRECT_URI, "scope": "identify email", "state": state,
            })
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", f"https://discord.com/oauth2/authorize?{query}")
            self.send_header("Set-Cookie", f"winn_oauth_state={state}; HttpOnly; SameSite=Lax; Path=/; Max-Age=600")
            self.end_headers()
            return
        if path == "/auth/callback":
            self.callback(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
            return
        if path == "/api/session":
            cookie = self.cookies().get("winn_session")
            user = current_user(cookie.value if cookie else None)
            self.send_json({"authenticated": bool(user), "user": user})
            return
        if path in ("/api/server-status", "/api/status"):
            self.server_status()
            return
        super().do_GET()

    def server_status(self):
        if not MCSTAT_API_KEY:
            self.send_json({"error": "MCStat API key is not configured"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        try:
            api_url = MCSTAT_BASE_URL + "/servers?" + urllib.parse.urlencode({
                "search": SERVER_ADDRESS, "limit": 20,
            })
            request = urllib.request.Request(api_url, headers={
                "X-API-Key": MCSTAT_API_KEY, "User-Agent": "WINN-Server-Status/1.0",
            })
            with urllib.request.urlopen(request, timeout=8) as response:
                result = json.load(response)
            servers = result.get("data", {}).get("servers", [])
            match = next((item for item in servers if item.get("ip", "").lower() == SERVER_ADDRESS.lower()), None)
            if not match:
                self.send_json({"address": SERVER_ADDRESS, "online": False, "players": 0,
                                "max_players": 0, "version": "не найден", "motd": "",
                                "ping": None, "error": "Сервер не найден в MCStat"}, HTTPStatus.NOT_FOUND)
                return
            self.send_json({
                "address": SERVER_ADDRESS,
                "online": bool(match.get("isOnline")),
                "players": match.get("currentPlayers", 0),
                "max_players": match.get("maxPlayers", 0),
                "version": match.get("version") or "неизвестно",
                "motd": match.get("motd", ""),
                "ping": match.get("latency"),
                "source": "mcstat.org",
            })
        except urllib.error.HTTPError as error:
            print(f"MCStat error {error.code}: {error.read().decode('utf-8', errors='replace')}", flush=True)
            self.send_json({"error": f"MCStat вернул HTTP {error.code}"}, HTTPStatus.BAD_GATEWAY)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"Server status error: {error}", flush=True)
            self.send_json({
                "address": SERVER_ADDRESS, "online": False, "players": 0,
                "max_players": 0, "version": "недоступен", "motd": "",
                "ping": None, "error": "Не удалось получить статус сервера",
            }, HTTPStatus.BAD_GATEWAY)

    def callback(self, query):
        state = query.get("state", [None])[0]
        code = query.get("code", [None])[0]
        oauth_cookie = self.cookies().get("winn_oauth_state")
        issued = STATES.pop(state, None) if state else None
        if not state or not oauth_cookie or oauth_cookie.value != state or issued is None or time.time() - issued > 600:
            self.send_json({"error": "OAuth state недействителен. Начните вход заново."}, HTTPStatus.BAD_REQUEST)
            return
        if not code:
            self.send_json({"error": "Discord не вернул код авторизации."}, HTTPStatus.BAD_REQUEST)
            return
        try:
            token_request = urllib.request.Request(
                "https://discord.com/api/oauth2/token",
                data=urllib.parse.urlencode({
                    "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                    "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI,
                }).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            token = json.load(urllib.request.urlopen(token_request, timeout=10))
            user_request = urllib.request.Request(
                "https://discord.com/api/users/@me",
                headers={"Authorization": "Bearer " + token["access_token"]},
            )
            user = json.load(urllib.request.urlopen(user_request, timeout=10))
            avatar = None
            if user.get("avatar"):
                avatar = f"https://cdn.discordapp.com/avatars/{user['id']}/{user['avatar']}.png?size=128"
            with db() as connection:
                connection.execute("""
                    INSERT INTO users (discord_id, username, global_name, avatar, email, last_login_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(discord_id) DO UPDATE SET
                        username=excluded.username, global_name=excluded.global_name,
                        avatar=excluded.avatar, email=excluded.email,
                        last_login_at=CURRENT_TIMESTAMP
                """, (user["id"], user.get("username", "Игрок"), user.get("global_name"),
                      avatar, user.get("email")))
            session = create_session(user["id"])
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"winn_session={session}; HttpOnly; SameSite=Lax; Path=/; Max-Age=604800")
            self.send_header("Set-Cookie", "winn_oauth_state=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
            self.end_headers()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            print(f"Discord OAuth error {error.code}: {detail}", flush=True)
            self.send_json({"error": "Discord отклонил авторизацию. Проверьте Client Secret и Redirect URI."}, HTTPStatus.BAD_GATEWAY)
        except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
            print(f"OAuth callback error: {error}", flush=True)
            self.send_json({"error": "Не удалось сохранить профиль Discord."}, HTTPStatus.BAD_GATEWAY)

    def do_POST(self):
        if self.path == "/auth/logout":
            cookie = self.cookies().get("winn_session")
            if cookie:
                with db() as connection:
                    connection.execute("DELETE FROM sessions WHERE token = ?", (cookie.value,))
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Set-Cookie", "winn_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
            self.end_headers()
            return
        self.send_error(HTTPStatus.NOT_FOUND)


if __name__ == "__main__":
    init_db()
    print(f"WINN is running at http://localhost:8000 (redirect: {REDIRECT_URI})")
    ThreadingHTTPServer(("127.0.0.1", 8000), WinnHandler).serve_forever()
