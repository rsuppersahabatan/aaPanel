---
name: aaPanel WordPress
description: >
  Create and manage WordPress sites on aaPanel servers. Use this skill when users want to:
  deploy new WordPress sites, install/activate themes and plugins via WP-CLI, get site info,
  list WordPress sites, manage WordPress installations, or perform any WP-CLI operations.
  Also use for: troubleshooting WP deployments, PHP version detection, or WordPress site management.
  Trigger keywords: WordPress, WP, deploy WP, install WP, WP theme, WP plugin, create site.
---

# aaPanel WordPress

> **STOP. Do NOT read wp_helper.py. Do NOT run --help.**
> All commands, parameters, and usage are in this document.
> Execute commands directly using the format and tables below.
> Reading the script file will waste time and provide no useful information.

---

## Script Path

The wp_helper.py script is located at:
`/www/server/panel/data/agent/skills/wordpress_deploy/script/wp_helper.py`

Always use this absolute path when calling the script via btpython.

---

## Core Rules

1. **Read this SKILL.md completely before doing anything.** Do NOT skip sections — read the entire document first, then execute.
2. **NEVER read wp_helper.py or run --help.** Everything you need is in this document.
3. **NEVER show raw commands, code blocks, or btpython paths to users.** Execute directly, report as plain text.
4. **Never let users type commands.** Always execute via RunCommand.
5. **On error** (`"status": false`): report to user, do NOT retry automatically.
6. **Max 8 RunCommand calls** per task.
7. **Forbidden operations**: delete site, drop database, delete files.

---

## Two Modes

This skill operates in two modes. Determine which one applies before doing anything.

### Mode 1: Create a new WordPress site

**Steps — execute directly, do NOT read script, do NOT run --help, do NOT check existing sites:**

1. Collect parameters from user: domain (required), site title. Other params use defaults.
2. Execute immediately:
   `btpython /www/server/panel/data/agent/skills/wordpress_deploy/script/wp_helper.py create-site '{"domain":"<domain>","weblog_title":"<title>","user_name":"admin","admin_email":"admin@example.com","admin_password":"<auto_or_user_provided>"}'`
3. Report result to user: site URL, admin URL, admin_user, admin_password.

If `create-site` returns an error about missing MySQL, PHP, or web server → see Environment Check section below.

**Do NOT**: list sites first, check databases, read the script, run --help, or explore tools. Just execute create-site directly.

### Mode 2: Query or modify an existing WordPress site

For anything else on an existing site (themes, plugins, posts, pages, options, users, db, core update, etc.):

1. `btpython /www/server/panel/data/agent/skills/wordpress_deploy/script/wp_helper.py site-info '{"domain":"<domain>"}'` → get `s_id`
2. `btpython /www/server/panel/data/agent/skills/wordpress_deploy/script/wp_helper.py site-wcli '{"s_id":<id>}'` → get `cmd_prefix`
3. RunCommand: `{cmd_prefix} <wp-cli subcommand>`

The script does NOT have a `wp-cli` subcommand. Use `site-wcli` to get the prefix, then call WP-CLI directly.

---

## Default Values

| Parameter | Default |
|-----------|---------|
| user_name | admin |
| admin_email | admin@example.com |
| admin_password | Auto-generated 12-char strong password |
| php_version | Auto-detect highest installed |
| language | en_US |
| prefix | wp_ |

**domain is always required.** Ask user if not provided.

---

## Commands

**Example execution pattern**:
```
btpython /www/server/panel/data/agent/skills/wordpress_deploy/script/wp_helper.py create-site '{"domain":"example.com","weblog_title":"My Blog","user_name":"admin","admin_email":"admin@example.com","admin_password":"StrongPass123!"}'
```

### create-site

Create a new WordPress site with database, web server config (Nginx/Apache/OLS), and WP-CLI installation. Automatically generates wp-config.php, sets file permissions, and writes rewrite rules. Returns site ID, database name, and admin login URL.

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| domain | Yes | string | Domain name |
| weblog_title | Yes | string | Site title |
| user_name | Yes | string | Admin username |
| admin_email | Yes | string | Admin email |
| admin_password | Yes | string | Admin password (min 8 chars) |
| php_version | No | string | PHP version (e.g. "82", "81") |
| language | No | string | WP language, default "en_US" |
| prefix | No | string | DB table prefix, default "wp_" |
| ps | No | string | Site remark |

**Returns**: status, domain, path, s_id, d_id, database, admin_url, admin_user

### site-info

Get site details by domain or s_id.

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| domain | One of | string | Domain name |
| s_id | One of | int | Site ID |

**Returns**: status, data.id, data.path, data.name, data.status, data.database, data.domains

### list-sites

List all WordPress sites (project_type=WP2). No parameters.

### ensure-wp-cli

Check and install WP-CLI if missing. Call before any WP-CLI operations.

### site-wcli

Returns the WP-CLI command prefix for a site. Required before any theme/plugin/core/option/db/user operation — different sites may use different PHP versions, so the prefix must be resolved per-site.

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| s_id | Yes | int | Site ID (from `site-info` or `list-sites`) |

**Returns**: `cmd_prefix` — a string like `/www/server/php/82/bin/php -d memory_limit=512M /usr/local/bin/wp --allow-root --path=/www/wwwroot/example.com`

**Usage**: Append WP-CLI subcommand to `cmd_prefix`, execute via RunCommand.

**Example flow** (install plugin on site ID 166):
1. `btpython /www/server/panel/data/agent/skills/wordpress_deploy/script/wp_helper.py site-wcli '{"s_id":166}'` → get `cmd_prefix`
2. RunCommand: `{cmd_prefix} plugin install redis-cache --activate`

**Common WP-CLI subcommands**:

| Operation | Append to cmd_prefix |
|-----------|---------------------|
| Install theme | `theme install <slug> --activate` |
| List themes | `theme list` |
| Activate theme | `theme activate <slug>` |
| Install plugin | `plugin install <slug> --activate` |
| List plugins | `plugin list` |
| Activate plugin | `plugin activate <slug>` |
| Deactivate plugin | `plugin deactivate <slug>` |
| Update WP core | `core update` |
| List users | `user list` |
| Search-replace | `search-replace "old" "new" --dry-run` |
| Get option | `option get <option_name>` |
| Set option | `option update <option_name> <value>` |
| Export DB | `db export /tmp/backup.sql` |
| Import DB | `db import /tmp/backup.sql` |
| List posts | `post list --post_type=post --fields=ID,post_title,post_status --format=table` |
| Get post content | `post get <post_id> --field=post_content` |
| Update post content | `post update <post_id> --post_content='<new content>'` |
| List pages | `post list --post_type=page --fields=ID,post_title,post_status --format=table` |
| Search posts | `post list --s='<keyword>' --fields=ID,post_title --format=table` |
| Count posts | `post list --post_type=post --format=count` |

---

## Workflows

### Create new site
1. Collect: domain, site title, admin info
2. `create-site` → report site URL, admin URL, admin_user, admin_password

### Any existing site operation (Mode 2)
1. `btpython /www/server/panel/data/agent/skills/wordpress_deploy/script/wp_helper.py site-info '{"domain":"<domain>"}'` → `s_id`
2. `btpython /www/server/panel/data/agent/skills/wordpress_deploy/script/wp_helper.py site-wcli '{"s_id":<id>}'` → `cmd_prefix`
3. RunCommand: `{cmd_prefix} <wp-cli subcommand>`

### Resolve Site ID
- Domain given → `btpython ...wp_helper.py site-info '{"domain":"xxx"}'` → data.id
- Vague request → `btpython ...wp_helper.py list-sites '{}'` → match by name/path
- Just created → use returned s_id
- Not found → ask whether to create

**Never fabricate post content or IDs. Always query first.**

---

## Environment Check & Error Handling

### Missing environment components (MySQL, PHP, Web Server)

When `create-site` returns an error about missing MySQL, PHP, or web server:

1. Read the error message to identify **which specific component** is missing or errored (MySQL / PHP / Nginx / Apache / OpenLiteSpeed).
2. Report the missing component to the user with a clear message, for example:
   > "Creation failed: MySQL is not installed. Please go to aaPanel App Store to install MySQL and try again."
   > "Creation failed: PHP is not installed. Please go to aaPanel App Store to install PHP and try again."
   > "Creation failed: Web server (Nginx/Apache) is not installed. Please go to aaPanel App Store to install one and try again."
3. **STOP immediately after reporting.** Do NOT try to fix the issue, do NOT suggest workarounds, do NOT check for alternatives, do NOT proceed with any other action. Just report and wait for the user.

**Key**: always name the exact missing component in the error message — do not use generic "environment error". Never attempt to resolve environment issues yourself.

### Other errors

- **PHP errors / PHP not working**: report to user: "PHP is not installed or has errors. Please go to aaPanel App Store to install PHP and try again."
- **PHP version mismatch**: show available versions
- **WP-CLI download failed**: provide manual install command
- **Site already exists**: show existing site ID
- **Database creation failed**: check MySQL root password
- **WordPress download failed**: check network connectivity
