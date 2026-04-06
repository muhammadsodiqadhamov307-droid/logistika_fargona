# Van Sales ERP - Deployment & System Documentation

**Last Updated:** 2026-03-18
**System Status:** Production
**Primary Administrator:** Muhammadsodiq

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Server Information](#server-information)
3. [Access Credentials](#access-credentials)
4. [GitHub Repository](#github-repository)
5. [Deployment Procedures](#deployment-procedures)
6. [Database Information](#database-information)
7. [File Locations](#file-locations)
8. [Odoo Configuration](#odoo-configuration)
9. [Troubleshooting](#troubleshooting)
10. [Backup Procedures](#backup-procedures)
11. [Common Commands](#common-commands)
12. [Contact Information](#contact-information)

---

## 1. Project Overview

**Project Name:** Van Sales ERP (Pharmaceutical Distribution System)
**Odoo Version:** 19.0 Community Edition
**Module Name:** `van_sales_pharma`
**Primary Language:** Uzbek (uz_UZ)
**Timezone:** Asia/Tashkent
**Currency:** UZS (Uzbek Som)

**Purpose:** 
Mobile-first ERP system for pharmaceutical/medical supply distribution via van sales agents in Uzbekistan.

**Key Features:**
- Mobile POS for agents
- Commission tracking
- Inventory management
- Client debt tracking (Nasiya)
- Supplier management (Taminotchi)
- Telegram integration for clients
- Offline support

---

## 2. Server Information

### Production Server

**Domain:** new-logstics.duckdns.org
**Public IP Address:** 37.221.127.20
**Internal IP:** N/A (VPS)
**Server Location:** Remote VPS
**Operating System:** Ubuntu 24.04 LTS

**Ports:**
- HTTP: 80
- HTTPS: 443
- SSH: 22
- Odoo: 8069 (internal)
- PostgreSQL: 5432 (internal, not exposed)

### Server Specifications

- **CPU:** [Check Server Spec]
- **RAM:** [Check Server Spec]
- **Storage:** [Check Server Spec]
- **Bandwidth:** [Check Server Spec]

---

## 3. Access Credentials

**>> FOR ALL PASSWORDS AND SENSITIVE DETAILS: PLEASE REFER TO THE PRIVATE `CREDENTIALS.md` FILE <<**

### SSH Access

**Username:** root
**Password:** [See CREDENTIALS.md]

**SSH Command:**
```bash
ssh root@37.221.127.20
# OR
ssh root@new-logstics.duckdns.org
```

### Odoo Admin Access

**URL:** https://new-logstics.duckdns.org
**Admin Username:** admin
**Admin Password:** [See CREDENTIALS.md]
**Admin Email:** admin@example.com

**Database Manager:**
**URL:** https://new-logstics.duckdns.org/web/database/manager
**Master Password:** [See CREDENTIALS.md]

### PostgreSQL Database

**Username:** odoo19
**Password:** [See CREDENTIALS.md]
**Database Name:** default
**Host:** localhost
**Port:** 5432

**Connection String:**
```bash
sudo -u postgres psql -U postgres -d default
# OR
psql -U odoo19 -d default
```

### System User Accounts

**Odoo Service User:** odoo19
**Postgres Service User:** postgres

---

## 4. GitHub Repository

**Repository URL:** https://github.com/muhammadsodiqadhamov307-droid/logistika
**Branch Strategy:**
- `main` - Production
- `development` - Development/Testing
- `feature/*` - Feature branches

**Clone Command:**
```bash
git clone https://github.com/muhammadsodiqadhamov307-droid/logistika.git
```

**Repository Structure:**
```
van_sales_pharma/
├── __init__.py
├── __manifest__.py
├── controllers/
├── models/
├── views/
├── static/
├── security/
├── scripts/
└── report/
```

---

## 5. Deployment Procedures

### Initial Deployment

1. **SSH into server:**
   ```bash
   ssh root@37.221.127.20
   ```

2. **Navigate to addons directory:**
   ```bash
   cd /opt/odoo19/custom_addons
   ```

3. **Clone or pull repository:**
   ```bash
   # First time
   git clone https://github.com/muhammadsodiqadhamov307-droid/logistika.git logistika
   
   # Updates
   cd logistika
   git pull origin main
   ```

4. **Set permissions:**
   ```bash
   chown -R odoo19:odoo19 /opt/odoo19/custom_addons/logistika
   ```

5. **Restart Odoo:**
   ```bash
   systemctl restart odoo19
   ```

6. **Upgrade module:**
   ```bash
   sudo su - odoo19 -s /bin/bash -c '/opt/odoo19/odoo-venv/bin/python3 /opt/odoo19/odoo-server/odoo-bin -c /etc/odoo19.conf -u van_sales_pharma -d default --stop-after-init'
   ```

7. **Check logs:**
   ```bash
   journalctl -u odoo19 -n 100 --no-pager
   ```

### Hot-Fix Deployment

```bash
# 1. SSH to server
ssh root@37.221.127.20

# 2. Navigate to module
cd /opt/odoo19/custom_addons/logistika

# 3. Pull latest changes
git pull origin main

# 4. Stop Odoo to ensure smooth upgrade
systemctl stop odoo19

# 5. Upgrade module (if model/view changes)
sudo su - odoo19 -s /bin/bash -c '/opt/odoo19/odoo-venv/bin/python3 /opt/odoo19/odoo-server/odoo-bin -c /etc/odoo19.conf -u van_sales_pharma -d default --stop-after-init'

# 6. Restart Odoo
systemctl start odoo19

# 7. Monitor logs
journalctl -u odoo19 -f
```

---

## 6. Database Information

**Database Name:** default
**Character Encoding:** UTF-8
**Collation:** en_US.UTF-8
**Timezone:** UTC (converted to Asia/Tashkent in application)

### Database Backup

**Backup Location:** `/var/backups/odoo/` (if configured)
**Backup Schedule:** [Configure via Cron]

**Manual Backup Command:**
```bash
sudo -u postgres pg_dump default > backup_$(date +%Y%m%d).sql
```

**Restore Command:**
```bash
sudo -u postgres psql default < backup_20260317.sql
```

### Database Access

```bash
# Access PostgreSQL as postgres user
sudo -u postgres psql

# Access specific database
sudo -u postgres psql -d default

# Common queries
SELECT * FROM res_users WHERE share IS FALSE;
SELECT * FROM van_pos_order WHERE date >= '2026-03-01';
```

---

## 7. File Locations

### Odoo Installation

**Odoo Server:** `/opt/odoo19/odoo-server/`
**Custom Addons:** `/opt/odoo19/custom_addons/`
**Van Sales Module:** `/opt/odoo19/custom_addons/logistika/van_sales_pharma/`
**Virtual Environment:** `/opt/odoo19/odoo-venv/`

### Configuration

**Odoo Config:** `/etc/odoo19.conf`
**Systemd Service:** `/etc/systemd/system/odoo19.service`

### Logs

**Odoo Logs:** 
- Systemd: `journalctl -u odoo19`
- Log file: `/var/log/odoo19/odoo19.log`

**Nginx Logs:**
- Access: `/var/log/nginx/access.log`
- Error: `/var/log/nginx/error.log`

**PostgreSQL Logs:**
- `/var/log/postgresql/postgresql-X-main.log` (Check var/log/postgresql for version)

### Data Storage

**Filestore:** `~odoo19/.local/share/Odoo/filestore/default/`

---

## 8. Odoo Configuration

**Config File:** `/etc/odoo19.conf`

**Key Settings:**
```ini
[options]
addons_path = /opt/odoo19/odoo-server/addons,/opt/odoo19/custom_addons/logistika
admin_passwd = [master-password]
db_host = False
db_port = False
db_user = odoo19
db_password = False
db_name = default
xmlrpc_port = 8069
logfile = /var/log/odoo19/odoo19.log
```

---

## 9. Troubleshooting

### Common Issues

**Issue:** Module not appearing in Apps list
```bash
# Solution: Update apps list
# Settings > Apps > Update Apps List
```

**Issue:** Changes not reflecting (502 Gateway, etc.)
```bash
# Solution: Upgrade module + restart
systemctl stop odoo19
sudo su - odoo19 -s /bin/bash -c '/opt/odoo19/odoo-venv/bin/python3 /opt/odoo19/odoo-server/odoo-bin -c /etc/odoo19.conf -u van_sales_pharma -d default --stop-after-init'
systemctl start odoo19
```

**Issue:** Permission denied errors
```bash
# Solution: Fix ownership
sudo chown -R odoo19:odoo19 /opt/odoo19/custom_addons/logistika
```

**Issue:** Database connection errors
```bash
# Check PostgreSQL status
systemctl status postgresql

# Restart PostgreSQL
systemctl restart postgresql
```

### Log Commands

```bash
# View last 50 Odoo logs
journalctl -u odoo19 -n 50 --no-pager

# Follow Odoo logs in real-time
journalctl -u odoo19 -f

# View logs with errors only
journalctl -u odoo19 | grep -i error

# View logs from specific date
journalctl -u odoo19 --since "2026-03-18"
```

---

## 10. Backup Procedures

### Automated Backup (Cron)

**Cron job:** `/etc/cron.d/odoo-backup` (Create if not exists)

```bash
0 2 * * * root /usr/local/bin/backup-odoo.sh
```

### Manual Backup

```bash
# Database backup
sudo -u postgres pg_dump default | gzip > /var/backups/odoo/db_$(date +\%Y\%m\%d).sql.gz

# Filestore backup
sudo tar -czf /var/backups/odoo/filestore_$(date +\%Y\%m\%d).tar.gz ~odoo19/.local/share/Odoo/filestore/

# Custom addons backup
sudo tar -czf /var/backups/odoo/addons_$(date +\%Y\%m\%d).tar.gz /opt/odoo19/custom_addons/logistika/
```

### Restore Procedures

```bash
# 1. Stop Odoo
systemctl stop odoo19

# 2. Drop and recreate database
sudo -u postgres dropdb default
sudo -u postgres createdb -O odoo19 default

# 3. Restore database
gunzip < /var/backups/odoo/db_20260317.sql.gz | sudo -u postgres psql default

# 4. Start Odoo
systemctl start odoo19
```

---

## 11. Common Commands

### Service Management

```bash
# Restart Odoo
systemctl restart odoo19

# Stop Odoo
systemctl stop odoo19

# Start Odoo
systemctl start odoo19

# Check Odoo status
systemctl status odoo19
```

### Module Management

```bash
# Upgrade specific module
sudo su - odoo19 -s /bin/bash -c '/opt/odoo19/odoo-venv/bin/python3 /opt/odoo19/odoo-server/odoo-bin -c /etc/odoo19.conf -u van_sales_pharma -d default --stop-after-init'

# Install module
sudo su - odoo19 -s /bin/bash -c '/opt/odoo19/odoo-venv/bin/python3 /opt/odoo19/odoo-server/odoo-bin -c /etc/odoo19.conf -i van_sales_pharma -d default --stop-after-init'
```

### File Operations

```bash
# Navigate to module
cd /opt/odoo19/custom_addons/logistika/van_sales_pharma

# Check file permissions
ls -la
```

---

## 12. Contact Information

**Primary Administrator:** Muhammadsodiq
**Email:** [your-email@example.com]

**Technical Support:**
- GitHub Issues: https://github.com/muhammadsodiqadhamov307-droid/logistika/issues

---

## Appendix A: Agent Login Credentials

**(See `CREDENTIALS.md` for actual passwords)**

| Agent Name | Username | Password | Commission % |
|------------|----------|----------|--------------|
| Bahodir aka | bahodir@gmail.com | [See CREDENTIALS.md] | 2% |
| Jahongir | jahongir@gmail.com | [See CREDENTIALS.md] | 2% |
| Muhammadsodiq | muhammadsodiq@gmail.com | [See CREDENTIALS.md] | 2% |

---

## Appendix B: Key Model Relationships

- `res.users` (Agent) → Main agent record
- `van.agent.summary` → Agent dashboard metrics
- `van.product` → Product catalog
- `van.pos.order` → Sales transactions
- `van.payment` → Payment records (Kirim/Chiqim)
- `van.agent.debt` → Agent's individual debts to Admin
- `van.taminotchi` → Suppliers
- `van.trip` / `van.request` → Product loading/transfers
- `res.partner` → Clients (and agents as clients)

---

## Appendix C: Commission Calculation Formulas

```
Yalpi Balans = (Naqt + Kirim) - Kunlik Chiqim (excluding salary payouts)
Agent Oyligi (Earned) = Yalpi Balans × komissiya_foizi / 100
Oylik Olindi = Sum(oylik chiqim payouts)
Oylik Qoldig'i = Agent Oyligi - Oylik Olindi
Sof Balans = Yalpi Balans - Oylik Olindi
Foyda = Σ(actual_sale_price - kelish_narxi) × qty
Agentdan qoladigan = Foyda - Agent Oyligi (earned)
```

---

**END OF DOCUMENTATION**
