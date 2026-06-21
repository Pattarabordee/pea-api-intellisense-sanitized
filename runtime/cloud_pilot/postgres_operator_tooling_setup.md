# PostgreSQL Operator Tooling Setup

Status: `operator_setup_required`  
Mode: `shadow`  
Production send: `blocked`

ใช้ไฟล์นี้เตรียมเครื่อง operator สำหรับ backup/restore drill ของ Render PostgreSQL

## Current Local Status

Latest local check:

```text
pg_dump: not found
pg_restore: not found
psql: not found
DATABASE_URL: not set
RESTORE_TEST_DATABASE_URL: not set
```

ดังนั้น backup/restore drill ยังไม่ควรถูกนับว่าผ่าน

## Install PostgreSQL Client Tools On Windows

ติดตั้ง PostgreSQL client tools อย่างใดอย่างหนึ่ง:

- PostgreSQL installer จาก EnterpriseDB แล้วเลือก command line tools
- Chocolatey: `choco install postgresql`
- Scoop: `scoop install postgresql`

หลังติดตั้ง เปิด PowerShell ใหม่ แล้วตรวจ:

```powershell
pg_dump --version
pg_restore --version
psql --version
```

## Environment Variables

ตั้งค่าเฉพาะใน local PowerShell session หรือ Windows User Environment เท่านั้น ห้าม commit ห้าม paste ใน chat

```powershell
$env:DATABASE_URL = "<Render internal/external database URL>"
$env:RESTORE_TEST_DATABASE_URL = "<non-production restore test database URL>"
```

`RESTORE_TEST_DATABASE_URL` ต้องไม่ใช่ production database

## Backup Drill

```powershell
powershell -ExecutionPolicy Bypass -File ".\runtime\production_cloud_postgres_backup.ps1"
```

Expected result:

```text
Postgres backup created: ...
Mode: shadow; production_send: blocked
```

## Restore Drill

รันเฉพาะกับ non-production restore DB:

```powershell
powershell -ExecutionPolicy Bypass -File ".\runtime\production_cloud_postgres_restore_check.ps1" `
  -BackupFile ".\runtime\backups\postgres\<backup>.dump"
```

Expected result:

```text
Restore check passed. Mode: shadow; production_send: blocked
```

## Safety Rules

- ห้าม restore เข้า production DB
- ห้ามใส่ DB URL ใน GitHub, slide, group chat, screenshot
- ห้าม export raw meter/PEANO/customer identity
- ถ้า restore target เท่ากับ `DATABASE_URL` script ต้อง refuse ทันที
