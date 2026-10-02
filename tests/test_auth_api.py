"""
API seviyesi testler — `fastapi.testclient.TestClient`.

Mevcut `tests/` paketi API testi içermiyordu (plugin/extractor testleri canlı ağ
kullanıyor). Auth ve sync için bu yeni alışkanlık kuruldu.

Kapsam (SYNC_AUTH_PLAN.md §8.2):
  * Token'sız korumalı uçlar → 401, geçersiz token → 401
  * Gövde doğrulaması → 422, sürüm uyuşmazlığı → 400, fazla kayıt → 413
  * signup → login → me → refresh → logout sözleşme biçimi
  * push/pull sözleşmesi (alan adları, tipler, tombstone, delta, sayfalama)
  * Cihaz listesi / iptal
  * `user_id` izolasyonu  🔴 kritik

Bu testler AĞ GEREKTİRMEZ: GoTrue ve PostgREST yerine sahte yöneticiler
bağlanır. Gerçek Supabase doğrulaması `-m live` işaretli testlerle yapılır;
`SUPABASE_LIVE_TESTS=1` verilmedikçe atlanırlar.

Not: `client` / `anon_client` fixture'ları `TestClient`'ı bağlam yöneticisi
OLMADAN kurar; böylece `lifespan` tetiklenmez ve eklenti yükleme (canlı ağ)
testlere bulaşmaz. `lifespan`'ın kendisi ayrı testlerde bilinçli çalıştırılır.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from supabase_auth.errors import AuthApiError

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from api import app as app_module
from api import deps
from api.app import app
from Core.Libs.SyncModels import SUPPORTED_SCHEMA_VERSION

from tests.test_sync_merge import fake_checkpoint, make_manager


# ══════════════════════════════════════════════════════════════════════════════
# Sahte yöneticiler
# ══════════════════════════════════════════════════════════════════════════════


class FakeAuthManager:
    """GoTrue işlemlerini bellek içinde taklit eder; token'ları elle doğrular."""

    VALID_TOKEN = "gecerli-eytoken"
    VALID_USER_ID = "11111111-2222-3333-4444-555555555555"
    VALID_EMAIL = "test@example.com"

    def __init__(self):
        self.users = {}        # user_id -> kullanıcı sözlüğü
        self.sessions = {}     # refresh_token -> user_id
        self.logged_out = []
        self.password = "sifre123"

    async def sign_up(self, email, password, username, display_name=None):
        user_id = f"user-{len(self.users) + 1}"
        refresh = f"refresh-{user_id}"
        self.users[user_id] = {
            "id": user_id,
            "email": email,
            "username": username,
            "display_name": display_name,
            "created_at": "2026-10-01T12:00:00Z",
        }
        self.sessions[refresh] = user_id
        return self._session(refresh)

    async def sign_in(self, email, password):
        for user in self.users.values():
            if user["email"] == email:
                if password != self.password:
                    # GoTrue'nin durum kodu sürümden sürüme değişebiliyor; sahte
                    # istemci ÜSTÜSTÜ düşülen 401'i kullanır ki üretim
                    # davranışının gerçekten 400'e normalize edildiğini kanıtlasın.
                    raise AuthApiError(
                        "Invalid login credentials", 401, "invalid_credentials"
                    )
                refresh = f"refresh-{user['id']}-{len(self.sessions)}"
                self.sessions[refresh] = user["id"]
                return self._session(refresh)
        raise AuthApiError("Invalid login credentials", 401, "invalid_credentials")

    async def refresh(self, refresh_token):
        user_id = self.sessions.get(refresh_token)
        if not user_id:
            raise AuthApiError(
                "Oturumun süresi doldu.", 401, "refresh_token_not_found"
            )
        return self._session(refresh_token)

    async def logout(self, access_token):
        self.logged_out.append(access_token)

    async def verify_access_token(self, token):
        from Core.Libs.SupabaseAuth import InvalidTokenError

        if token != self.VALID_TOKEN:
            raise InvalidTokenError("Oturum geçersiz.")
        return {"sub": self.VALID_USER_ID, "email": self.VALID_EMAIL, "source": "jwt"}

    async def close(self):
        return None

    def _session(self, refresh_token):
        user_id = self.sessions[refresh_token]
        return {
            "access_token": self.VALID_TOKEN,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": 3600,
            "user": dict(self.users[user_id]),
        }


def _username_taken(manager):
    """Sahte `username_taken`: profil tablosundan kontrol eder."""
    async def check(username, exclude_user_id=None):
        rows = manager._fake_client.store.get("user_profiles", [])
        return any(
            row.get("username") == username and row.get("id") != exclude_user_id
            for row in rows
        )

    return check


@pytest.fixture
def fake_db(monkeypatch):
    """Bellek içi Supabase yöneticisi."""
    manager = make_manager({})
    monkeypatch.setattr(manager, "username_taken", _username_taken(manager))
    return manager


@pytest.fixture
def fake_auth():
    return FakeAuthManager()


@pytest.fixture
def patched(fake_db, fake_auth, monkeypatch):
    """
    Tüm GoTrue/PostgREST bağımlılıklarını sahteye bağlar.

    `api/deps.py` modül içi `get_auth_manager()` çağrısı yaptığı için `deps`
    üzerinden değiştirilir; route modülleri ise adı import ettiği için ayrıca
    `api.routes.auth` üzerinden değiştirilir.
    """
    monkeypatch.setattr(deps, "get_auth_manager", lambda: fake_auth)
    monkeypatch.setattr("api.routes.auth.get_auth_manager", lambda: fake_auth)
    monkeypatch.setattr("api.routes.auth.get_supabase_async", lambda: fake_db)
    monkeypatch.setattr("api.routes.sync.get_supabase_async", lambda: fake_db)

    app.dependency_overrides[deps.get_current_claims] = lambda: {
        "sub": FakeAuthManager.VALID_USER_ID,
        "email": FakeAuthManager.VALID_EMAIL,
        "source": "jwt",
    }
    app.dependency_overrides[deps.get_optional_token] = lambda: FakeAuthManager.VALID_TOKEN
    yield fake_db
    app.dependency_overrides.clear()


@pytest.fixture
def client(patched):
    """Doğrulanmış istemci — korumalı uçlar 200 döner."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def anon_client(fake_db, fake_auth, monkeypatch):
    """Gerçek kimlik doğrulama — 401 davranışını ölçer."""
    monkeypatch.setattr(deps, "get_auth_manager", lambda: fake_auth)
    monkeypatch.setattr("api.routes.auth.get_auth_manager", lambda: fake_auth)
    monkeypatch.setattr("api.routes.auth.get_supabase_async", lambda: fake_db)
    monkeypatch.setattr("api.routes.sync.get_supabase_async", lambda: fake_db)
    return TestClient(app, raise_server_exceptions=False)


AUTH_HEADER = {"Authorization": f"Bearer {FakeAuthManager.VALID_TOKEN}"}


# ══════════════════════════════════════════════════════════════════════════════
# 1. KORUMA — Token'sız ve geçersiz token
# ══════════════════════════════════════════════════════════════════════════════


class TestAuthProtection:
    """Korumalı uçlar token olmadan 401 döner (frontend sessizce refresh dener)."""

    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/api/auth/me"),
            ("GET", "/api/sync/pull"),
            ("GET", "/api/sync/devices"),
            ("POST", "/api/sync/push"),
            ("DELETE", "/api/sync/devices/cihaz-1"),
        ],
    )
    def test_token_siz_istek_401(self, anon_client, method, path):
        response = anon_client.request(method, path, json={} if method == "POST" else None)
        assert response.status_code == 401
        assert response.json()["detail"] == "Oturum geçersiz."

    def test_bozuk_token_401(self, anon_client):
        response = anon_client.get(
            "/api/sync/pull", headers={"Authorization": "Bearer bozuk.token"}
        )
        assert response.status_code == 401

    def test_baska_authorization_seması_401(self, anon_client):
        response = anon_client.get("/api/sync/pull", headers={"Authorization": "Basic abc"})
        assert response.status_code == 401

    def test_logout_token_almazsa_204(self, anon_client):
        """Çıkışta token yoksa da 204 döner; frontend token'ları zaten siler."""
        response = anon_client.post("/api/auth/logout")
        assert response.status_code == 204


# ══════════════════════════════════════════════════════════════════════════════
# 2. AUTH UÇLARI
# ══════════════════════════════════════════════════════════════════════════════


SIGNUP = {
    "email": "Test@Example.com",
    "password": "sifre123",
    "username": "sinemasever",
    "display_name": "Sinema Sever",
}


class TestAuthEndpoints:
    """signup → login → me → refresh → logout akışı."""

    def test_signup_sozlesme_bicimi(self, client):
        response = client.post("/api/auth/signup", json=SIGNUP)
        assert response.status_code == 200

        body = response.json()
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["token_type"] == "bearer"
        assert body["expires_in"] > 0
        assert body["user"]["email"] == "test@example.com"    # küçük harfe normalize
        assert body["user"]["username"] == "sinemasever"
        assert body["user"]["language"] == "tr"
        assert body["user"]["is_private"] is False

    def test_signup_profil_satiri_olusur(self, client, patched):
        client.post("/api/auth/signup", json=SIGNUP)
        profiles = patched._fake_client.store["user_profiles"]
        assert len(profiles) == 1
        assert profiles[0]["username"] == "sinemasever"
        assert profiles[0]["display_name"] == "Sinema Sever"

    def test_kullanici_adi_tekrar_409(self, client):
        client.post("/api/auth/signup", json=SIGNUP)
        response = client.post("/api/auth/signup", json=SIGNUP)
        assert response.status_code == 409
        assert response.json()["detail"] == "Bu kullanıcı adı alınmış."

    @pytest.mark.parametrize(
        "override",
        [
            {"email": "gecersiz"},
            {"password": "123"},
            {"username": "ab"},
            {"username": "Boşluklu Ad"},
        ],
    )
    def test_gecersiz_govde_422(self, client, override):
        response = client.post("/api/auth/signup", json={**SIGNUP, **override})
        assert response.status_code == 422
        # Frontend `body.detail` alanını doğrudan Error mesajı olarak kullanır;
        # bu yüzden `detail` METİN olmalı, FastAPI'nin varsayılan dizisi değil.
        assert isinstance(response.json()["detail"], str)
        assert "geçersiz" in response.json()["detail"]

    def test_422_mesaji_ingilizce_degil(self, client):
        """Pydantic'in İngilizce mesajları sızmamalı (kullanıcı Türkçe görür)."""
        for payload in (
            {"email": "x", "password": "sifre123", "username": "sinemasever"},
            {"email": "test@example.com", "password": "1", "username": "sinemasever"},
            {"email": "test@example.com", "password": "sifre123", "username": "ab"},
        ):
            detail = client.post("/api/auth/signup", json=payload).json()["detail"]
            assert isinstance(detail, str)
            for english in ("String should", "Input should", "Field required",
                            "Invalid ", "at least"):
                assert english not in detail, f"İngilizce mesaj sızdı: {detail}"

    def test_422_ozel_dogrulayici_mesaji_korunur(self, client):
        """Kendi doğrulayıcılarımızın Türkçe mesajı korunmalı."""
        response = client.post(
            "/api/auth/signup",
            json={**SIGNUP, "email": "gecersiz@adres"},
        )
        assert "e-posta" in response.json()["detail"]

    def test_login_ve_token(self, client):
        client.post("/api/auth/signup", json=SIGNUP)
        response = client.post(
            "/api/auth/login",
            json={"email": "test@example.com", "password": "sifre123"},
        )
        assert response.status_code == 200
        assert response.json()["access_token"]

    def test_login_hatali_parola(self, client, fake_auth):
        """
        🔴 401 DEĞİL 400.

        İstemci 401'i "oturum süresi doldu" sanıp sessizce refresh → çıkış
        yapar; yanlış parolada kullanıcı form hatasını göremelidir.
        """
        client.post("/api/auth/signup", json=SIGNUP)
        response = client.post(
            "/api/auth/login",
            json={"email": "test@example.com", "password": "yanlis"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "E-posta veya parola hatalı."

    def test_login_bilinmeyen_eposta_400(self, client):
        response = client.post(
            "/api/auth/login",
            json={"email": "yok@example.com", "password": "sifre123"},
        )
        assert response.status_code == 400

    def test_me_profil_ve_cihaz_dondurur(self, client):
        body = client.get("/api/auth/me", headers=AUTH_HEADER).json()
        assert set(body) == {"user", "devices"}
        assert body["user"]["id"] == FakeAuthManager.VALID_USER_ID
        assert body["user"]["email"] == FakeAuthManager.VALID_EMAIL
        assert body["devices"] == []

    def test_refresh_yeni_token_dondurur(self, client):
        signup = client.post("/api/auth/signup", json=SIGNUP).json()
        response = client.post(
            "/api/auth/refresh", json={"refresh_token": signup["refresh_token"]}
        )
        assert response.status_code == 200
        assert response.json()["access_token"]
        assert response.json()["user"]["username"] == "sinemasever"

    def test_gecersiz_refresh_token_401(self, client):
        """
        🔴 Yenilenemeyen refresh token daima 401 döner.

        İstemci 401'e sessizce yeniden giriş dener, o da olmazsa oturumu
        kapatır — kullanıcıya kurtarma şansı kalır. 400 dönerse "form hatası"
        sanılır ve kırık oturumda kullanıcı kilitlenir.
        """
        for token in ("x" * 20, "v1-refresh-bogus", "not-a-token"):
            response = client.post("/api/auth/refresh", json={"refresh_token": token})
            assert response.status_code == 401, token
            assert "giriş" in response.json()["detail"].lower()

    def test_refresh_govde_dogrulama_422(self, client):
        """Gövde doğrulaması ayrı yoldan 422 döner (401 değil)."""
        response = client.post("/api/auth/refresh", json={"refresh_token": "kisa"})
        assert response.status_code == 422

    def test_logout_204_ve_token_iptali(self, client, fake_auth):
        response = client.post("/api/auth/logout", headers=AUTH_HEADER)
        assert response.status_code == 204
        assert fake_auth.logged_out == [FakeAuthManager.VALID_TOKEN]


# ══════════════════════════════════════════════════════════════════════════════
# 3. SYNC UÇLARI — SÖZLEŞME
# ══════════════════════════════════════════════════════════════════════════════


def push_body(records=None, documents=None, schema_version=None):
    body = {
        "device": {
            "device_id": "cihaz-1",
            "device_name": "Salon TV",
            "platform": "android",
            "app_version": "1.0.0",
        },
        "records": records if records is not None else [],
        "documents": documents if documents is not None else {},
    }
    if schema_version is not None:
        body["schema_version"] = schema_version
    return body


def favorite(content_id, wall=1760000000000, counter=0, device="cihaz-1",
              is_deleted=False, item_type="favorite"):
    return {
        "item_type": item_type,
        "content_id": content_id,
        "payload": {"title": "Interstellar", "type": "movie"},
        "is_deleted": is_deleted,
        "hlc": {"wall": wall, "counter": counter},
        "device_id": device,
        "client_updated_at": "2026-10-01T12:00:00.000Z",
    }


class TestSyncEndpoints:
    """POST /api/sync/push ve GET /api/sync/pull sözleşmesi."""

    def test_push_bos_govde_200(self, client):
        response = client.post("/api/sync/push", json=push_body(), headers=AUTH_HEADER)
        assert response.status_code == 200

        body = response.json()
        assert set(body) == {
            "applied", "rejected", "documents_applied",
            "documents_rejected", "server_time",
        }
        assert body["applied"] == []
        assert body["server_time"].endswith("Z")

    def test_push_kayit_uygular(self, client):
        body = client.post(
            "/api/sync/push", json=push_body([favorite("abc123")]), headers=AUTH_HEADER
        ).json()
        assert body["applied"] == [{"item_type": "favorite", "content_id": "abc123"}]
        assert body["rejected"] == []

    def test_push_ayni_kaydi_tekrar_gonderir_rejected(self, client):
        """Sessiz veri kaybı yerine red + sunucu sürümü döner."""
        record = favorite("abc123")
        client.post("/api/sync/push", json=push_body([record]), headers=AUTH_HEADER)
        body = client.post(
            "/api/sync/push", json=push_body([record]), headers=AUTH_HEADER
        ).json()

        assert body["applied"] == []
        assert len(body["rejected"]) == 1
        rejected = body["rejected"][0]
        assert rejected["item_type"] == "favorite"
        assert rejected["content_id"] == "abc123"
        assert rejected["reason"] == "server_equal"
        # Frontend `server_version.payload / .hlc / .device_id / .is_deleted` okur.
        assert rejected["server_version"]["payload"]["title"] == "Interstellar"
        assert rejected["server_version"]["hlc"]["wall"] == 1760000000000
        assert rejected["server_version"]["device_id"] == "cihaz-1"
        assert rejected["server_version"]["is_deleted"] is False

    def test_push_daha_eski_kayit_server_newer(self, client):
        client.post(
            "/api/sync/push",
            json=push_body([favorite("abc", device="tablet")]),
            headers=AUTH_HEADER,
        )
        body = client.post(
            "/api/sync/push",
            json=push_body([favorite("abc", wall=1000, device="telefon")]),
            headers=AUTH_HEADER,
        ).json()
        assert body["applied"] == []
        assert body["rejected"][0]["reason"] == "server_newer"

    def test_push_belgeleri_uygular(self, client):
        documents = {
            "player_settings": {
                "payload": {"seekDuration": 15},
                "hlc": {"wall": 1760000000000, "counter": 1},
                "device_id": "cihaz-1",
                "client_updated_at": "2026-10-01T12:00:05.000Z",
            }
        }
        body = client.post(
            "/api/sync/push", json=push_body(documents=documents), headers=AUTH_HEADER
        ).json()
        assert body["documents_applied"] == ["player_settings"]
        assert body["documents_rejected"] == []

    def test_push_bilinmeyen_belge_tipi_400(self, client):
        documents = {
            "bilinmeyen": {
                "payload": {},
                "hlc": {"wall": 1, "counter": 0},
                "device_id": "cihaz-1",
            }
        }
        response = client.post(
            "/api/sync/push", json=push_body(documents=documents), headers=AUTH_HEADER
        )
        assert response.status_code == 400
        assert "bilinmeyen" in response.json()["detail"]

    def test_push_gorunurluk_belgeleri_global_uygulanir(self, client):
        """Eklenti/kategori görünürlüğü hesap genelinde senkronize edilir."""
        documents = {
            "plugin_visibility": {
                "payload": {"dizibox": False, "hdfilmcehennemi": True},
                "hlc": {"wall": 1760000000000, "counter": 0},
                "device_id": "telefon",
                "client_updated_at": "2026-10-01T12:00:00.000Z",
            },
            "category_visibility": {
                "payload": {"hdfilmcehennemi": {"dram": False}},
                "hlc": {"wall": 1760000000000, "counter": 0},
                "device_id": "telefon",
                "client_updated_at": "2026-10-01T12:00:00.000Z",
            },
        }
        body = client.post(
            "/api/sync/push", json=push_body(documents=documents), headers=AUTH_HEADER
        ).json()
        assert sorted(body["documents_applied"]) == [
            "category_visibility",
            "plugin_visibility",
        ]
        assert body["documents_rejected"] == []

    def test_push_gorunurluk_eski_cihaz_reddedilir(self, client):
        """Global kural: daha eski HLC'li cihaz sunucunun değerini ezemez."""
        newer = {
            "plugin_visibility": {
                "payload": {"dizibox": False},
                "hlc": {"wall": 1760000009000, "counter": 0},
                "device_id": "telefon",
            }
        }
        client.post(
            "/api/sync/push", json=push_body(documents=newer), headers=AUTH_HEADER
        )

        older = {
            "plugin_visibility": {
                "payload": {"dizibox": True},
                "hlc": {"wall": 1760000001000, "counter": 0},
                "device_id": "tv",
            }
        }
        body = client.post(
            "/api/sync/push", json=push_body(documents=older), headers=AUTH_HEADER
        ).json()
        assert body["documents_applied"] == []
        assert body["documents_rejected"][0]["doc_type"] == "plugin_visibility"
        assert body["documents_rejected"][0]["reason"] == "server_newer"
        assert body["documents_rejected"][0]["server_version"]["payload"] == {"dizibox": False}

    def test_pull_gorunurluk_belgelerini_dondurur(self, client):
        documents = {
            "plugin_visibility": {
                "payload": {"filmmodu": False},
                "hlc": {"wall": 1760000000000, "counter": 0},
                "device_id": "tv",
            }
        }
        client.post(
            "/api/sync/push", json=push_body(documents=documents), headers=AUTH_HEADER
        )
        body = client.get("/api/sync/pull", headers=AUTH_HEADER).json()
        assert body["documents"]["plugin_visibility"]["payload"] == {"filmmodu": False}
        # Sunucuda olmayan bir belge yanıtta da yer almaz (tombstone üretilmez)
        assert "player_settings" not in body["documents"]

    def test_push_cihaz_bos_422(self, client):
        body = push_body([favorite("abc")])
        body["device"] = {"device_id": "   "}
        assert client.post("/api/sync/push", json=body, headers=AUTH_HEADER).status_code == 422

    def test_push_gecersiz_item_type_422(self, client):
        record = {**favorite("abc"), "item_type": "bilinmeyen"}
        response = client.post(
            "/api/sync/push", json=push_body([record]), headers=AUTH_HEADER
        )
        assert response.status_code == 422

    def test_push_eksik_hlc_422(self, client):
        record = {k: v for k, v in favorite("abc").items() if k != "hlc"}
        response = client.post(
            "/api/sync/push", json=push_body([record]), headers=AUTH_HEADER
        )
        assert response.status_code == 422

    def test_push_surum_uyusmazligi_400(self, client):
        response = client.post(
            "/api/sync/push",
            json=push_body(schema_version=SUPPORTED_SCHEMA_VERSION + 1),
            headers=AUTH_HEADER,
        )
        assert response.status_code == 400
        assert "şema sürümü" in response.json()["detail"]

    def test_push_desteklenen_surum_200(self, client):
        response = client.post(
            "/api/sync/push",
            json=push_body(schema_version=SUPPORTED_SCHEMA_VERSION),
            headers=AUTH_HEADER,
        )
        assert response.status_code == 200

    def test_push_cok_fazla_kayit_413(self, client):
        records = [favorite(f"id-{i}") for i in range(1200)]
        response = client.post(
            "/api/sync/push", json=push_body(records), headers=AUTH_HEADER
        )
        assert response.status_code == 413

    def test_push_govde_boyutu_413(self, client):
        """
        Gövde boyutu sınırı gerçekten uygulanır.

        Kayıt SAYISI sınırına takılmayan, yalnızca boyut sınırına takılan istek
        kurulur: az sayıda ama çok büyük payload.
        """
        records = [
            {**favorite(f"id-{i}"), "payload": {"not": "x" * 600_000}}
            for i in range(5)
        ]
        response = client.post(
            "/api/sync/push", json=push_body(records), headers=AUTH_HEADER
        )
        assert response.status_code == 413
        assert "büyük" in response.json()["detail"]

    def test_push_tam_veri_seti_kabul_edilir(self, client):
        """
        Frontend her senkronizasyonda TÜM yerel durumu gönderir ve parçalamaz.

        En büyük gerçek veri kümesi (500 favori + 100 liste + 50 geçmiş +
        50 devam et = 700 kayıt) 413 almamalıdır; aksi halde senkronizasyon
        kalıcı olarak bozulur.
        """
        records = (
            [favorite(f"fav-{i}") for i in range(500)]
            + [favorite(f"wl-{i}", item_type="watchlist") for i in range(100)]
            + [favorite(f"wh-{i}", item_type="watch_history") for i in range(50)]
            + [favorite(f"cw-{i}", item_type="continue_watching") for i in range(50)]
        )
        for record in records:
            record["payload"] = {
                "id": record["content_id"],
                "title": "Interstellar",
                "poster": "https://example.com/poster.jpg",
                "type": "movie",
                "plugin": "HDFilm",
                "url": "/film/interstellar/",
            }
        response = client.post(
            "/api/sync/push", json=push_body(records), headers=AUTH_HEADER
        )
        assert response.status_code == 200
        assert len(response.json()["applied"]) == 700

    def test_pull_tam_dokum(self, client):
        client.post(
            "/api/sync/push",
            json=push_body([favorite("abc123"), favorite("def456")]),
            headers=AUTH_HEADER,
        )
        body = client.get("/api/sync/pull", headers=AUTH_HEADER).json()

        assert set(body) == {
            "records", "documents", "deleted_content_ids",
            "server_time", "has_more",
        }
        assert {r["content_id"] for r in body["records"]} == {"abc123", "def456"}
        assert body["has_more"] is False
        assert body["deleted_content_ids"] == []

        record = body["records"][0]
        assert record["payload"]["title"] == "Interstellar"
        assert record["hlc"] == {"wall": 1760000000000, "counter": 0}
        assert record["device_id"] == "cihaz-1"
        assert record["is_deleted"] is False
        assert record["server_updated_at"]

    def test_pull_delta_since(self, client):
        client.post("/api/sync/push", json=push_body([favorite("a")]), headers=AUTH_HEADER)
        checkpoint = fake_checkpoint()

        client.post(
            "/api/sync/push",
            json=push_body([favorite("a", wall=1760000009999), favorite("b")]),
            headers=AUTH_HEADER,
        )
        delta = client.get(f"/api/sync/pull?since={checkpoint}", headers=AUTH_HEADER).json()
        assert {r["content_id"] for r in delta["records"]} == {"a", "b"}

    def test_pull_delta_degisiklik_yoksa_bos(self, client):
        client.post("/api/sync/push", json=push_body([favorite("a")]), headers=AUTH_HEADER)
        checkpoint = fake_checkpoint()
        body = client.get(f"/api/sync/pull?since={checkpoint}", headers=AUTH_HEADER).json()
        assert body["records"] == []
        assert body["documents"] == {}

    def test_pull_gecersiz_since_422(self, client):
        response = client.get("/api/sync/pull?since=yarin", headers=AUTH_HEADER)
        assert response.status_code == 422

    def test_pull_tombstone_listesi(self, client):
        client.post("/api/sync/push", json=push_body([favorite("a")]), headers=AUTH_HEADER)
        body = client.post(
            "/api/sync/push",
            json=push_body([favorite("a", wall=1760000009999, is_deleted=True)]),
            headers=AUTH_HEADER,
        ).json()
        assert body["applied"] == [{"item_type": "favorite", "content_id": "a"}]

        pull = client.get("/api/sync/pull", headers=AUTH_HEADER).json()
        assert pull["deleted_content_ids"] == ["a"]
        assert pull["records"][0]["is_deleted"] is True

    def test_pull_belgeleri_dondurur(self, client):
        documents = {
            "theme": {
                "payload": {"mode": "dark"},
                "hlc": {"wall": 1760000000000, "counter": 0},
                "device_id": "cihaz-1",
            }
        }
        client.post("/api/sync/push", json=push_body(documents=documents), headers=AUTH_HEADER)

        body = client.get("/api/sync/pull", headers=AUTH_HEADER).json()
        assert body["documents"]["theme"]["payload"] == {"mode": "dark"}
        assert body["documents"]["theme"]["device_id"] == "cihaz-1"

    def test_pull_tam_veri_seti_tek_sayfada(self, client):
        """
        🔴 En büyük gerçek veri kümesi TEK sayfada gelmelidir.

        Mobil istemci `has_more` alanını yok sayar ve sayfalama yapmaz. 700
        kayıttan fazlası varsa kalan kayıtlar HİÇBİR ZAMAN teslim edilemez
        (istemci `since` damgasını push'tan alır ve eski satırları bir daha
        sorgulamaz).
        """
        records = (
            [favorite(f"fav-{i}") for i in range(500)]
            + [favorite(f"wl-{i}", item_type="watchlist") for i in range(100)]
            + [favorite(f"wh-{i}", item_type="watch_history") for i in range(50)]
            + [favorite(f"cw-{i}", item_type="continue_watching") for i in range(50)]
        )
        client.post("/api/sync/push", json=push_body(records), headers=AUTH_HEADER)

        body = client.get("/api/sync/pull", headers=AUTH_HEADER).json()
        assert body["has_more"] is False
        assert len(body["records"]) == 700

    def test_pull_limit_ve_has_more(self, client):
        records = [favorite(f"id-{i}") for i in range(5)]
        client.post("/api/sync/push", json=push_body(records), headers=AUTH_HEADER)
        body = client.get("/api/sync/pull?limit=2", headers=AUTH_HEADER).json()
        assert len(body["records"]) == 2
        assert body["has_more"] is True

    def test_cihaz_listesi_dizi_dondurur(self, client):
        client.post("/api/sync/push", json=push_body(), headers=AUTH_HEADER)
        devices = client.get("/api/sync/devices", headers=AUTH_HEADER).json()

        # Frontend `await res.json()` sonucunu doğrudan dizi olarak kullanır.
        assert isinstance(devices, list)
        assert devices[0]["device_id"] == "cihaz-1"
        assert devices[0]["device_name"] == "Salon TV"
        assert devices[0]["app_version"] == "1.0.0"
        assert devices[0]["is_current"] is True

    def test_cihaz_iptali(self, client):
        client.post("/api/sync/push", json=push_body(), headers=AUTH_HEADER)
        response = client.delete("/api/sync/devices/cihaz-1", headers=AUTH_HEADER)
        assert response.status_code == 200
        assert response.json()["revoked"] is True
        assert client.get("/api/sync/devices", headers=AUTH_HEADER).json() == []

    def test_iptal_olmayan_cihaz_404(self, client):
        response = client.delete("/api/sync/devices/yok", headers=AUTH_HEADER)
        assert response.status_code == 404

    def test_x_device_id_basligi_isareti_gunceller(self, client):
        client.post("/api/sync/push", json=push_body(), headers=AUTH_HEADER)
        devices = client.get(
            "/api/sync/devices",
            headers={**AUTH_HEADER, "X-Device-Id": "baska-cihaz"},
        ).json()
        assert devices[0]["is_current"] is False

    def test_push_su_isareti_yazma_once_alinir(self, client, patched):
        """
        🔴 Sessiz veri kaybı koruması.

        İstemci `server_time` değerini bir sonraki `pull?since=` değeri olarak
        saklar. Damga yazmalardan SONRA alınırsa, bu push sırasında başka bir
        cihazın yazdığı satırlar bir sonraki çekişte hiç gelmez.
        """
        client.post("/api/sync/push", json=push_body([favorite("a")]), headers=AUTH_HEADER)
        watermark = client.post(
            "/api/sync/push", json=push_body([favorite("b")]), headers=AUTH_HEADER
        ).json()["server_time"]

        # Damga, bu push'un yazdığı satırlardan ÖNCE alınmış olmalı:
        # aynı döngüde yazılan kayıt bir sonraki çekişte yeniden görünür
        # (HLC birleştirmesi idempotent olduğu için bu zararsızdır ve güvenlidir).
        delta = client.get(
            f"/api/sync/pull?since={watermark}", headers=AUTH_HEADER
        ).json()
        assert {r["content_id"] for r in delta["records"]} == {"a", "b"}

    def test_pull_last_pulled_at_isaretler(self, client):
        """Pull, cihazın `last_pulled_at` alanını günceller."""
        client.post("/api/sync/push", json=push_body(), headers=AUTH_HEADER)
        client.get("/api/sync/pull", headers=AUTH_HEADER)

        devices = client.get("/api/sync/devices", headers=AUTH_HEADER).json()
        assert devices[0]["last_pulled_at"] is not None


# ══════════════════════════════════════════════════════════════════════════════
# 4. UYGULAMA KATMANI — lifespan, CORS, yapılandırma
# ══════════════════════════════════════════════════════════════════════════════


class TestApplicationWiring:
    """`api/app.py` başlangıç/kapatma ve yapılandırma davranışı."""

    def test_tum_yeni_uc_kayitli(self):
        schema = app.openapi()
        paths = {
            f"{method.upper()} {path}"
            for path, operations in schema["paths"].items()
            for method in operations
        }
        for endpoint in (
            "POST /api/auth/signup",
            "POST /api/auth/login",
            "POST /api/auth/refresh",
            "POST /api/auth/logout",
            "GET /api/auth/me",
            "POST /api/sync/push",
            "GET /api/sync/pull",
            "GET /api/sync/devices",
            "DELETE /api/sync/devices/{device_id}",
        ):
            assert endpoint in paths, f"{endpoint} kayıtlı değil"

    def test_kok_endpoint_calisir(self):
        """Lifespan bilinçli çalıştırılır: başlangıç uyarıları hata vermemeli."""
        with TestClient(app) as client:
            assert client.get("/").status_code == 200

    def test_lifespan_baglantilari_kapatir(self, monkeypatch):
        """Shutdown'da Supabase ve Auth bağlantıları kapatılır."""
        import anyio

        closed = []
        dummy = _DummyPluginManager()

        monkeypatch.setattr(app_module, "get_plugin_manager", lambda: dummy)
        monkeypatch.setattr(
            app_module, "get_supabase_async", lambda: _FakeLifecycle(closed, "supabase")
        )
        monkeypatch.setattr(
            app_module, "get_auth_manager", lambda: _FakeLifecycle(closed, "auth")
        )

        async def run_lifespan():
            async with app.router.lifespan_context(app):
                pass

        anyio.run(run_lifespan)
        assert dummy.closed is True
        assert closed == ["supabase", "auth"]

    def test_supabase_yapilandirma_hatasi_503(self, patched, monkeypatch):
        """
        Eksik Supabase yapılandırması 500 değil anlaşılır 503 döner.

        `get_current_claims` bağımlılığı `patched` fixture'ı ile geçersiz kılınır;
        böylece 503'ün KAYNAĞININ auth katmanı değil, veri katmanı olduğu
        kanıtlanır.
        """
        from Core.Libs.Supabase import SupabaseConfigurationError

        def boom():
            raise SupabaseConfigurationError("SUPABASE_URL tanımlı değil.")

        monkeypatch.setattr("api.routes.sync.get_supabase_async", boom)
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/sync/pull", headers=AUTH_HEADER)
        assert response.status_code == 503
        assert "yapılandırılmamış" in response.json()["detail"]


class _DummyPluginManager:
    def __init__(self):
        self.closed = False

    async def close_plugins(self):
        self.closed = True


class _FakeLifecycle:
    """Kapatma çağrılarını kaydeden sahte yönetici."""

    def __init__(self, sink, label):
        self._sink = sink
        self._label = label

    async def close_async(self):
        self._sink.append(self._label)

    async def close(self):
        self._sink.append(self._label)


class TestCorsConfiguration:
    """CORS beyaz listesi — wildcard + credential kombinasyonu kapatılmış olmalı."""

    def test_virgulle_ayrilir_ve_temizlenir(self):
        from api.app import parse_cors_origins

        assert parse_cors_origins(" http://a.test , https://b.test ") == [
            "http://a.test",
            "https://b.test",
        ]

    def test_bos_girdi_kapali_kalar(self):
        from api.app import parse_cors_origins

        assert parse_cors_origins("") == []
        assert parse_cors_origins(None) == []
        assert parse_cors_origins(" , , ") == []

    def test_izinli_origin_eklenir_credentials_kapali(self):
        from fastapi import FastAPI

        from api.app import configure_cors

        fresh = FastAPI()
        configure_cors(fresh, ["https://app.example.com"])

        cors = [m for m in fresh.user_middleware if m.cls.__name__ == "CORSMiddleware"]
        assert len(cors) == 1
        assert cors[0].kwargs["allow_origins"] == ["https://app.example.com"]
        assert cors[0].kwargs["allow_credentials"] is False
        assert "Authorization" in cors[0].kwargs["allow_headers"]

    def test_bos_liste_middleware_eklemez(self):
        from fastapi import FastAPI

        from api.app import configure_cors

        fresh = FastAPI()
        configure_cors(fresh, [])
        assert [m for m in fresh.user_middleware if m.cls.__name__ == "CORSMiddleware"] == []


# ══════════════════════════════════════════════════════════════════════════════
# 5. JWT DOĞRULAMA
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════
# 5. JWT DOĞRULAMA
# ══════════════════════════════════════════════════════════════════════════



class FakeClaims:
    """`supabase.auth.get_claims()` dönüşünü taklit eder."""

    def __init__(self, claims):
        self.claims = claims
        self.headers = {}
        self.signature = b""


def make_token(role="authenticated", alg="HS256", kid=None, exp_delta=3600):
    """Gerçek bir JWT ürretir (imzası geçersiz ama yapısı doğrudur)."""
    import base64
    import json
    import time

    header = {"alg": alg, "typ": "JWT"}
    if kid:
        header["kid"] = kid
    payload = {
        "iss": "https://fake.supabase.co/auth/v1",
        "sub": "user-123",
        "email": "user@example.com",
        "role": role,
        "aud": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + exp_delta,
    }

    def part(data):
        raw = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
        return raw

    return f"{part(header)}.{part(payload)}.bmFzaW1zaW4"


def make_auth_manager():
    from Core.Libs.SupabaseAuth import SupabaseAuthManager

    return SupabaseAuthManager(url="https://fake.supabase.co", anon_key="anon")


def stub_client(manager, get_claims=None):
    """Manager'{'i sahte GoTrue istemcisine bağlar."""
    if get_claims is None:
        async def get_claims(token):
            return FakeClaims({
                "sub": "user-123",
                "email": "user@example.com",
                "role": "authenticated",
            })

    client = type("Client", (), {})()
    client.auth = type("Auth", (), {"get_claims": staticmethod(get_claims)})()

    async def client_fn():
        return client

    manager.client = client_fn
    return client


class TestJwtVerification:
    """
    Doğrulama SDK'nın resmî `auth.get_claims()` metoduna devredilir.

    Supabase iki imza sistemi destekler:
      * Asimetrik (ES256/RS256/EdDSA) → JWKS'ten `kid` ile eşleşen açık anahtarla YERELDE
      * Simetrik (HS256)            → Auth sunucusunda (`get_user`)
    `get_claims` bu seçimi kendisi yapar; bizim işimiz yalnızca sonucu
    denetlemek ve API sözleşmesine uygun hâle getirmek.
    """

    def test_env_de_imza_anahtari_yok(self):
        """
        🔑 `.env`'de tutulacak bir imza anahtarı OLMAMALI.

        Anahtar modeli değişti (Key ID vs legacy secret); kod değişmeden
        her iki durumu da desteklemesi gerekiyor.
        """
        from pathlib import Path

        from Core.Libs import SupabaseAuth

        source = Path(SupabaseAuth.__file__).read_text(encoding="utf-8")
        assert "SUPABASE_JWT_SECRET" not in source
        assert not hasattr(make_auth_manager(), "jwt_secret")

    def test_gecerli_token_kabul_edilir(self):
        manager = make_auth_manager()
        stub_client(manager)

        claims = _run(manager.verify_access_token(make_token()))
        assert claims["sub"] == "user-123"
        assert claims["email"] == "user@example.com"
        assert claims["role"] == "authenticated"

    def test_service_role_token_reddedilir(self):
        """
        🔴 `service_role` JWT'si kabul edilmemeli.

        Bir sunucu anahtarı istemciye sızarsa doğrudan API'ye erişmesine
        yol açardı; istemci tarafı için sadece `authenticated` rolü geçerlidir.
        """
        from Core.Libs.SupabaseAuth import InvalidTokenError

        manager = make_auth_manager()
        stub_client(manager, lambda token: _async_value(FakeClaims({
            "sub": "user-123", "email": "a@b.c", "role": "service_role",
        })))

        with pytest.raises(InvalidTokenError):
            _run(manager.verify_access_token(make_token(role="service_role")))

    def test_sub_olmayan_token_reddedilir(self):
        from Core.Libs.SupabaseAuth import InvalidTokenError

        manager = make_auth_manager()
        stub_client(manager, lambda token: _async_value(FakeClaims({"role": "authenticated"})))

        with pytest.raises(InvalidTokenError):
            _run(manager.verify_access_token(make_token()))

    def test_bos_token_reddedilir(self):
        from Core.Libs.SupabaseAuth import InvalidTokenError

        with pytest.raises(InvalidTokenError):
            _run(make_auth_manager().verify_access_token("   "))

    def test_get_claims_hatasi_401e_cevrilir(self):
        """SDK'nın imza/süre hatası geçersiz token anlamına gelir."""
        from supabase_auth.errors import AuthInvalidJwtError

        from Core.Libs.SupabaseAuth import InvalidTokenError

        async def boom(token):
            raise AuthInvalidJwtError("Invalid JWT signature")

        manager = make_auth_manager()
        stub_client(manager, boom)

        with pytest.raises(InvalidTokenError):
            _run(manager.verify_access_token(make_token()))

    def test_yapilandirma_hatasi_yutulmez(self):
        """
        🔴 Sunucu yapılandırması eksikse 503'e dönmeli, 401'e değil.

        401 dönerse istemci oturumu kapatır ve kullanıcı hesabına erişemez.
        """
        from Core.Libs.SupabaseAuth import AuthConfigurationError, InvalidTokenError

        manager = make_auth_manager()

        async def no_config():
            raise AuthConfigurationError("SUPABASE_ANON_KEY tanımlı değil.")

        manager.client = no_config

        with pytest.raises(AuthConfigurationError):
            _run(manager.verify_access_token(make_token()))

        with pytest.raises(InvalidTokenError):
            _run(manager.verify_access_token(""))
        # ✓ yapılandırma hatası yalnızca gerçek doğrulama yolunda yukarı yayılır


class TestVerificationSource:
    """
    `source` alanı hangi yolun izlendiığini bildirir.

    Salt tanı amaçlıdır: token başılığı OKUNUR ama GÜVENİLMEZ —
    güvenlik kararı `get_claims`'a aittir.
    """

    def test_simetrik_token_gotrue(self):
        from Core.Libs.SupabaseAuth import _verification_source

        assert _verification_source(make_token(alg="HS256")) == "gotrue"

    def test_kid_siz_token_gotrue(self):
        """`kid` yoksa SDK simetrik varsayar."""
        from Core.Libs.SupabaseAuth import _verification_source

        assert _verification_source(make_token(alg="ES256")) == "gotrue"

    def test_asimetrik_token_jwks(self):
        from Core.Libs.SupabaseAuth import _verification_source

        for alg in ("ES256", "RS256", "EdDSA"):
            token = make_token(alg=alg, kid="3a18cfe2-7226-43b0-bbb4-7c5242f2406e")
            assert _verification_source(token) == "jwks"

    def test_bozuk_token_guvenli_default(self):
        from Core.Libs.SupabaseAuth import _verification_source

        assert _verification_source("bozuk") == "gotrue"
        assert _verification_source("") == "gotrue"

    def test_dogrulama_bu_yolla_etkilenmez(self):
        """`source` hesabı başarı çıkışı yönümde de aynı iddialar döner."""
        manager = make_auth_manager()
        stub_client(manager)

        token = make_token(alg="ES256", kid="abc-123")
        claims = _run(manager.verify_access_token(token))
        assert claims["sub"] == "user-123"
        assert claims["source"] == "jwks"


class TestIssuerCheck:
    """`iss` denetimi yalnızca BıLGİLİDİR; imza zaten doğrulanmıştır."""

    def test_iss_uyusmazligi_reddetmez(self):
        manager = make_auth_manager()
        stub_client(manager, lambda token: _async_value(FakeClaims({
            "sub": "user-123",
            "role": "authenticated",
            "iss": "https://ozel-alan-adi.example.com/auth/v1",
        })))

        claims = _run(manager.verify_access_token(make_token()))
        assert claims["sub"] == "user-123"

    def test_uyusan_iss_uyari_yok(self, capsys):
        manager = make_auth_manager()
        stub_client(manager, lambda token: _async_value(FakeClaims({
            "sub": "user-123",
            "role": "authenticated",
            "iss": "https://fake.supabase.co/auth/v1",
        })))

        _run(manager.verify_access_token(make_token()))
        assert "iss" not in capsys.readouterr().out


class TestVerificationModeProbe:
    """
    JWKS probu — "hangi moddayım?" sorusunu başlangıçta yanıtlar.

    JWKS uç noktası yalnızca ASİMETRİK anahtarları yayımlar; simetrik (HS256)
    sır orada görünmez. Bu yüzden yanıt doluysa doğrulama ağ turusuzdur.
    """

    KID = "3a18cfe2-7226-43b0-bbb4-7c5242f2406e"

    def _manager_with_jwks(self, payload, status_code=200):
        manager = make_auth_manager()

        class Response:
            def __init__(self):
                self.status_code = status_code

            def json(self):
                return payload

        class Http:
            async def get(self, url, headers=None):
                self.url = url
                self.headers = headers
                return Response()

        http = Http()
        client = type("Client", (), {})()
        client.auth = type("Auth", (), {"_http_client": http})()

        async def client_fn():
            return client

        manager.client = client_fn
        return manager, http

    def test_asimetrik_proje_tespit_edilir(self):
        manager, http = self._manager_with_jwks({
            "keys": [{"kid": self.KID, "alg": "ES256", "kty": "EC"}]
        })
        probe = _run(manager.probe_verification_mode())

        assert probe["mode"] == "asymmetric"
        assert probe["key_count"] == 1
        assert probe["algorithms"] == ["ES256"]
        assert probe["key_ids"] == [self.KID]
        assert http.url.endswith("/auth/v1/.well-known/jwks.json")

    def test_simetrik_proje_tespit_edilir(self):
        manager, _ = self._manager_with_jwks({"keys": []})
        probe = _run(manager.probe_verification_mode())
        assert probe["mode"] == "symmetric"
        assert probe["key_count"] == 0

    def test_hata_durumunda_unknown(self):
        manager, _ = self._manager_with_jwks({}, status_code=503)
        probe = _run(manager.probe_verification_mode())
        assert probe["mode"] == "unknown"
        assert "503" in probe["reason"]

    def test_url_veya_anahtar_yoksa_unknown(self):
        from Core.Libs.SupabaseAuth import SupabaseAuthManager

        manager = SupabaseAuthManager(url="", anon_key="anon")
        assert _run(manager.probe_verification_mode())["mode"] == "unknown"

        manager2 = SupabaseAuthManager(url="https://x.supabase.co", anon_key="")
        assert _run(manager2.probe_verification_mode())["mode"] == "unknown"

    def test_probe_hatasi_baslamayi_engellemez(self):
        """Tanı aracıdır: patlarsa API yine de ayağa kalkar."""
        import importlib

        # `api.app` paket özniteliği FastAPI nesnesiyle gölgelenmiş; modülü
        # doğrudan sys.modules'tan almak gerekiyor.
        app_module = importlib.import_module("api.app")

        async def boom():
            raise RuntimeError("ağ yok")

        class Dummy:
            probe_verification_mode = staticmethod(boom)

        original = app_module.get_auth_manager
        app_module.get_auth_manager = lambda: Dummy()
        try:
            _run(app_module._report_verification_mode())   # istisna atmamalı
        finally:
            app_module.get_auth_manager = original


class TestRouteDiagnostics:
    """
    404 teşhisi — sessiz "Not Found" yerine ne yapılması gerektiğini söyler.

    En sık yapılandırma hatası: taban URL sonuna `/api` yazılması. İstek
    `/api/api/auth/signup` olur ve kullanıcı neden 404 aldığını anlamaz.
    """

    def test_cift_api_onemli_dahil(self, client):
        response = client.post("/api/api/auth/signup", json={})
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert "EXPO_PUBLIC_API_URL" in detail
        assert "/api/api/auth/signup" in detail

    def test_cift_api_sync_uc_dahil(self, client):
        response = client.get("/api/api/sync/pull", headers=AUTH_HEADER)
        assert response.status_code == 404
        assert "EXPO_PUBLIC_API_URL" in response.json()["detail"]

    def test_normal_yollar_dokunulmaz(self, client):
        """Mevcut uçlar kendi 404 mesajlarını korumalı."""
        response = client.delete("/api/sync/devices/yok", headers=AUTH_HEADER)
        assert response.status_code == 404
        assert response.json()["detail"] == "Bu cihaz bulunamadı veya zaten iptal edilmiş."

    def test_bilinmeyen_yol_oldugu_gibi_kalir(self, client):
        response = client.get("/api/olmayan-uc")
        assert response.status_code == 404
        assert "EXPO_PUBLIC_API_URL" not in response.json()["detail"]

    def test_diger_http_hatalari_korunur(self, anon_client):
        """401 gövdesi ve WWW-Authenticate başlığı bozulmamalı."""
        response = anon_client.get("/api/sync/pull")
        assert response.status_code == 401
        assert response.json()["detail"] == "Oturum geçersiz."
        assert response.headers.get("WWW-Authenticate") == "Bearer"


class TestClockSkewWatermark:
    """
    🔴 Delta damgası `updated_at` ile AYNI saat kaynağından gelmelidir.

    `updated_at` sütunu veritabanının NOW() değeriyle yazılır. Damga API
    sunucusunun saatinden gelirse iki saat arasındaki kayma (bu proje için
    ölçülen ~0.95 saniye) sessiz veri kaybına yol açar: damgadan sonra yazılan
    satırlar `updated_at > since` koşulunu sağlamaz ve bir daha asla gelmez.
    """

    DB_TIME = "2026-10-01T12:00:00.123Z"

    def test_sunucu_saatinin_mikrosaniyeleri_kirpilir(self):
        """Postgres mikro saniye döner; API sözleşmesi milisaniye ister."""
        from datetime import datetime, timezone

        from Core.Libs.Supabase import _iso_utc

        stamp = datetime(2026, 10, 1, 12, 0, 0, 123456, tzinfo=timezone.utc)
        assert _iso_utc(stamp) == "2026-10-01T12:00:00.123Z"
        assert _iso_utc(None) is None

    def test_damga_veritabanindan_alinir(self, patched, fake_db):
        """RPC varsa damga doğrudan DB saatidir (`_iso_utc` ile normalize)."""
        async def server_now():
            return self.DB_TIME

        fake_db.server_now = server_now

        client = client_with(fake_db)
        body = client.get("/api/sync/pull", headers=AUTH_HEADER).json()
        assert body["server_time"] == "2026-10-01T12:00:00.123Z"

        push = client.post("/api/sync/push", json=push_body(), headers=AUTH_HEADER).json()
        assert push["server_time"] == "2026-10-01T12:00:00.123Z"

    def test_rpc_yoksa_guvenli_yedek_kullanilir(self, patched, fake_db, capsys,
                                                    monkeypatch):
        """
        DDL çalıştırılmamışsa yedeğe düşülür — ama kayma payı kadar geriden.

        Yedek, API saatinden `CLOCK_SKEW_MARGIN_SECONDS` kadar geri gider; bu
        sayede DB saatinin geride olması hâlinde bile hiçbir satır atlanmaz.
        """
        import api.routes.sync as sync_route
        from datetime import datetime, timezone

        from Core.Libs.SyncModels import CLOCK_SKEW_MARGIN_SECONDS

        monkeypatch.setattr(sync_route, "_warned_clock_skew", False)

        async def server_now():
            return None

        fake_db.server_now = server_now

        client = client_with(fake_db)
        body = client.get("/api/sync/pull", headers=AUTH_HEADER).json()

        stamp = datetime.fromisoformat(body["server_time"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
        assert CLOCK_SKEW_MARGIN_SECONDS - 2 <= age <= CLOCK_SKEW_MARGIN_SECONDS + 2

        # Kullanıcıya ne yapması gerektiği bildirilir.
        assert "server_now" in capsys.readouterr().out

    def test_rpc_hatasi_uyariyi_tekrar_basmaz(self, patched, fake_db, monkeypatch):
        """Uyarı yalnızca bir kez basılır (gürültü yaratmamak için)."""
        import api.routes.sync as sync_route

        monkeypatch.setattr(sync_route, "_warned_clock_skew", False)

        calls = []

        async def server_now():
            calls.append(1)
            return None

        fake_db.server_now = server_now
        client = client_with(fake_db)

        client.get("/api/sync/pull", headers=AUTH_HEADER)
        client.get("/api/sync/pull", headers=AUTH_HEADER)
        assert len(calls) == 2
        assert sync_route._warned_clock_skew is True

    def test_damga_okumalardan_once_alinir(self, patched, fake_db):
        """Damga okuma/yazma başlamadan alınır (aksi halde kayıp satır)."""
        order = []

        async def server_now():
            order.append("damga")
            return "2026-10-01T12:00:00.000Z"

        async def mark_pulled(user_id, device_id=None):
            order.append("mark_pulled")
            return True

        fake_db.server_now = server_now
        fake_db.mark_pulled = mark_pulled

        client = client_with(fake_db)
        client.get("/api/sync/pull", headers=AUTH_HEADER)

        assert order[0] == "damga"


def client_with(fake_db):
    """Sahte veri yöneticisiyle bir TestClient kurar."""
    import api.routes.sync as sync_route

    original = sync_route.get_supabase_async
    sync_route.get_supabase_async = lambda: fake_db
    test_client = TestClient(app, raise_server_exceptions=False)
    test_client._restore_sync = lambda: setattr(sync_route, "get_supabase_async", original)
    return test_client


class TestRefreshErrorMapping:
    """Yenileme hatalarının hepsi 401'e düşmelidir (bkz. TestAuthEndpoints)."""

    def test_yenileme_hatasi_401_eslesmeleri(self):
        from api.routes.auth import _REFRESH_ERROR_MESSAGES

        # İstemci 401'de sessizce yeniden giriş dener; bu yüzden "yenilenemedi"
        # anlamına gelen HER hata 401 olmalı.
        for code in ("refresh_token_not_found", "refresh_token_already_used",
                     "session_not_found", "session_expired",
                     "validation_failed", "bad_json"):
            assert code in _REFRESH_ERROR_MESSAGES, code

    def test_bilinmeyen_kod_401_ve_turkce(self):
        from fastapi import HTTPException

        from api.routes.auth import _refresh_error

        error = _refresh_error(Exception("çok gizemli hata"))
        assert isinstance(error, HTTPException)
        assert error.status_code == 401
        assert "giriş" in error.detail.lower()


def _async_value(value):
    """Sabit bir değeri döndüren sahte coroutine."""

    async def _resolve():
        return value

    return _resolve()


def _run(coro):
    """Test içinde `async def` çağrısı çalıştırır."""
    import asyncio

    return asyncio.run(coro)


class TestServiceRoleKeyRequirement:
    """
    RLS açık tablolar yalnızca servis rolü anahtarıyla erişilebilir.

    Anon anahtarla yapılan sorgular boş döner; bu sessizce "senkronizasyon
    çalışıyor gibi görünür ama veri taşınmaz" demektir. Bu yüzden hata fırlatılır
    ve yedek anahtar zinciri `resolve_service_role_key` içinde BULUNMAZ.
    """

    def test_yedek_anahtar_zinciri_yok(self):
        """`SUPABASE_ANON_KEY` / eski `SUPABASE_KEY`, servis rolü yerine sayılmaz."""
        from Core.Libs.SupabaseAuth import resolve_service_role_key

        import os

        original = {
            key: os.environ.get(key)
            for key in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ANON_KEY", "SUPABASE_KEY")
        }
        try:
            os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)
            os.environ["SUPABASE_ANON_KEY"] = "anon-anahtar"
            os.environ["SUPABASE_KEY"] = "eski-anahtar"
            key, name = resolve_service_role_key()
            assert key == ""
            assert name == "SUPABASE_SERVICE_ROLE_KEY"

            os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "servis-rolu"
            assert resolve_service_role_key()[0] == "servis-rolu"
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    @pytest.mark.asyncio
    async def test_anahtar_yoksa_hata_firlatir(self, monkeypatch):
        from Core.Libs import Supabase as supabase_module
        from Core.Libs.Supabase import SupabaseManager, SupabaseConfigurationError

        monkeypatch.setattr(supabase_module, "resolve_supabase_url",
                            lambda: "https://fake.supabase.co")
        monkeypatch.setattr(supabase_module, "resolve_service_role_key", lambda: ("", ""))
        with pytest.raises(SupabaseConfigurationError, match="SUPABASE_SERVICE_ROLE_KEY"):
            await SupabaseManager().async_client()

    @pytest.mark.asyncio
    async def test_url_eksikse_once_o_hata_gelir(self, monkeypatch):
        from Core.Libs import Supabase as supabase_module
        from Core.Libs.Supabase import SupabaseManager, SupabaseConfigurationError

        monkeypatch.setattr(supabase_module, "resolve_supabase_url", lambda: "")
        monkeypatch.setattr(
            supabase_module, "resolve_service_role_key", lambda: ("svc", "SUPABASE_SERVICE_ROLE_KEY")
        )
        with pytest.raises(SupabaseConfigurationError, match="SUPABASE_URL"):
            await SupabaseManager().async_client()

    def test_anon_anahtar_yalnizca_gotrue_icin(self, monkeypatch):
        """`resolve_anon_key` servis rolü anahtarını TUTMAMALI (kaynak karışıklığı)."""
        from Core.Libs.SupabaseAuth import resolve_anon_key

        monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "servis")
        monkeypatch.setenv("SUPABASE_KEY", "eski")
        assert resolve_anon_key() == "anon"


# ══════════════════════════════════════════════════════════════════════════════
# 6. CANLI SUPABASE TESTLERİ (varsayılan olarak atlanır)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.live
class TestLiveSupabase:
    """
    Gerçek Supabase'e karşı uçtan uca testler.

    Çalıştırma (PowerShell):
        $env:SUPABASE_LIVE_TESTS="1"
        pytest -m live tests/test_auth_api.py
    """

    @pytest.fixture(autouse=True)
    def require_live(self):
        import os

        if os.getenv("SUPABASE_LIVE_TESTS") != "1":
            pytest.skip("Canlı testler için SUPABASE_LIVE_TESTS=1 gerekir.")
        if not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
            pytest.skip("SUPABASE_SERVICE_ROLE_KEY tanımlı değil.")

    @pytest.mark.asyncio
    async def test_db_baglantisi_acar(self):
        from Core.Libs.Supabase import SupabaseManager

        manager = SupabaseManager()
        try:
            rows, has_more = await manager.fetch_library(
                "00000000-0000-0000-0000-000000000000"
            )
            assert rows == []
            assert has_more is False
        finally:
            await manager.close_async()

    @pytest.mark.asyncio
    async def test_eksik_servis_rolu_anahtari_hata_verir(self, monkeypatch):
        """Servis rolü anahtarı yoksa açık hata fırlatılır (sessiz boş sonuç yok)."""
        from Core.Libs import Supabase as supabase_module
        from Core.Libs.Supabase import SupabaseManager, SupabaseConfigurationError

        monkeypatch.setattr(supabase_module, "resolve_service_role_key", lambda: ("", ""))
        manager = SupabaseManager()
        with pytest.raises(SupabaseConfigurationError):
            await manager.async_client()
