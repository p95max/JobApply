import io
from types import SimpleNamespace

import pytest
from django.core.exceptions import PermissionDenied

from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from googleapiclient.errors import HttpError

from apps.reports.drive import (
    DriveError,
    _friendly_http_error,
    _wrap_drive_call,
    _credentials_from_allauth,
    get_drive_status,
    upload_backup,
    list_backups,
    download_file,
    upload_backup_rotate_3,
)


def _make_http_error(status: int) -> HttpError:
    resp = SimpleNamespace(status=status, reason="X")
    return HttpError(resp=resp, content=b"{}")


class _Execute:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _FilesResource:
    def __init__(self):
        self._folders = {}
        self._files_by_id = {}
        self._files_by_parent = {}

        self._id_seq = 1

    def _new_id(self) -> str:
        i = self._id_seq
        self._id_seq += 1
        return str(i)

    def list(self, q=None, fields=None, pageSize=None, orderBy=None):
        if q and "mimeType='application/vnd.google-apps.folder'" in q:
            name = q.split("name='", 1)[1].split("'", 1)[0]
            parent_id = None
            if "in parents" in q:
                parent_id = q.split("and '", 1)[1].split("'", 1)[0]
            folder_id = self._folders.get((name, parent_id))
            files = []
            if folder_id:
                files = [{"id": folder_id, "name": name}]
            return _Execute({"files": files})

        if q and "in parents" in q and "trashed=false" in q:
            parent_id = q.split("'", 2)[1]
            if "and name='" in q:
                name = q.split("and name='", 1)[1].split("'", 1)[0]
                file_id = None
                for fid in self._files_by_parent.get(parent_id, []):
                    if self._files_by_id[fid]["name"] == name:
                        file_id = fid
                        break
                files = []
                if file_id:
                    meta = self._files_by_id[file_id]
                    files = [{"id": file_id, "name": meta["name"]}]
                return _Execute({"files": files})

            ids = list(self._files_by_parent.get(parent_id, []))
            metas = [self._files_by_id[fid] for fid in ids]
            metas.sort(key=lambda x: x.get("createdTime", ""), reverse=True)
            out = [{"id": m["id"], "name": m["name"], "mimeType": m["mimeType"]} for m in metas[: pageSize or 100]]
            return _Execute({"files": out})

        return _Execute({"files": []})

    def create(self, body=None, media_body=None, fields=None):
        if body and body.get("mimeType") == "application/vnd.google-apps.folder":
            name = body["name"]
            parent_id = (body.get("parents") or [None])[0]
            existing = self._folders.get((name, parent_id))
            if existing:
                return _Execute({"id": existing})
            folder_id = self._new_id()
            self._folders[(name, parent_id)] = folder_id
            return _Execute({"id": folder_id})

        name = body["name"]
        parent_id = (body.get("parents") or [None])[0]
        file_id = self._new_id()
        meta = {"id": file_id, "name": name, "mimeType": getattr(media_body, "mimetype", "application/octet-stream")}
        self._files_by_id[file_id] = meta
        self._files_by_parent.setdefault(parent_id, []).append(file_id)
        return _Execute(meta)

    def update(self, fileId=None, body=None):
        meta = self._files_by_id[fileId]
        meta["name"] = body["name"]
        return _Execute({"id": fileId})

    def delete(self, fileId=None):
        meta = self._files_by_id.pop(fileId, None)
        if meta:
            for parent_id, ids in list(self._files_by_parent.items()):
                if fileId in ids:
                    ids.remove(fileId)
                    self._files_by_parent[parent_id] = ids
        return _Execute({})

    def get_media(self, fileId=None):
        content = f"file:{fileId}".encode("utf-8")
        return SimpleNamespace(_content=content)


class _DriveService:
    def __init__(self):
        self._files = _FilesResource()

    def files(self):
        return self._files


class _Downloader:
    def __init__(self, fh: io.BytesIO, request):
        self._fh = fh
        self._req = request
        self._done = False

    def next_chunk(self):
        if self._done:
            return (None, True)
        self._fh.write(self._req._content)
        self._done = True
        return (None, True)


@pytest.fixture
def user(db, django_user_model):
    return django_user_model.objects.create_user(username="u1", email="u1@example.com", password="x")


@pytest.fixture
def google_social(db):
    app = SocialApp.objects.create(provider="google", name="google", client_id="cid", secret="sec")
    return app


@pytest.fixture
def connect_google(db, user, google_social):
    acc = SocialAccount.objects.create(user=user, provider="google", uid="uid", extra_data={"email": "u1@example.com"})
    tok = SocialToken.objects.create(account=acc, app=google_social, token="access", token_secret="refresh")
    return acc, tok


def test_friendly_http_error_auth():
    err = _make_http_error(401)
    out = _friendly_http_error(err)
    assert isinstance(out, DriveError)
    assert out.code == "auth"


def test_friendly_http_error_rate_limited():
    err = _make_http_error(429)
    out = _friendly_http_error(err)
    assert out.code == "rate_limited"


def test_friendly_http_error_upstream():
    err = _make_http_error(503)
    out = _friendly_http_error(err)
    assert out.code == "upstream"


def test_wrap_drive_call_passthrough_permission_denied():
    with pytest.raises(PermissionDenied):
        _wrap_drive_call("x", lambda: (_ for _ in ()).throw(PermissionDenied("no")))


def test_wrap_drive_call_http_error():
    with pytest.raises(DriveError) as e:
        _wrap_drive_call("x", lambda: (_ for _ in ()).throw(_make_http_error(403)))
    assert e.value.code == "auth"


def test_get_drive_status_not_connected(db, user):
    st = get_drive_status(user)
    assert st["connected"] is False
    assert st["has_refresh_token"] is False


def test_get_drive_status_connected_no_token(db, user, google_social):
    SocialAccount.objects.create(user=user, provider="google", uid="uid")
    st = get_drive_status(user)
    assert st["connected"] is True
    assert st["has_refresh_token"] is False


def test_get_drive_status_connected_with_refresh(db, connect_google, user):
    st = get_drive_status(user)
    assert st["connected"] is True
    assert st["has_refresh_token"] is True


def test_credentials_from_allauth_requires_account(db, user):
    with pytest.raises(PermissionDenied):
        _credentials_from_allauth(user)


def test_credentials_from_allauth_requires_refresh_token(db, user, google_social):
    acc = SocialAccount.objects.create(user=user, provider="google", uid="uid")
    SocialToken.objects.create(account=acc, app=google_social, token="access", token_secret="")
    with pytest.raises(PermissionDenied):
        _credentials_from_allauth(user)


def test_credentials_from_allauth_ok(db, connect_google, user):
    creds = _credentials_from_allauth(user)
    assert creds.token == "access"
    assert creds.refresh_token == "refresh"


def test_upload_list_download_happy_path(monkeypatch, connect_google, user):
    service = _DriveService()

    import apps.reports.drive as drive_mod

    monkeypatch.setattr(drive_mod, "build", lambda *a, **k: service)
    monkeypatch.setattr(drive_mod, "MediaIoBaseDownload", _Downloader)

    up = upload_backup(
        user=user,
        filename="x.csv",
        content_bytes=b"hello",
        mime_type="text/csv",
        root_name="JobApply",
        subfolder="backups",
    )
    assert up.file_id
    assert up.name == "x.csv"

    items = list_backups(user=user, limit=30, root_name="JobApply", subfolder="backups")
    assert len(items) == 1
    assert items[0].name == "x.csv"

    raw = download_file(user=user, file_id=items[0].file_id)
    assert raw.startswith(b"file:")


def test_rotate_3_happy_path(monkeypatch, connect_google, user):
    service = _DriveService()

    import apps.reports.drive as drive_mod

    monkeypatch.setattr(drive_mod, "build", lambda *a, **k: service)

    upload_backup_rotate_3(user=user, content_bytes=b"a", ext="csv")
    upload_backup_rotate_3(user=user, content_bytes=b"b", ext="csv")
    upload_backup_rotate_3(user=user, content_bytes=b"c", ext="csv")
    upload_backup_rotate_3(user=user, content_bytes=b"d", ext="csv")

    items = list_backups(user=user, limit=30, root_name="JobApply", subfolder="backups")
    names = sorted([x.name for x in items])

    assert "autobackup_latest.csv" in names
    assert "autobackup-1.csv" in names
    assert "autobackup-2.csv" in names
    assert len([n for n in names if n.startswith("autobackup")]) == 3
