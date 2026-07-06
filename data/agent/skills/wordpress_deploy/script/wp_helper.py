#!/usr/bin/env btpython
"""
WordPress Helper - Site creation and WP-CLI management.
Usage: btpython wp_helper.py <command> [JSON args]
"""
import os
import sys
import json
import subprocess
import sqlite3
import time
import re
import shutil
import random
import string
import traceback
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# ========== Configuration ==========
PANEL_PATH = '/www/server/panel'
PANEL_DB = os.path.join(PANEL_PATH, 'data/default.db')
WP_CLI_PATH = '/usr/local/bin/wp'
VHOST_NGINX = os.path.join(PANEL_PATH, 'vhost/nginx')
VHOST_APACHE = os.path.join(PANEL_PATH, 'vhost/apache')
VHOST_OLS = os.path.join(PANEL_PATH, 'vhost/openlitespeed')
VHOST_OLS_DETAIL = os.path.join(PANEL_PATH, 'vhost/openlitespeed/detail')
VHOST_REWRITE = os.path.join(PANEL_PATH, 'vhost/rewrite')
WWWLOGS = '/www/wwwlogs'

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger('wp_helper')


# ========== Output ==========
def json_out(data: Dict[str, Any]) -> None:
    """Output JSON to stdout."""
    print(json.dumps(data, ensure_ascii=False, default=str))


def run_command(commands: Dict[str, callable]) -> None:
    """Main command dispatcher."""
    if len(sys.argv) < 2:
        print(f"Usage: btpython wp_helper.py <command> [JSON args]")
        print(f"Available: {', '.join(commands.keys())}")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd not in commands:
        json_out({"status": False, "msg": f"Unknown command: {cmd}, available: {', '.join(commands.keys())}"})
        sys.exit(1)
    args: Dict[str, Any] = {}
    if len(sys.argv) > 2:
        try:
            args = json.loads(sys.argv[2])
        except json.JSONDecodeError:
            json_out({"status": False, "msg": f"JSON parse error: {sys.argv[2]}"})
            sys.exit(1)
    if not isinstance(args, dict):
        json_out({"status": False, "msg": f"Invalid args type: expected dict, got {type(args).__name__}"})
        sys.exit(1)
    try:
        logger.info(f"Executing command: {cmd}")
        json_out(commands[cmd](args))
    except Exception as e:
        logger.error(f"Command {cmd} failed: {e}\n{traceback.format_exc()}")
        json_out({"status": False, "msg": f"Execution error: {str(e)}", "traceback": traceback.format_exc()})
        sys.exit(1)


# ========== Database ==========
def get_panel_db() -> sqlite3.Connection:
    """Get panel database connection."""
    conn = sqlite3.connect(PANEL_DB)
    conn.row_factory = sqlite3.Row
    return conn


def db_query(sql: str, params: Tuple = (), fetchone: bool = False) -> Any:
    """Execute SELECT query."""
    conn = get_panel_db()
    try:
        cur = conn.execute(sql, params)
        if fetchone:
            row = cur.fetchone()
            return dict(row) if row else None
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def db_execute(sql: str, params: Tuple = ()) -> int:
    """Execute INSERT/UPDATE/DELETE query. Returns last rowid."""
    conn = get_panel_db()
    try:
        conn.execute(sql, params)
        conn.commit()
        return conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    finally:
        conn.close()


def get_mysql_root_password() -> str:
    """Get MySQL root password from panel config."""
    row = db_query('SELECT mysql_root FROM config WHERE id=1', fetchone=True)
    return (row.get('mysql_root', '') if row else '') or ''


def get_mysql_bin() -> str:
    """Find MySQL binary path."""
    for p in ['/www/server/mysql/bin/mysql', '/usr/bin/mysql', '/usr/local/bin/mysql']:
        if os.path.exists(p):
            return p
    return 'mysql'


def run_mysql_sql(sql: str, root_password: Optional[str] = None) -> Tuple[bool, str]:
    """Execute MySQL SQL statement."""
    if root_password is None:
        root_password = get_mysql_root_password()
    mysql_bin = get_mysql_bin()
    try:
        result = subprocess.run(
            [mysql_bin, '-uroot', f'-p{root_password}', '-e', sql],
            capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0, result.stderr.strip()
    except Exception as e:
        return False, str(e)


# ========== Common Utilities ==========
def get_php_bin(version: str) -> str:
    """Get PHP binary path for version."""
    return f'/www/server/php/{version}/bin/php'


def detect_php_version() -> Optional[str]:
    """Detect highest installed PHP version."""
    php_base = "/www/server/php"
    if not os.path.exists(php_base):
        return None
    versions = []
    for d in os.listdir(php_base):
        if d.isdigit() and os.path.exists(os.path.join(php_base, d, 'bin/php')):
            versions.append(d)
    return max(versions) if versions else None


def get_date() -> str:
    """Get current datetime string."""
    return time.strftime('%Y-%m-%d %X')


def run_cmd(cmd: List[str], timeout: int = 60) -> Tuple[bool, str, str]:
    """Execute command safely (no shell=True)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, '', f'Command timed out after {timeout}s'
    except Exception as e:
        return False, '', str(e)


def shell(cmd: str, timeout: int = 60) -> Tuple[bool, str, str]:
    """Execute shell command (for simple operations only)."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, '', f'Command timed out after {timeout}s'
    except Exception as e:
        return False, '', str(e)


def write_file(path: str, content: str, mode: str = 'w') -> None:
    """Write content to file, creating directories if needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as f:
        f.write(content)


def is_multi_webservice() -> bool:
    """Check if multiple web services are installed."""
    return (os.path.exists('/www/server/nginx/sbin/nginx')
            and os.path.exists('/www/server/apache/bin/apachectl')
            and os.path.exists('/usr/local/lsws/bin/lswsctrl'))


def resolve_site(s_id: int) -> Tuple[Optional[Dict], Optional[str]]:
    """Resolve site info and PHP version from site ID."""
    try:
        s_id = int(s_id)
    except (ValueError, TypeError):
        return None, None
    site = db_query('SELECT id,path,name FROM sites WHERE id=?', (s_id,), fetchone=True)
    if not site:
        return None, None
    conf_path = os.path.join(VHOST_NGINX, f'{site["name"]}.conf')
    php_ver = None
    if os.path.exists(conf_path):
        with open(conf_path, 'r') as f:
            m = re.search(r'enable-php-(\d+)\.conf', f.read())
            if m:
                php_ver = m.group(1)
    if not php_ver:
        php_ver = detect_php_version()
    return site, php_ver


# ========== WP-CLI ==========
def ensure_wp_cli() -> bool:
    """Check and install WP-CLI if not present."""
    if os.path.exists(WP_CLI_PATH):
        return True
    try:
        logger.info("Installing WP-CLI...")
        subprocess.run(
            ['curl', '-sSL', '-o', WP_CLI_PATH,
             'https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar'],
            capture_output=True, timeout=120
        )
        os.chmod(WP_CLI_PATH, 0o755)
        return os.path.exists(WP_CLI_PATH)
    except Exception as e:
        logger.error(f"WP-CLI installation failed: {e}")
        return False


def run_wp_cli(args: List[str], php_version: str, cwd: Optional[str] = None) -> Tuple[bool, str, str]:
    """Execute WP-CLI command."""
    php_bin = get_php_bin(php_version)
    cmd = [php_bin, '-d', 'memory_limit=512M', WP_CLI_PATH, '--allow-root'] + args
    if cwd:
        cmd += ['--path=' + cwd]
    return run_cmd(cmd, timeout=300)


# ========== Web Config Generation ==========
def gen_nginx_conf(domain: str, php_version: str, site_path: str) -> str:
    """Generate Nginx virtual host configuration."""
    rewrite_conf = os.path.join(VHOST_REWRITE, domain + '.conf')
    return f'''server
{{
    listen 80;
    listen [::]:80;
    server_name {domain};
    index index.php index.html index.htm default.php default.htm default.html;
    root {site_path};

    #SSL-START
    #error_page 404/404.html;
    #SSL-END

    #ERROR-PAGE-START
    error_page 404 /404.html;
    error_page 502 /502.html;
    #ERROR-PAGE-END

    #PHP-INFO-START
    include enable-php-{php_version}.conf;
    #PHP-INFO-END

    #REWRITE-START
    include {rewrite_conf};
    #REWRITE-END

    location ~ ^/(\\.user\\.ini|\\.htaccess|\\.git|\\.env|\\.svn|\\.project|LICENSE|README.md)
    {{
        return 404;
    }}

    location ~ \\.well-known{{
        allow all;
    }}

    if ( $uri ~ "^/\\.well-known/.*\\.(php|jsp|py|js|css|lua|ts|go|zip|tar\\.gz|rar|7z|sql|bak)$" ) {{
        return 403;
    }}

    location ~ .*\\.(gif|jpg|jpeg|png|bmp|swf)$
    {{
        expires      30d;
        error_log /dev/null;
        access_log /dev/null;
    }}

    location ~ .*\\.(js|css)?$
    {{
        expires      12h;
        error_log /dev/null;
        access_log /dev/null;
    }}
    access_log  {WWWLOGS}/{domain}.log;
    error_log  {WWWLOGS}/{domain}.error.log;
}}'''


def gen_apache_conf(domain: str, php_version: str, site_path: str, port: str = '80') -> str:
    """Generate Apache virtual host configuration."""
    php_proxy = f'unix:/tmp/php-cgi-{php_version}.sock|fcgi://localhost'
    return f'''<VirtualHost *:{port}>
    ServerAdmin webmaster@example.com
    DocumentRoot "{site_path}"
    ServerName {time.strftime('%Y%m%d%H%M%S')}.{domain}
    ServerAlias {domain}
    #errorDocument 404 /404.html
    ErrorLog "{WWWLOGS}/{domain}-error_log"
    CustomLog "{WWWLOGS}/{domain}-access_log" combined

    #DENY FILES
     <Files ~ (\\.user\\.ini|\\.htaccess|\\.git|\\.env|\\.svn|\\.project|LICENSE|README.md)$>
       Order allow,deny
       Deny from all
    </Files>

    #PHP
    <FilesMatch \\.php$>
            SetHandler "proxy:{php_proxy}"
    </FilesMatch>

    #PATH
    <Directory "{site_path}">
        SetOutputFilter DEFLATE
        Options FollowSymLinks
        AllowOverride All
        Require all granted
        DirectoryIndex index.php index.html index.htm default.php default.html default.htm
    </Directory>
</VirtualHost>'''


def gen_ols_conf(domain: str, php_version: str, site_path: str) -> Tuple[str, str]:
    """Generate OpenLiteSpeed configuration."""
    if not site_path.endswith('/'):
        site_path += '/'
    main_conf = f"""
#VHOST {domain} START
virtualhost {domain} {{
vhRoot {site_path}
configFile {PANEL_PATH}/vhost/openlitespeed/detail/{domain}.conf
allowSymbolLink 1
enableScript 1
restrained 1
setUIDMode 0
}}
#VHOST {domain} END
"""
    detail_conf = f'''docRoot                   $VH_ROOT
vhDomain                  $VH_NAME
adminEmails               example@example.com
enableGzip                1
enableIpGeo               1

index  {{
  useServer               0
  indexFiles index.php,index.html
}}

errorlog /www/wwwlogs/$VH_NAME_ols.error_log {{
  useServer               0
  logLevel                ERROR
  rollingSize             10M
}}

accesslog /www/wwwlogs/$VH_NAME_ols.access_log {{
  useServer               0
  logFormat               '%{{X-Forwarded-For}}i %h %l %u %t "%r" %>s %b "%{{Referer}}i" "%{{User-Agent}}i"'
  logHeaders              5
  rollingSize             10M
  keepDays                10  compressArchive         1
}}

scripthandler  {{
  add                     lsapi:{domain} php
}}

extprocessor {domain} {{
  type                    lsapi
  address                 UDS://tmp/lshttpd/{domain}.sock
  maxConns                300
  env                     LSAPI_CHILDREN=300
  env                     LSAPI_AVOID_FORK=1
  initTimeout             600
  retryTimeout            5
  persistConn             1
  pcKeepAliveTimeout      30
  respBuffer              0
  autoStart               1
  path                    /usr/local/lsws/lsphp{php_version}/bin/lsphp
  extUser                 www
  extGroup                www
  memSoftLimit            2047M
  memHardLimit            2047M
  procSoftLimit           1000
  procHardLimit           1100
}}

phpIniOverride  {{
php_admin_value open_basedir "/tmp/:{site_path}"
}}

expires {{
    enableExpires           1
    expiresByType           image/*=A43200,text/css=A43200,application/x-javascript=A43200,application/javascript=A43200,font/*=A43200,application/x-font-ttf=A43200
}}

rewrite  {{
  enable                  1
  autoLoadHtaccess        1
  include {PANEL_PATH}/vhost/openlitespeed/proxy/{domain}/urlrewrite/*.conf
  include {PANEL_PATH}/vhost/apache/redirect/{domain}/*.conf
  include {PANEL_PATH}/vhost/openlitespeed/redirect/{domain}/*.conf
}}
include {PANEL_PATH}/vhost/openlitespeed/proxy/{domain}/*.conf
'''
    return main_conf, detail_conf


def write_wordpress_rewrite(domain: str) -> None:
    """Write WordPress rewrite rules."""
    rewrite_path = os.path.join(VHOST_REWRITE, domain + '.conf')
    with open(rewrite_path, 'w') as f:
        f.write("location /\n{\n    try_files $uri $uri/ /index.php?$args;\n}\n\n"
                "rewrite /wp-admin$ $scheme://$host$uri/ permanent;\n")


def ensure_ols_listen_conf(domain: str) -> None:
    """Ensure OpenLiteSpeed listen configuration includes domain."""
    listen_dir = os.path.join(PANEL_PATH, 'vhost', 'openlitespeed', 'listen')
    os.makedirs(listen_dir, exist_ok=True)
    listen_file = os.path.join(listen_dir, '80.conf')
    listen_conf = ''
    if os.path.exists(listen_file):
        with open(listen_file, 'r') as f:
            listen_conf = f.read()
    map_line = f'\tmap\t{domain} {domain}'
    if listen_conf:
        rep = r'map\s+{0}.*'.format(re.escape(domain))
        if not re.search(rep, listen_conf):
            listen_conf = re.sub(r'secure\s*0', 'secure 0\n' + map_line, listen_conf)
    else:
        listen_conf = f"\nlistener Default80{{\n    address *:80\n    secure 0\n{map_line}\n}}\n"
    with open(listen_file, 'w') as f:
        f.write(listen_conf)


def write_all_web_configs(domain: str, php_version: str, site_path: str) -> None:
    """Write all web server configurations (Nginx, Apache, OLS)."""
    multi = is_multi_webservice()
    apache_port = '8288' if multi else '80'
    write_file(os.path.join(VHOST_NGINX, domain + '.conf'), gen_nginx_conf(domain, php_version, site_path))
    write_file(os.path.join(VHOST_APACHE, domain + '.conf'), gen_apache_conf(domain, php_version, site_path, port=apache_port))
    htaccess = os.path.join(site_path, '.htaccess')
    if not os.path.exists(htaccess):
        write_file(htaccess, ' ')
        shell(f'chmod 644 {htaccess}')
        shell(f'chown www:www {htaccess}')
    ols_main, ols_detail = gen_ols_conf(domain, php_version, site_path)
    write_file(os.path.join(VHOST_OLS, domain + '.conf'), ols_main, mode='a+')
    write_file(os.path.join(VHOST_OLS_DETAIL, domain + '.conf'), ols_detail)
    ensure_ols_listen_conf(domain)
    write_wordpress_rewrite(domain)
    ok, _, _ = shell('nginx -t')
    if ok:
        shell('nginx -s reload')


# ========== Site Cleanup ==========
def _cleanup_site(s_id: int, d_id: int, domain: str, db_name: str, db_user: str, site_path: str) -> None:
    """Clean up site resources on failure."""
    for fn, args in [
        (db_execute, ('DELETE FROM domain WHERE pid=?', (s_id,))),
        (db_execute, ('DELETE FROM wordpress_onekey WHERE s_id=?', (s_id,))),
        (db_execute, ('DELETE FROM databases WHERE id=?', (d_id,))),
        (db_execute, ('DELETE FROM sites WHERE id=?', (s_id,))),
    ]:
        try:
            fn(*args)
        except Exception as e:
            logger.warning(f"Cleanup query failed: {e}")
    run_mysql_sql(
        f"DROP DATABASE IF EXISTS `{db_name}`; DROP USER IF EXISTS `{db_user}`@'localhost'; FLUSH PRIVILEGES;",
        get_mysql_root_password()
    )
    if os.path.exists(site_path):
        shutil.rmtree(site_path, ignore_errors=True)
    for p in [
        os.path.join(VHOST_NGINX, domain + '.conf'),
        os.path.join(VHOST_APACHE, domain + '.conf'),
        os.path.join(VHOST_OLS_DETAIL, domain + '.conf'),
        os.path.join(VHOST_REWRITE, domain + '.conf'),
    ]:
        if os.path.exists(p):
            os.remove(p)
    ols_main = os.path.join(VHOST_OLS, domain + '.conf')
    if os.path.exists(ols_main):
        try:
            content = open(ols_main, 'r').read()
            content = re.sub(f'#VHOST {domain} START.*?#VHOST {domain} END\n?', '', content, flags=re.DOTALL)
            open(ols_main, 'w').write(content)
        except Exception as e:
            logger.warning(f"OLS cleanup failed: {e}")
    shell('nginx -s reload')


# ========== Commands ==========

def cmd_create_site(args: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new WordPress site."""
    required = ['weblog_title', 'user_name', 'admin_email', 'admin_password']
    for key in required:
        if key not in args or not args[key]:
            return {"status": False, "msg": f"Missing required parameter: {key}"}
    domain = args.get('domain', 'example.com')
    if not isinstance(domain, str):
        domain = str(domain)
    domain = domain.strip().lower()
    if not domain:
        domain = 'example.com'
    password = args['admin_password']
    if not isinstance(password, str):
        password = str(password)
    if len(password) < 8:
        return {"status": False, "msg": "Password must be at least 8 characters"}
    existing = db_query('SELECT id FROM sites WHERE name=?', (domain,), fetchone=True)
    if existing:
        return {"status": False, "msg": f"Site {domain} already exists (ID: {existing['id']})"}
    if not os.path.exists("/www/server/mysql"):
        return {"status": False, "msg": "MySQL is not installed. Please install MySQL first."}
    if not os.path.exists("/www/server/php"):
        return {"status": False, "msg": "PHP is not installed. Please install PHP first."}
    php_version = args.get('php_version', '')
    if not isinstance(php_version, str):
        php_version = str(php_version) if php_version else ''
    php_version = php_version.strip()
    if not php_version:
        php_version = detect_php_version()
        if not php_version:
            return {"status": False, "msg": "No installed PHP version detected"}
    if not os.path.exists(f"/www/server/php/{php_version}"):
        available = [d for d in os.listdir("/www/server/php/") if d.isdigit()]
        return {"status": False, "msg": f"PHP {php_version} not installed. Available: {', '.join(sorted(available))}"}
    if not ensure_wp_cli():
        return {"status": False, "msg": "WP-CLI download failed. Please install manually to /usr/local/bin/wp"}

    site_path = f"/www/wwwroot/{domain}"
    db_name = 'wp_' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    db_user = db_name
    db_password = password
    now = get_date()
    prefix = args.get('prefix', 'wp_')
    s_id = d_id = None

    try:
        os.makedirs(site_path, exist_ok=True)
        ok, err = run_mysql_sql(
            f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci; "
            f"CREATE USER `{db_user}`@'localhost' IDENTIFIED BY '{db_password}'; "
            f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO `{db_user}`@'localhost'; FLUSH PRIVILEGES;"
        )
        if not ok:
            return {"status": False, "msg": f"Failed to create database: {err}"}

        d_id = db_execute(
            'INSERT INTO databases (pid,sid,db_type,name,username,password,accept,type,ps,addtime) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (0, 0, 0, db_name, db_user, db_password, '127.0.0.1', 'MySQL', domain, now)
        )
        s_id = db_execute(
            'INSERT INTO sites (name,path,status,ps,type_id,addtime,project_type,project_config) VALUES (?,?,?,?,?,?,?,?)',
            (domain, site_path, '1', args.get('ps', domain), 0, now, 'WP2', '{}')
        )
        db_execute('UPDATE databases SET pid=? WHERE id=?', (s_id, d_id))
        db_execute('INSERT INTO domain (pid,name,port,addtime) VALUES (?,?,?,?)', (s_id, domain, '80', now))

        ok, out, err = run_wp_cli(['core', 'download', '--locale=' + args.get('language', 'en_US'), '--force'], php_version, cwd=site_path)
        if not ok:
            raise Exception(f"WordPress download failed: {err or out}")
        ok, out, err = run_wp_cli([
            'config', 'create', f'--dbname={db_name}', f'--dbuser={db_user}',
            f'--dbpass={db_password}', '--dbhost=localhost', f'--dbprefix={prefix}', '--force',
        ], php_version, cwd=site_path)
        if not ok:
            raise Exception(f"wp-config.php creation failed: {err or out}")
        title = args['weblog_title']
        admin_user = args['user_name']
        admin_email = args['admin_email']
        ok, out, err = run_wp_cli([
            'core', 'install', f'--url=http://{domain}', f'--title={title}',
            f'--admin_user={admin_user}', f'--admin_password={password}',
            f'--admin_email={admin_email}', '--skip-email'
        ], php_version, cwd=site_path)
        if not ok:
            raise Exception(f"WordPress installation failed: {err or out}")

        write_all_web_configs(domain, php_version, site_path)
        shell(f'chown -R www:www {site_path}')
        shell(f'chmod -R 755 {site_path}')
        db_execute(
            'INSERT INTO wordpress_onekey (s_id,d_id,prefix,user,pass,site_type) VALUES (?,?,?,?,?,?)',
            (s_id, d_id, prefix, args['user_name'], password, 'Default category')
        )
        logger.info(f"WordPress site created: {domain} (ID: {s_id})")
        return {
            "status": True, "msg": "WordPress site created successfully", "domain": domain,
            "path": site_path, "s_id": s_id, "d_id": d_id, "database": db_name,
            "admin_url": f"http://{domain}/wp-admin", "admin_user": args['user_name'],
        }
    except Exception as e:
        if s_id is not None:
            _cleanup_site(s_id, d_id or 0, domain, db_name, db_user, site_path)
        return {"status": False, "msg": f"Deployment failed: {str(e)}"}


def cmd_site_info(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get site details by domain or s_id."""
    domain = args.get('domain', '')
    if not isinstance(domain, str):
        domain = str(domain) if domain else ''
    domain = domain.strip().lower()
    s_id = args.get('s_id')
    if s_id is not None:
        try:
            s_id = int(s_id)
        except (ValueError, TypeError):
            return {"status": False, "msg": f"Invalid s_id: {s_id}"}
        site = db_query('SELECT id,path,name,status,ps,project_type FROM sites WHERE id=?', (s_id,), fetchone=True)
    elif domain:
        site = db_query('SELECT id,path,name,status,ps,project_type FROM sites WHERE name=?', (domain,), fetchone=True)
    else:
        return {"status": False, "msg": "Please provide domain or s_id"}
    if not site:
        return {"status": False, "msg": "Site not found"}
    site['database'] = db_query('SELECT name,username,password FROM databases WHERE pid=?', (site['id'],), fetchone=True)
    site['domains'] = db_query('SELECT name,port FROM domain WHERE pid=?', (site['id'],))
    return {"status": True, "data": site}


def cmd_list_sites(args: Dict[str, Any]) -> Dict[str, Any]:
    """List all WordPress sites."""
    return {"status": True, "data": db_query("SELECT id,name,path,status,ps FROM sites WHERE project_type='WP2'")}


def cmd_ensure_wp_cli(args: Dict[str, Any]) -> Dict[str, Any]:
    """Check and install WP-CLI if not present."""
    if ensure_wp_cli():
        return {"status": True, "msg": "WP-CLI is ready", "path": WP_CLI_PATH}
    return {"status": False, "msg": "WP-CLI installation failed. Please install manually: curl -o /usr/local/bin/wp https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar && chmod +x /usr/local/bin/wp"}


def cmd_site_wcli(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get WP-CLI command prefix for a site."""
    s_id = args.get('s_id')
    if s_id is None:
        return {"status": False, "msg": "Please provide s_id"}
    try:
        s_id = int(s_id)
    except (ValueError, TypeError):
        return {"status": False, "msg": f"Invalid s_id: {s_id}"}
    site, php_ver = resolve_site(s_id)
    if not site:
        return {"status": False, "msg": "Site not found"}
    php_bin = get_php_bin(php_ver)
    site_path = site['path']
    prefix = f"{php_bin} -d memory_limit=512M {WP_CLI_PATH} --allow-root --path={site_path}"
    return {
        "status": True, "domain": site['name'], "path": site_path,
        "php_bin": php_bin, "wp_cli": WP_CLI_PATH, "cmd_prefix": prefix,
    }


def cmd_wp_cli(args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute WP-CLI command for a site."""
    s_id = args.get('s_id')
    wp_args = args.get('args', [])
    if s_id is None:
        return {"status": False, "msg": "Please provide s_id"}
    try:
        s_id = int(s_id)
    except (ValueError, TypeError):
        return {"status": False, "msg": f"Invalid s_id: {s_id}"}
    if not wp_args:
        return {"status": False, "msg": "Please provide args (WP-CLI subcommand argument list)"}
    site, php_ver = resolve_site(s_id)
    if not site:
        return {"status": False, "msg": "Site not found"}
    php_bin = get_php_bin(php_ver)
    site_path = site['path']
    cmd = [php_bin, '-d', 'memory_limit=512M', WP_CLI_PATH, '--allow-root', f'--path={site_path}'] + wp_args
    returncode, stdout, stderr = run_cmd(cmd, timeout=300)
    return {"status": returncode, "stdout": stdout, "stderr": stderr}


# ========== Entry Point ==========
run_command({
    'create-site': cmd_create_site,
    'site-info': cmd_site_info,
    'list-sites': cmd_list_sites,
    'ensure-wp-cli': cmd_ensure_wp_cli,
    'site-wcli': cmd_site_wcli,
})
