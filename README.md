# E-Learning Universitas Berbasis Cloud (AWS)

Project ini = **Infrastructure as Code (Terraform)** + **backend API (FastAPI)** untuk sistem e-learning kampus.

## Arsitektur

```
Mahasiswa/Dosen ──► ALB + WAF (public subnet) ──► EC2 Auto Scaling (private app subnet) ──► RDS PostgreSQL Multi-AZ
                                                           │                                   ElastiCache Redis
                                                           │                                   (private DB subnet, tanpa route internet)
                                                           ├─ presigned URL ─► S3 (materi, tugas, backup)  via VPC Endpoint
Penonton materi ──► CloudFront (OAC) ──► S3 materi          └─ YouTube (embed) untuk video kuliah umum
```

| Lapisan | CIDR | Isi | Internet |
|---|---|---|---|
| Public | 10.0.1.0/24, 10.0.2.0/24 | ALB, NAT GW | Ya (IGW) |
| Private App | 10.0.11.0/24, 10.0.12.0/24 | EC2 (container API) | Keluar saja (NAT) |
| Private DB | 10.0.21.0/24, 10.0.22.0/24 | RDS, Redis | **Tidak ada** |

Proteksi database mahasiswa: private subnet tanpa default route, `publicly_accessible=false`, SG hanya menerima 5432 dari SG-App, NACL subnet DB, enkripsi KMS + TLS wajib (`rds.force_ssl`), password dikelola Secrets Manager, admin lewat SSM (tanpa SSH).

Storage: RDS (data akademik) · S3 `materi` (SSE-S3 + CloudFront) · S3 `tugas` (SSE-KMS, privat) · S3 `backup` (Glacier setelah 30 hari) · Redis · YouTube Unlisted (opsional untuk video kuliah umum).

## Struktur

```
terraform/   vpc, security, storage, database, compute, alb(+WAF), cdn, outputs
app/         main.py (API), schema.sql, Dockerfile
scripts/     deploy_image.sh
docker-compose.yml   dev lokal (Postgres + MinIO + API)
```

## Jalankan lokal

```bash
docker compose up --build
# API docs: http://localhost:8080/docs
```

## Deploy ke AWS

Prasyarat: AWS CLI ter-login, Terraform >= 1.5, Docker.

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # sesuaikan
terraform init
terraform apply        # ~15-25 menit (RDS Multi-AZ + Redis)

../scripts/deploy_image.sh      # build & push image ke ECR, refresh ASG
terraform output alb_dns_name   # buka URL ini -> /docs
```

Untuk produksi: set `environment="prod"`, `single_nat=false`, isi `acm_certificate_arn` (HTTPS) dan `cors_origins` dengan domain kampus.

## Alur upload (video/file besar)

1. Dosen: `POST /courses/{id}/materials/upload-url` -> dapat `upload_url`
2. Browser: `PUT` file langsung ke S3 memakai `upload_url` (header `Content-Type` yang sama)
3. Dosen: `POST /courses/{id}/materials` dengan `kind=video|file` dan `s3_key`
   - Teks: `kind=text` + `body`. Video YouTube: `kind=youtube` + `youtube_url` (embed memakai `youtube-nocookie`).
4. Mahasiswa: alur sama via `/assignments/{id}/submissions/upload-url` lalu `POST /assignments/{id}/submissions`.

Untuk video sangat besar, gunakan multipart upload (CORS sudah mengekspos header `ETag`).

## Endpoint utama

`POST /auth/register|login` · `GET/POST /courses` · `POST /courses/{id}/enroll` · `GET/POST /courses/{id}/materials` · `POST /courses/{id}/assignments` · `POST/GET /assignments/{id}/submissions` · `PUT /submissions/{id}/grade`

## Catatan & pengembangan lanjut

- Kode ini belum dijalankan terhadap akun AWS; jalankan `terraform validate` / `terraform plan` dulu dan review sebelum `apply`.
- Estimasi biaya dev (Multi-AZ + NAT + Redis) cukup terasa; matikan dengan `terraform destroy` bila tidak dipakai.
- Registrasi di API ini hanya demo. Produksi: SSO kampus (SAML/OIDC) atau Cognito + MFA untuk dosen/admin.
- Redis sudah disediakan (env `REDIS_HOST`) tetapi belum dipakai kode; cocok untuk cache daftar materi & rate-limit.
- Transkoding video adaptif: tambahkan AWS MediaConvert (trigger S3 event -> Lambda).
- Tambahkan CloudTrail, AWS Backup, dan alarm CloudWatch (CPU RDS, 5xx ALB).
- Kepatuhan UU PDP No. 27/2022: region Jakarta, enkripsi, audit log, kebijakan retensi.
