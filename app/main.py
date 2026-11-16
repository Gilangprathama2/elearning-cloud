"""E-Learning Universitas - backend API (FastAPI).

Alur file besar (video/PDF): browser minta presigned URL -> upload LANGSUNG ke S3
-> kirim metadata ke API. Server aplikasi tidak pernah memegang file video.
"""
import hashlib, hmac, json, os, re, secrets, uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote_plus

import boto3, jwt
from botocore.config import Config
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

REGION = os.getenv("AWS_REGION", "ap-southeast-3")
BUCKET_MATERI = os.getenv("BUCKET_MATERI", "elearning-materi")
BUCKET_TUGAS = os.getenv("BUCKET_TUGAS", "elearning-tugas")
CDN_DOMAIN = os.getenv("CDN_DOMAIN", "")
UPLOAD_TTL, DOWNLOAD_TTL = 900, 900  # presigned URL berlaku 15 menit
MAX_UPLOAD_MB = 2048


# ---------- konfigurasi & koneksi ----------
def _secret(arn: str) -> str:
    sm = boto3.client("secretsmanager", region_name=REGION)
    return sm.get_secret_value(SecretId=arn)["SecretString"]


def _database_url() -> str:
    if os.getenv("DATABASE_URL"):  # dev lokal
        return os.environ["DATABASE_URL"]
    cred = json.loads(_secret(os.environ["DB_SECRET_ARN"]))  # password dari Secrets Manager
    return (f"postgresql+psycopg://{quote_plus(cred['username'])}:{quote_plus(cred['password'])}"
            f"@{os.environ['DB_HOST']}:{os.getenv('DB_PORT', '5432')}/{os.environ['DB_NAME']}?sslmode=require")


JWT_SECRET = _secret(os.environ["JWT_SECRET_ARN"]) if os.getenv("JWT_SECRET_ARN") else os.getenv("JWT_SECRET", "dev-only-secret")
engine = create_engine(_database_url(), pool_size=10, max_overflow=20, pool_pre_ping=True, pool_recycle=1800)

s3 = boto3.client(
    "s3", region_name=REGION, endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
    config=Config(signature_version="s3v4", s3={"addressing_style": "virtual" if not os.getenv("S3_ENDPOINT_URL") else "path"}),
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    with engine.begin() as c:  # DB privat -> skema dibuat dari dalam VPC saat startup
        c.exec_driver_sql((Path(__file__).parent / "schema.sql").read_text())
    yield


app = FastAPI(title="E-Learning Universitas API", lifespan=lifespan)


# ---------- auth ----------
def hash_pw(pw: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 310_000).hex()
    return f"{salt}${h}"


def verify_pw(pw: str, stored: str) -> bool:
    salt, _ = stored.split("$")
    return hmac.compare_digest(hash_pw(pw, salt), stored)


def current_user(authorization: str = Header(...)) -> dict:
    try:
        return jwt.decode(authorization.removeprefix("Bearer "), JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Token tidak valid / kedaluwarsa")


def require(*roles: str):
    def dep(u: dict = Depends(current_user)) -> dict:
        if u["role"] not in roles:
            raise HTTPException(403, "Tidak punya akses")
        return u
    return dep


class RegisterIn(BaseModel):
    nim_nip: str
    name: str
    email: str
    role: Literal["mahasiswa", "dosen"]
    password: str = Field(min_length=8)


class LoginIn(BaseModel):
    email: str
    password: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/register", status_code=201)
def register(d: RegisterIn):
    # Demo: pada produksi gunakan SSO kampus / Cognito dan batasi pendaftaran dosen.
    with engine.begin() as c:
        try:
            c.execute(text("INSERT INTO users(nim_nip,name,email,role,password_hash) VALUES(:n,:nm,:e,:r,:p)"),
                      dict(n=d.nim_nip, nm=d.name, e=d.email, r=d.role, p=hash_pw(d.password)))
        except Exception:
            raise HTTPException(409, "NIM/NIP atau email sudah terdaftar")
    return {"ok": True}


@app.post("/auth/login")
def login(d: LoginIn):
    with engine.connect() as c:
        u = c.execute(text("SELECT id,role,password_hash FROM users WHERE email=:e"), dict(e=d.email)).first()
    if not u or not verify_pw(d.password, u.password_hash):
        raise HTTPException(401, "Email atau password salah")
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    return {"access_token": jwt.encode({"sub": u.id, "role": u.role, "exp": exp}, JWT_SECRET, algorithm="HS256")}


# ---------- helper akses ----------
def _can_access_course(c, user: dict, course_id: int) -> bool:
    if user["role"] == "admin":
        return True
    if user["role"] == "dosen":
        q = "SELECT 1 FROM courses WHERE id=:c AND lecturer_id=:u"
    else:
        q = "SELECT 1 FROM enrollments WHERE course_id=:c AND student_id=:u"
    return c.execute(text(q), dict(c=course_id, u=user["sub"])).first() is not None


def _check_course(user: dict, course_id: int):
    with engine.connect() as c:
        if not _can_access_course(c, user, course_id):
            raise HTTPException(403, "Anda tidak terdaftar pada mata kuliah ini")


def _presign_put(bucket: str, key: str, content_type: str) -> dict:
    url = s3.generate_presigned_url(
        "put_object", Params={"Bucket": bucket, "Key": key, "ContentType": content_type}, ExpiresIn=UPLOAD_TTL)
    return {"upload_url": url, "s3_key": key, "headers": {"Content-Type": content_type}, "expires_in": UPLOAD_TTL}


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:100]


# ---------- mata kuliah ----------
class CourseIn(BaseModel):
    code: str
    name: str


@app.post("/courses", status_code=201)
def create_course(d: CourseIn, u: dict = Depends(require("dosen", "admin"))):
    with engine.begin() as c:
        r = c.execute(text("INSERT INTO courses(code,name,lecturer_id) VALUES(:c,:n,:l) RETURNING id"),
                      dict(c=d.code, n=d.name, l=u["sub"])).first()
    return {"id": r.id}


@app.post("/courses/{course_id}/enroll", status_code=201)
def enroll(course_id: int, u: dict = Depends(require("mahasiswa"))):
    with engine.begin() as c:
        c.execute(text("INSERT INTO enrollments VALUES(:c,:s) ON CONFLICT DO NOTHING"), dict(c=course_id, s=u["sub"]))
    return {"ok": True}


@app.get("/courses")
def my_courses(u: dict = Depends(current_user)):
    q = {"mahasiswa": "SELECT c.id,c.code,c.name FROM courses c JOIN enrollments e ON e.course_id=c.id WHERE e.student_id=:u",
         "dosen": "SELECT id,code,name FROM courses WHERE lecturer_id=:u",
         "admin": "SELECT id,code,name FROM courses"}[u["role"]]
    params = {} if u["role"] == "admin" else dict(u=u["sub"])
    with engine.connect() as c:
        return [dict(r._mapping) for r in c.execute(text(q), params)]


# ---------- materi (dosen unggah teks/file/video/YouTube) ----------
class UploadReq(BaseModel):
    filename: str
    content_type: str = "application/octet-stream"


@app.post("/courses/{course_id}/materials/upload-url")
def material_upload_url(course_id: int, d: UploadReq, u: dict = Depends(require("dosen", "admin"))):
    _check_course(u, course_id)
    return _presign_put(BUCKET_MATERI, f"course-{course_id}/{uuid.uuid4().hex}-{_safe_name(d.filename)}", d.content_type)


class MaterialIn(BaseModel):
    title: str
    kind: Literal["text", "file", "video", "youtube"]
    body: Optional[str] = None
    s3_key: Optional[str] = None
    youtube_url: Optional[str] = None


def _youtube_id(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})", url)
    if not m:
        raise HTTPException(422, "URL YouTube tidak valid")
    return m.group(1)


@app.post("/courses/{course_id}/materials", status_code=201)
def add_material(course_id: int, d: MaterialIn, u: dict = Depends(require("dosen", "admin"))):
    _check_course(u, course_id)
    if d.kind == "text" and not d.body:
        raise HTTPException(422, "body wajib untuk materi teks")
    if d.kind in ("file", "video"):
        if not d.s3_key or not d.s3_key.startswith(f"course-{course_id}/"):
            raise HTTPException(422, "s3_key tidak valid")
    yt = _youtube_id(d.youtube_url) if d.kind == "youtube" and d.youtube_url else None
    if d.kind == "youtube" and not yt:
        raise HTTPException(422, "youtube_url wajib")
    with engine.begin() as c:
        r = c.execute(text("INSERT INTO materials(course_id,title,kind,body,s3_key,youtube_id) "
                           "VALUES(:c,:t,:k,:b,:s,:y) RETURNING id"),
                      dict(c=course_id, t=d.title, k=d.kind, b=d.body, s=d.s3_key, y=yt)).first()
    return {"id": r.id}


@app.get("/courses/{course_id}/materials")
def list_materials(course_id: int, u: dict = Depends(current_user)):
    _check_course(u, course_id)
    with engine.connect() as c:
        rows = c.execute(text("SELECT id,title,kind,body,s3_key,youtube_id,created_at FROM materials "
                              "WHERE course_id=:c ORDER BY created_at DESC"), dict(c=course_id)).all()
    out = []
    for r in rows:
        m = dict(r._mapping)
        key = m.pop("s3_key")
        if key:  # file/video: URL sementara (privat). Alternatif cepat: https://{CDN_DOMAIN}/{key}
            m["url"] = s3.generate_presigned_url("get_object", Params={"Bucket": BUCKET_MATERI, "Key": key}, ExpiresIn=DOWNLOAD_TTL)
        if m["youtube_id"]:
            m["embed_url"] = f"https://www.youtube-nocookie.com/embed/{m['youtube_id']}"
        out.append(m)
    return out


# ---------- tugas ----------
class AssignmentIn(BaseModel):
    title: str
    description: Optional[str] = None
    due_at: Optional[datetime] = None


@app.post("/courses/{course_id}/assignments", status_code=201)
def create_assignment(course_id: int, d: AssignmentIn, u: dict = Depends(require("dosen", "admin"))):
    _check_course(u, course_id)
    with engine.begin() as c:
        r = c.execute(text("INSERT INTO assignments(course_id,title,description,due_at) VALUES(:c,:t,:d,:due) RETURNING id"),
                      dict(c=course_id, t=d.title, d=d.description, due=d.due_at)).first()
    return {"id": r.id}


def _assignment(aid: int):
    with engine.connect() as c:
        a = c.execute(text("SELECT id,course_id,due_at FROM assignments WHERE id=:i"), dict(i=aid)).first()
    if not a:
        raise HTTPException(404, "Tugas tidak ditemukan")
    return a


@app.post("/assignments/{aid}/submissions/upload-url")
def submission_upload_url(aid: int, d: UploadReq, u: dict = Depends(require("mahasiswa"))):
    a = _assignment(aid)
    _check_course(u, a.course_id)
    key = f"assignment-{aid}/student-{u['sub']}/{uuid.uuid4().hex}-{_safe_name(d.filename)}"
    return _presign_put(BUCKET_TUGAS, key, d.content_type)


class SubmissionIn(BaseModel):
    kind: Literal["text", "file", "video"]
    body: Optional[str] = None
    s3_key: Optional[str] = None


@app.post("/assignments/{aid}/submissions", status_code=201)
def submit(aid: int, d: SubmissionIn, u: dict = Depends(require("mahasiswa"))):
    a = _assignment(aid)
    _check_course(u, a.course_id)
    if a.due_at and datetime.now(timezone.utc) > a.due_at:
        raise HTTPException(403, "Batas waktu pengumpulan sudah lewat")
    if d.kind == "text" and not d.body:
        raise HTTPException(422, "body wajib untuk tugas teks")
    if d.kind != "text" and (not d.s3_key or not d.s3_key.startswith(f"assignment-{aid}/student-{u['sub']}/")):
        raise HTTPException(422, "s3_key tidak valid")
    with engine.begin() as c:  # kumpul ulang = timpa submission sebelumnya
        c.execute(text("INSERT INTO submissions(assignment_id,student_id,kind,body,s3_key) VALUES(:a,:s,:k,:b,:key) "
                       "ON CONFLICT (assignment_id,student_id) DO UPDATE SET kind=:k,body=:b,s3_key=:key,submitted_at=now(),grade=NULL"),
                  dict(a=aid, s=u["sub"], k=d.kind, b=d.body, key=d.s3_key))
    return {"ok": True}


@app.get("/assignments/{aid}/submissions")
def list_submissions(aid: int, u: dict = Depends(current_user)):
    a = _assignment(aid)
    _check_course(u, a.course_id)
    sql = ("SELECT s.id,s.student_id,us.name,s.kind,s.body,s.s3_key,s.submitted_at,s.grade FROM submissions s "
           "JOIN users us ON us.id=s.student_id WHERE s.assignment_id=:a")
    params = dict(a=aid)
    if u["role"] == "mahasiswa":  # mahasiswa hanya melihat tugasnya sendiri
        sql += " AND s.student_id=:u"
        params["u"] = u["sub"]
    with engine.connect() as c:
        rows = [dict(r._mapping) for r in c.execute(text(sql), params)]
    for m in rows:
        key = m.pop("s3_key")
        if key:
            m["url"] = s3.generate_presigned_url("get_object", Params={"Bucket": BUCKET_TUGAS, "Key": key}, ExpiresIn=DOWNLOAD_TTL)
    return rows


class GradeIn(BaseModel):
    grade: float = Field(ge=0, le=100)


@app.put("/submissions/{sid}/grade")
def grade(sid: int, d: GradeIn, u: dict = Depends(require("dosen", "admin"))):
    with engine.begin() as c:
        row = c.execute(text("SELECT a.course_id FROM submissions s JOIN assignments a ON a.id=s.assignment_id WHERE s.id=:i"),
                        dict(i=sid)).first()
        if not row:
            raise HTTPException(404, "Submission tidak ditemukan")
        if not _can_access_course(c, u, row.course_id):
            raise HTTPException(403, "Bukan mata kuliah Anda")
        c.execute(text("UPDATE submissions SET grade=:g WHERE id=:i"), dict(g=d.grade, i=sid))
    return {"ok": True}
