CREATE TABLE IF NOT EXISTS users (
  id            SERIAL PRIMARY KEY,
  nim_nip       VARCHAR(30) UNIQUE NOT NULL,
  name          VARCHAR(120) NOT NULL,
  email         VARCHAR(150) UNIQUE NOT NULL,
  role          VARCHAR(12) NOT NULL CHECK (role IN ('mahasiswa','dosen','admin')),
  password_hash TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS courses (
  id          SERIAL PRIMARY KEY,
  code        VARCHAR(20) UNIQUE NOT NULL,
  name        VARCHAR(150) NOT NULL,
  lecturer_id INT NOT NULL REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS enrollments (
  course_id  INT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  student_id INT NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
  PRIMARY KEY (course_id, student_id)
);

-- kind: text (isi di body) | file (PDF/PPT di S3) | video (file video di S3) | youtube (embed)
CREATE TABLE IF NOT EXISTS materials (
  id          SERIAL PRIMARY KEY,
  course_id   INT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  title       VARCHAR(200) NOT NULL,
  kind        VARCHAR(10) NOT NULL CHECK (kind IN ('text','file','video','youtube')),
  body        TEXT,
  s3_key      TEXT,
  youtube_id  VARCHAR(20),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_materials_course ON materials(course_id);

CREATE TABLE IF NOT EXISTS assignments (
  id          SERIAL PRIMARY KEY,
  course_id   INT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  title       VARCHAR(200) NOT NULL,
  description TEXT,
  due_at      TIMESTAMPTZ
);

-- kind: text | file | video
CREATE TABLE IF NOT EXISTS submissions (
  id            SERIAL PRIMARY KEY,
  assignment_id INT NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
  student_id    INT NOT NULL REFERENCES users(id),
  kind          VARCHAR(10) NOT NULL CHECK (kind IN ('text','file','video')),
  body          TEXT,
  s3_key        TEXT,
  submitted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  grade         NUMERIC(5,2),
  UNIQUE (assignment_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_submissions_assignment ON submissions(assignment_id);
