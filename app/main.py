"""E-Learning Universitas - Monolithic FastAPI Backend + Frontend UI.

Frontend (Tailwind CSS + Alpine.js) disajikan langsung di root (/) 
sehingga cukup deploy satu repository ke Railway.
"""
import hashlib, hmac, json, os, re, secrets, uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote_plus

import boto3, jwt
from botocore.config import Config
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
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
    if os.getenv("DATABASE_URL"):  # dev lokal / Railway / Supabase
        return os.environ["DATABASE_URL"]
    cred = json.loads(_secret(os.environ["DB_SECRET_ARN"]))
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
    schema_path = Path(__file__).parent / "schema.sql"
    if schema_path.exists():
        with engine.begin() as c:
            c.exec_driver_sql(schema_path.read_text())
    yield


app = FastAPI(title="E-Learning Universitas API", lifespan=lifespan)


# ---------- Frontend HTML UI (Monolithic) ----------
HTML_UI = """<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>E-Learning Universitas - Dashboard Akademik</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
</head>
<body class="bg-slate-50 font-sans min-h-screen" x-data="app()">
    <!-- Header -->
    <header class="bg-indigo-700 text-white shadow-md">
        <div class="max-w-7xl mx-auto px-4 py-4 flex justify-between items-center">
            <div class="flex items-center space-x-3">
                <span class="text-2xl font-bold">🎓 E-Learning Universitas</span>
                <span class="bg-indigo-800 text-xs px-2.5 py-1 rounded-full font-medium">Cloud Private Subnet</span>
            </div>
            <div class="flex items-center space-x-3">
                <a href="/docs" target="_blank" class="bg-indigo-600 hover:bg-indigo-500 px-3 py-1.5 rounded-lg text-sm font-medium transition">📄 API Docs</a>
                <template x-if="token">
                    <div class="flex items-center space-x-3">
                        <span class="text-sm bg-indigo-600 px-3 py-1 rounded-lg" x-text="'Role: ' + role"></span>
                        <button @click="logout()" class="bg-red-500 hover:bg-red-600 px-3 py-1.5 rounded-lg text-sm font-medium transition">Logout</button>
                    </div>
                </template>
            </div>
        </div>
    </header>

    <!-- Main Container -->
    <main class="max-w-7xl mx-auto px-4 py-8">
        <!-- Not Logged In: Auth View -->
        <template x-if="!token">
            <div class="grid md:grid-cols-2 gap-8 max-w-4xl mx-auto mt-6">
                <!-- Login Card -->
                <div class="bg-white p-8 rounded-2xl shadow-md border border-slate-100">
                    <h2 class="text-2xl font-bold text-slate-800 mb-6">Login Akun</h2>
                    <form @submit.prevent="login()" class="space-y-4">
                        <div>
                            <label class="block text-sm font-medium text-slate-600 mb-1">Email</label>
                            <input type="email" x-model="loginForm.email" required class="w-full px-4 py-2 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500 focus:outline-none">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-slate-600 mb-1">Password</label>
                            <input type="password" x-model="loginForm.password" required class="w-full px-4 py-2 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500 focus:outline-none">
                        </div>
                        <button type="submit" class="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-medium py-2.5 rounded-xl transition">Masuk</button>
                    </form>
                </div>

                <!-- Register Card -->
                <div class="bg-white p-8 rounded-2xl shadow-md border border-slate-100">
                    <h2 class="text-2xl font-bold text-slate-800 mb-6">Daftar Baru</h2>
                    <form @submit.prevent="register()" class="space-y-4">
                        <div class="grid grid-cols-2 gap-4">
                            <div>
                                <label class="block text-sm font-medium text-slate-600 mb-1">NIM / NIP</label>
                                <input type="text" x-model="regForm.nim_nip" required class="w-full px-3 py-2 border border-slate-300 rounded-xl focus:outline-none">
                            </div>
                            <div>
                                <label class="block text-sm font-medium text-slate-600 mb-1">Role</label>
                                <select x-model="regForm.role" class="w-full px-3 py-2 border border-slate-300 rounded-xl focus:outline-none">
                                    <option value="mahasiswa">Mahasiswa</option>
                                    <option value="dosen">Dosen</option>
                                </select>
                            </div>
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-slate-600 mb-1">Nama Lengkap</label>
                            <input type="text" x-model="regForm.name" required class="w-full px-3 py-2 border border-slate-300 rounded-xl focus:outline-none">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-slate-600 mb-1">Email</label>
                            <input type="email" x-model="regForm.email" required class="w-full px-3 py-2 border border-slate-300 rounded-xl focus:outline-none">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-slate-600 mb-1">Password (Min. 8 karakter)</label>
                            <input type="password" x-model="regForm.password" required minlength="8" class="w-full px-3 py-2 border border-slate-300 rounded-xl focus:outline-none">
                        </div>
                        <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-medium py-2.5 rounded-xl transition">Daftar</button>
                    </form>
                </div>
            </div>
        </template>

        <!-- Logged In: Dashboard View -->
        <template x-if="token">
            <div>
                <!-- Courses Tab Content -->
                <div>
                    <div class="flex justify-between items-center mb-6">
                        <h3 class="text-xl font-bold text-slate-800">Daftar Mata Kuliah</h3>
                        <template x-if="role === 'dosen' || role === 'admin'">
                            <button @click="showAddCourseModal = true" class="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-xl text-sm font-medium transition">+ Buat Mata Kuliah</button>
                        </template>
                    </div>

                    <!-- Course List Grid -->
                    <div class="grid md:grid-cols-3 gap-6">
                        <template x-for="c in courses" :key="c.id">
                            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 hover:shadow-md transition flex flex-col justify-between">
                                <div>
                                    <div class="flex justify-between items-start mb-3">
                                        <span class="bg-indigo-50 text-indigo-700 text-xs font-bold px-2.5 py-1 rounded-md" x-text="c.code"></span>
                                    </div>
                                    <h4 class="text-lg font-bold text-slate-800 mb-2" x-text="c.name"></h4>
                                </div>
                                <div class="mt-6 pt-4 border-t border-slate-100 flex justify-between items-center">
                                    <button @click="selectCourse(c)" class="text-indigo-600 hover:text-indigo-800 font-medium text-sm">Buka Materi & Tugas →</button>
                                    <template x-if="role === 'mahasiswa'">
                                        <button @click="enroll(c.id)" class="bg-emerald-50 text-emerald-700 hover:bg-emerald-100 px-3 py-1 rounded-lg text-xs font-medium transition">Enroll</button>
                                    </template>
                                </div>
                            </div>
                        </template>
                    </div>
                </div>

                <!-- Selected Course Detail View -->
                <template x-if="selectedCourse">
                    <div class="mt-10 bg-white p-8 rounded-2xl shadow-sm border border-slate-200">
                        <div class="flex justify-between items-center mb-6 pb-4 border-b border-slate-200">
                            <div>
                                <span class="text-xs font-bold text-indigo-600 uppercase tracking-wider" x-text="selectedCourse.code"></span>
                                <h3 class="text-2xl font-bold text-slate-800" x-text="selectedCourse.name"></h3>
                            </div>
                            <button @click="selectedCourse = null" class="text-slate-400 hover:text-slate-600 text-sm font-medium">← Kembali ke Daftar</button>
                        </div>

                        <!-- Materials Section -->
                        <div class="mb-10">
                            <div class="flex justify-between items-center mb-4">
                                <h4 class="text-lg font-bold text-slate-800">Materi Kuliah</h4>
                                <template x-if="role === 'dosen' || role === 'admin'">
                                    <button @click="showAddMaterialModal = true" class="bg-indigo-50 text-indigo-700 hover:bg-indigo-100 px-3 py-1.5 rounded-lg text-xs font-medium transition">+ Tambah Materi</button>
                                </template>
                            </div>
                            <div class="space-y-4">
                                <template x-for="m in materials" :key="m.id">
                                    <div class="p-4 rounded-xl border border-slate-200 bg-slate-50">
                                        <div class="flex justify-between items-start mb-2">
                                            <h5 class="font-semibold text-slate-800" x-text="m.title"></h5>
                                            <span class="text-xs uppercase bg-slate-200 text-slate-700 px-2 py-0.5 rounded font-mono" x-text="m.kind"></span>
                                        </div>
                                        <template x-if="m.kind === 'text'">
                                            <p class="text-slate-600 text-sm whitespace-pre-line" x-text="m.body"></p>
                                        </template>
                                        <template x-if="m.kind === 'youtube' && m.embed_url">
                                            <div class="aspect-video max-w-xl mt-3">
                                                <iframe :src="m.embed_url" class="w-full h-full rounded-lg" frameborder="0" allowfullscreen></iframe>
                                            </div>
                                        </template>
                                        <template x-if="(m.kind === 'file' || m.kind === 'video') && m.url">
                                            <a :href="m.url" target="_blank" class="inline-flex items-center text-indigo-600 hover:underline text-sm font-medium mt-2">📥 Download File / Tonton Video</a>
                                        </template>
                                    </div>
                                </template>
                            </div>
                        </div>
                    </div>
                </template>
            </div>
        </template>
    </main>

    <!-- Modal Buat Course -->
    <div x-show="showAddCourseModal" class="fixed inset-0 bg-black/50 flex items-center justify-center p-4">
        <div class="bg-white p-6 rounded-2xl max-w-md w-full">
            <h3 class="text-xl font-bold text-slate-800 mb-4">Buat Mata Kuliah Baru</h3>
            <form @submit.prevent="createCourse()" class="space-y-4">
                <div>
                    <label class="block text-sm font-medium text-slate-600 mb-1">Kode MK (misal: IF401)</label>
                    <input type="text" x-model="newCourse.code" required class="w-full px-3 py-2 border border-slate-300 rounded-xl">
                </div>
                <div>
                    <label class="block text-sm font-medium text-slate-600 mb-1">Nama Mata Kuliah</label>
                    <input type="text" x-model="newCourse.name" required class="w-full px-3 py-2 border border-slate-300 rounded-xl">
                </div>
                <div class="flex justify-end space-x-3 pt-2">
                    <button type="button" @click="showAddCourseModal = false" class="px-4 py-2 text-slate-600 text-sm font-medium">Batal</button>
                    <button type="submit" class="bg-indigo-600 text-white px-4 py-2 rounded-xl text-sm font-medium">Simpan</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Modal Tambah Materi -->
    <div x-show="showAddMaterialModal" class="fixed inset-0 bg-black/50 flex items-center justify-center p-4">
        <div class="bg-white p-6 rounded-2xl max-w-md w-full">
            <h3 class="text-xl font-bold text-slate-800 mb-4">Tambah Materi Kuliah</h3>
            <form @submit.prevent="createMaterial()" class="space-y-4">
                <div>
                    <label class="block text-sm font-medium text-slate-600 mb-1">Judul Materi</label>
                    <input type="text" x-model="newMaterial.title" required class="w-full px-3 py-2 border border-slate-300 rounded-xl">
                </div>
                <div>
                    <label class="block text-sm font-medium text-slate-600 mb-1">Jenis Materi</label>
                    <select x-model="newMaterial.kind" class="w-full px-3 py-2 border border-slate-300 rounded-xl">
                        <option value="text">Teks</option>
                        <option value="youtube">YouTube Video</option>
                    </select>
                </div>
                <template x-if="newMaterial.kind === 'text'">
                    <div>
                        <label class="block text-sm font-medium text-slate-600 mb-1">Isi Materi</label>
                        <textarea x-model="newMaterial.body" rows="4" class="w-full px-3 py-2 border border-slate-300 rounded-xl"></textarea>
                    </div>
                </template>
                <template x-if="newMaterial.kind === 'youtube'">
                    <div>
                        <label class="block text-sm font-medium text-slate-600 mb-1">URL YouTube</label>
                        <input type="url" x-model="newMaterial.youtube_url" placeholder="https://www.youtube.com/watch?v=..." class="w-full px-3 py-2 border border-slate-300 rounded-xl">
                    </div>
                </template>
                <div class="flex justify-end space-x-3 pt-2">
                    <button type="button" @click="showAddMaterialModal = false" class="px-4 py-2 text-slate-600 text-sm font-medium">Batal</button>
                    <button type="submit" class="bg-indigo-600 text-white px-4 py-2 rounded-xl text-sm font-medium">Simpan</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Script Alpine.js API Logic -->
    <script>
        function app() {
            return {
                apiUrl: window.location.origin,
                token: localStorage.getItem('token') || '',
                role: localStorage.getItem('role') || '',
                courses: [],
                selectedCourse: null,
                materials: [],
                loginForm: { email: '', password: '' },
                regForm: { nim_nip: '', name: '', email: '', role: 'mahasiswa', password: '' },
                showAddCourseModal: false,
                showAddMaterialModal: false,
                newCourse: { code: '', name: '' },
                newMaterial: { title: '', kind: 'text', body: '', youtube_url: '' },

                async login() {
                    try {
                        let res = await fetch(this.apiUrl + '/auth/login', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(this.loginForm)
                        });
                        if (!res.ok) throw new Error('Login gagal. Periksa email & password.');
                        let data = await res.json();
                        this.token = data.access_token;
                        let payload = JSON.parse(atob(this.token.split('.')[1]));
                        this.role = payload.role;
                        localStorage.setItem('token', this.token);
                        localStorage.setItem('role', this.role);
                        this.loadCourses();
                    } catch (err) {
                        alert(err.message);
                    }
                },

                async register() {
                    try {
                        let res = await fetch(this.apiUrl + '/auth/register', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(this.regForm)
                        });
                        if (!res.ok) throw new Error('Registrasi gagal / NIM/Email sudah terdaftar.');
                        alert('Registrasi berhasil! Silakan login.');
                        this.regForm = { nim_nip: '', name: '', email: '', role: 'mahasiswa', password: '' };
                    } catch (err) {
                        alert(err.message);
                    }
                },

                logout() {
                    this.token = '';
                    this.role = '';
                    this.selectedCourse = null;
                    localStorage.removeItem('token');
                    localStorage.removeItem('role');
                },

                async loadCourses() {
                    try {
                        let res = await fetch(this.apiUrl + '/courses', {
                            headers: { 'Authorization': 'Bearer ' + this.token }
                        });
                        if (res.ok) this.courses = await res.json();
                    } catch (err) { console.error(err); }
                },

                async enroll(courseId) {
                    try {
                        let res = await fetch(this.apiUrl + '/courses/' + courseId + '/enroll', {
                            method: 'POST',
                            headers: { 'Authorization': 'Bearer ' + this.token }
                        });
                        if (res.ok) {
                            alert('Berhasil enroll mata kuliah!');
                            this.loadCourses();
                        }
                    } catch (err) { alert('Gagal enroll'); }
                },

                async createCourse() {
                    try {
                        let res = await fetch(this.apiUrl + '/courses', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'Authorization': 'Bearer ' + this.token
                            },
                            body: JSON.stringify(this.newCourse)
                        });
                        if (res.ok) {
                            this.showAddCourseModal = false;
                            this.newCourse = { code: '', name: '' };
                            this.loadCourses();
                        }
                    } catch (err) { alert('Gagal membuat mata kuliah'); }
                },

                async selectCourse(c) {
                    this.selectedCourse = c;
                    try {
                        let res = await fetch(this.apiUrl + '/courses/' + c.id + '/materials', {
                            headers: { 'Authorization': 'Bearer ' + this.token }
                        });
                        if (res.ok) this.materials = await res.json();
                    } catch (err) { console.error(err); }
                },

                async createMaterial() {
                    try {
                        let res = await fetch(this.apiUrl + '/courses/' + this.selectedCourse.id + '/materials', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'Authorization': 'Bearer ' + this.token
                            },
                            body: JSON.stringify(this.newMaterial)
                        });
                        if (res.ok) {
                            this.showAddMaterialModal = false;
                            this.newMaterial = { title: '', kind: 'text', body: '', youtube_url: '' };
                            this.selectCourse(this.selectedCourse);
                        }
                    } catch (err) { alert('Gagal menambahkan materi'); }
                }
            }
        }
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def read_root():
    return HTML_UI


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


# ---------- materi ----------
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
        if key:
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
    with engine.begin() as c:
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
    if u["role"] == "mahasiswa":
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
