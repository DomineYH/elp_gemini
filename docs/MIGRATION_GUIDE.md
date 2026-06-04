# Authentication System Migration Guide

> **⚠️ SUPERSEDED by #91** — The email → username/nickname migration described below
> has itself been superseded by **id-login** (user-chosen `user_id` + password).
> See `docs/plans/2026-06-04-issue-91-id-auth-email-removal.md` for the current system.
> This document is kept for historical reference only.

## Overview
The authentication system has been migrated from email/password to username/nickname authentication.

## Changes Summary

### Database Schema Changes
- **Added**: `username` column (unique, required, indexed)
- **Added**: `nickname` column (required)
- **Modified**: `email` column (now optional)
- **Modified**: `hashed_password` column (now optional)

### Authentication Flow Changes
**Before:**
- Login with: email + password
- Password verification via bcrypt hashing

**After:**
- Login with: username + nickname
- Direct nickname matching (no hashing)

### Admin Credentials
**Old:** admin@example.com / admin_password
**New:** admin / admin

## Migration Process

### Automatic Migration (Recommended)
When you restart the application after updating the code, if the old database schema is detected, you'll see an error. Follow these steps:

1. **Backup and reset database:**
   ```bash
   bash scripts/reset_database.sh
   ```

2. **Start application:**
   ```bash
   python -m uvicorn app.main:app --reload
   ```

The new database will be created automatically with the correct schema and admin user.

### Manual Migration (Advanced)
If you need more control over the migration process:

```bash
python scripts/migrate_to_username_auth.py
```

This script will:
1. Backup existing database with timestamp
2. Delete old database files
3. Create new database with updated schema
4. Seed initial data (admin user)

### Rollback
If you need to rollback to the previous version:

1. Stop the application
2. Restore from backup:
   ```bash
   cp data/app.db.backup.YYYYMMDD_HHMMSS data/app.db
   ```
3. Revert code changes to previous commit

## Verification

### 1. Check Database Schema
```bash
sqlite3 data/app.db ".schema users"
```

Expected output should include:
```sql
username VARCHAR(255) NOT NULL,
nickname VARCHAR(255) NOT NULL,
email VARCHAR(255),
hashed_password VARCHAR(255),
```

### 2. Verify Admin User
```bash
sqlite3 data/app.db "SELECT id, username, nickname, is_admin FROM users WHERE username='admin';"
```

Expected output:
```
1|admin|admin|1
```

### 3. Test Login
1. Navigate to: http://localhost:8000/login
2. Enter credentials:
   - **Username**: admin
   - **Nickname**: admin
3. Click "로그인"
4. You should be redirected to the admin dashboard

## Code Changes Reference

### Files Modified
1. **app/models/users.py** - User model schema
2. **app/schemas/users.py** - API request/response models
3. **app/services/auth_service.py** - Authentication logic
4. **app/routers/auth.py** - Login endpoint
5. **app/templates/user/login.html** - Login form UI
6. **app/db.py** - Database seeding

### New Files
1. **scripts/migrate_to_username_auth.py** - Python migration script
2. **scripts/reset_database.sh** - Bash reset script
3. **docs/MIGRATION_GUIDE.md** - This guide

## Troubleshooting

### Error: "no such column: users.username"
**Cause**: Old database schema still exists
**Solution**: Run `bash scripts/reset_database.sh`

### Error: "UNIQUE constraint failed: users.username"
**Cause**: Trying to create duplicate username
**Solution**: Check existing users with:
```bash
sqlite3 data/app.db "SELECT username FROM users;"
```

### Login fails with correct credentials
**Cause**: Case sensitivity or whitespace in credentials
**Solution**:
1. Verify exact username/nickname in database
2. Ensure no trailing spaces in form inputs
3. Check application logs for authentication failures

## Security Considerations

### Authentication Weakness
⚠️ **Important**: The new authentication system uses direct nickname matching without password hashing. This is suitable for:
- Internal tools
- Development environments
- Trusted user bases

**Not recommended for:**
- Public-facing applications
- Systems handling sensitive data
- Compliance-required environments

### Recommended Enhancements
If you need stronger security:

1. **Add password field back:**
   - Keep username/nickname fields
   - Add password verification
   - Use bcrypt hashing

2. **Implement session management:**
   - Add session timeout
   - Implement CSRF protection
   - Add rate limiting

3. **Add multi-factor authentication:**
   - SMS/Email verification
   - TOTP-based 2FA
   - Hardware security keys

## Support

If you encounter issues during migration:
1. Check the backup files in `data/app.db.backup.*`
2. Review application logs
3. Verify all code changes were applied correctly
4. Ensure dependencies are up to date: `pip install -r requirements.txt`

## Changelog

### Version 2.0.0 (2025-11-14)
- **BREAKING**: Migrated from email/password to username/nickname authentication
- Added username and nickname fields to User model
- Updated authentication logic to use username/nickname matching
- Created migration scripts for database schema update
- Updated login UI to reflect new fields
- Changed admin credentials to admin/admin

---

**Last Updated**: 2025-11-14
**Migration Tool Version**: 1.0.0
