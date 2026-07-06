#coding: utf-8
#-------------------------------------------------------------------
# aaPanel
#-------------------------------------------------------------------
# Copyright (c) 2015-2017 aaPanel(www.aapanel.com) All rights reserved.
#-------------------------------------------------------------------
# Author: FAN <fan@aapanel.com>
#-------------------------------------------------------------------

#------------------------------
# 引导页一键部署
#------------------------------
import public, os, time, shutil, json, re, sys,math
import threading

from public.validate import Param


class GuidePage:

    def __init__(self):
        "php-8.3  mysql-8.0/mariadb-11.4   node-26.1.0/24.15.0/22.22.3"
        self.status_file = '/tmp/guide_page_install.log'
        self.lock_file =  '/tmp/guide_page_install.lock'
        self.guide_config = os.path.join(public.get_panel_path(), 'data', 'guide_config.json')
        self.default_service = {'display_name':'Web Server', 'name':'nginx','version' : '1.30' }
        self.php_version = ['82', '83', '84']

    # 引导页一键部署总入口
    def guide_page_install(self, get):
        """
        引导页一键部署统一入口。
        流程：参数校验 -> 异步函数 -> 日志初始化 -> 依赖安装 - > 部署
        """
        try:
            get.validate([
                Param('install_type').String(),
                Param('param').Json()
            ], [
                public.validate.trim_filter(),
            ])

            install_type = get.install_type
            param = json.loads(get.param)

            # 提前进行参数校验
            val_res = self._validate_params(install_type, param)
            if val_res['status'] is False:
                return public.return_message(-1, 0, val_res['msg'])

            clean_param = val_res['data']

            if not public.progress_acquire_lock(self.lock_file):
                return public.return_message(-1, 0, public.lang('Other tasks are being deployed. Please wait!'))

            task_mapping = {
                'wp': self.install_wp_site,
                'nodejs': self.install_nodejs_project,
                'proxy': self.install_proxy_project,
                'php': self.install_php_site
            }
            if install_type not in task_mapping:
                return public.return_message(-1, 0, public.lang('Unsupported installation type.'))

            from concurrent.futures import ThreadPoolExecutor

            thread = ThreadPoolExecutor(max_workers=1)
            task_func = task_mapping[install_type]

            started = threading.Event()
            thread.submit(task_func, clean_param, started)
            started.wait(timeout=5)  # 阻塞直到 Worker 写入自己的线程 ID
            self.save_config(install_type, param)
            public.set_module_logs(f'GuidePage', f'Installation_{install_type}')
            public.set_module_logs(f'GuidePage', 'Total_installation_count')
            return public.return_message(0, 0, 'Successful startup!')
        except Exception as ex:
            import traceback
            traceback.print_exc()
            return public.return_message(-1, 0, str(ex))

    # 安装的依赖列表
    def _init_plugin(self, install_type, param):
        # ===========================此处添加依赖===========================================
        # 同步安装的插件 必填 install_tmp_path，用于解压导入安装包

        install_list = [self.default_service]
        if install_type == 'php':
            install_list.append({'display_name':'PHP','name': 'php', 'version': param['version']})
            if param['database'] == 'mysql':
                install_list.append({'display_name':'MySql','name' : 'mysql', 'version' : '8.0'})
            elif param['database'] == 'mariadb':
                install_list.append({'display_name':'MariaDB','name': 'mysql', 'version': 'mariadb_11.4'})

        elif install_type == 'wp':
            install_list.append({'display_name':'PHP','name': 'php', 'version': '83'})
            install_list.append({'display_name':'MySql','name': 'mysql', 'version': '8.0'})

        elif install_type == 'proxy':
            pass

        elif install_type == 'nodejs':
            install_list.append({'display_name':'Node.js Manager', 'name': 'nodejs', 'version': '2.3', 'install_tmp_path': '/www/server/panel/temp/nodejs'})

        # ===========================此处添加依赖===========================================
        return install_list

    # 参数校验
    def _validate_params(self, install_type: str, param: dict) -> dict:
        """
        独立的参数校验与清洗函数
        返回结构: {'status': True/False, 'msg': '错误信息', 'data': 清洗后的参数字典}
        """
        try:
            clean_data = {}

            # --- 1. WordPress 参数校验 ---
            if install_type == 'wp':
                required_fields = ['domain', 'ssl_auto', 'title', 'language', 'email']
                for field in required_fields:
                    if field not in param or not str(param[field]).strip():
                        return {'status': False, 'msg': f'Missing required parameter: {field}', 'data': {}}

                clean_data['domain'] = str(param['domain']).strip()
                clean_data['ssl_auto'] = param['ssl_auto']
                clean_data['title'] = str(param['title']).strip()
                clean_data['language'] = str(param['language']).strip()
                clean_data['email'] = str(param['email']).strip()

            # --- 2. 纯 PHP 网站参数校验 ---
            elif install_type == 'php':
                required_fields = ['domain', 'ssl_auto' , 'version']
                for field in required_fields:
                    if field not in param or not str(param[field]).strip():
                        return {'status': False, 'msg': f'Missing required parameter: {field}', 'data': {}}

                clean_data['domain'] = str(param['domain']).strip()
                clean_data['ssl_auto'] = param['ssl_auto']
                clean_data['version'] = str(param['version'].strip())
                if clean_data['version'] not in self.php_version:
                    return {'status': False, 'msg': f'Missing required parameter: php version', 'data': {}}

                # 可选数据库参数校验
                db_type = str(param.get('database', '')).strip().lower()
                clean_data['database'] = db_type

                if db_type in ['mysql', 'mariadb']:
                    if not param.get('datauser') or not param.get('datapassword'):
                        return {'status': False, 'msg': 'Database user and password are required when database is enabled.',
                                'data': {}}
                    clean_data['datauser'] = str(param['datauser']).strip()
                    clean_data['datapassword'] = str(param['datapassword']).strip()
                else:
                    clean_data['database'] = ''
                    clean_data['datauser'] = ''
                    clean_data['datapassword'] = ''

            # --- 3. nodejs项目参数校验 ---
            elif install_type == 'nodejs':
                # 服务校验
                if public.get_webserver() in ['apache', 'openlitespeed']:
                    return {'status': False,
                            'msg': public.lang("The deployment of the introduction page only supports Nginx."),
                            'data': {}}

                required_fields = ['domain', 'project_name', 'version', 'package_manager', 'template', 'port']
                for field in required_fields:
                    if field not in param or not str(param[field]).strip():
                        return {'status': False, 'msg': f'Missing required parameter: {field}', 'data': {}}

                allowed_templates = ['express', 'astro', 'nestjs', 'nextjs', 'fastify']
                template = str(param['template']).strip().lower()
                if template not in allowed_templates:
                    return {'status': False, 'msg': f'Unsupported template: {param["template"]}. Allowed: {", ".join(allowed_templates)}', 'data': {}}

                allowed_managers = ['npm', 'yarn', 'pnpm']
                package_manager = str(param['package_manager']).strip().lower()
                if package_manager not in allowed_managers:
                    return {'status': False, 'msg': f'Unsupported package manager: {param["package_manager"]}. Allowed: {", ".join(allowed_managers)}', 'data': {}}

                clean_data['domain'] = str(param['domain']).strip()
                # clean_data['ssl_auto'] = str(param['ssl_auto']).strip()
                clean_data['project_name'] = str(param['project_name']).strip()
                clean_data['version'] = str(param['version']).strip()
                clean_data['package_manager'] = package_manager
                clean_data['template'] = template
                port_str = str(param['port']).strip()
                if not port_str.isdigit():
                    return {'status': False, 'msg': 'Port must be a positive integer.', 'data': {}}
                port_int = int(port_str)
                if port_int < 1 or port_int > 65535:
                    return {'status': False, 'msg': 'Port must be between 1 and 65535.', 'data': {}}
                if port_int < 1024:
                    return {'status': False, 'msg': 'Port must be >= 1024 (privileged ports are not allowed).', 'data': {}}
                import socket
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    if sock.connect_ex(('127.0.0.1', port_int)) == 0:
                        return {'status': False, 'msg': f'Port {port_int} is already in use.', 'data': {}}
                clean_data['port'] = port_str

            # --- 4. proxy项目参数校验 ---
            elif install_type == 'proxy':
                # 服务校验
                if public.get_webserver() in ['apache', 'openlitespeed']:
                    return {'status': False,
                            'msg': public.lang("The deployment of the introduction page only supports Nginx."),
                            'data': {}}

                required_fields = ['domain', 'ssl_auto', 'proxy_pass', 'proxy_cache', 'proxy_host']
                for field in required_fields:
                    if field not in param or not str(param[field]).strip():
                        return {'status': False, 'msg': f'Missing required parameter: {field}', 'data': {}}

                clean_data['domain'] = str(param['domain']).strip()
                clean_data['ssl_auto'] = str(param['ssl_auto']).strip()
                clean_data['proxy_cache'] = str(param['proxy_cache']).strip()
                clean_data['proxy_host'] = str(param['proxy_host']).strip()
                clean_data['proxy_pass'] = str(param['proxy_pass']).strip()

            else:
                return {'status': False, 'msg': f'Unknown installation type: {install_type}', 'data': {}}

            return {'status': True, 'msg': 'success', 'data': clean_data}
        except Exception as ex:
            import traceback
            traceback.print_exc()
            return {'status': False, 'msg': str(ex), 'data': {}}

    # 安装wp网站
    def install_wp_site(self, param, started=None):
        """
        一键部署 WordPress（后台异步运行）
        """
        task_status = os.path.join('/tmp', 'wp_aapanel_deploy.log')
        step_index = 0
        progress = 0
        service_count = self._init_log_structure('wp', param)
        public.writeFile(self.lock_file, str(threading.get_ident()))
        if started:
            started.set()
        try:
            # 安装依赖服务（每个服务独立步骤，由 install_plugin 内部按 step_index + idx 写入）
            ok = self.install_plugin('wp', param, step_index)
            if not ok:
                return

            progress = 55
            step_index = service_count
            self.write_deploy_log(step_index=step_index, ps="Creating a WordPress site...", progress=progress, status=0)

            from panel_site_v2 import panelSite
            site_obj = panelSite()
            # 获取wp最新版本
            package_version = '7.0'
            package_version_list = site_obj.get_wp_versions({'php_version_short':'83'})
            if package_version_list['status'] == 0:
                package_version = package_version_list['message'][0].get('version')
            webname = json.dumps({'domain': param['domain'], 'domainlist': [], 'count': 0})
            datapassword = public.GetRandomString(16)
            password = public.GetRandomString(16)
            admin = public.GetRandomString(12)
            datauser = param['domain'].replace('.', '_').replace('-', '_')[:16]
            site_args = public.to_dict_obj({
                'webname': webname,
                'type': 'PHP',
                'ps': param['domain'],
                'path': '/www/wwwroot/' + param['domain'],
                'version': '83',
                'sql': 'MySQL',
                'datauser': datauser,
                'datapassword': datapassword,
                'codeing': 'utf8',
                'port': '80',
                'ssl_auto': str(param['ssl_auto']),
                'project_type': 'WP2',
                'weblog_title': param['title'],
                'language': param['language'],
                'user_name':admin,
                'password': password,
                'pw_weak': 'on',
                'email': param['email'],
                'prefix': 'wp_',
                'enable_cache': '0',
                'package_version': package_version
            })

            if os.path.exists(task_status):
                os.remove(task_status)

            result = site_obj.AddWPSite(site_args)
            if result.get('status') != 0:
                raise ValueError(result.get('message', {}).get('result', result.get('message', result)))

            # 初始化wp日志监控
            wp_step_map = [
                ('parameter_verification', service_count, 60),
                ('create_website', service_count, 72),
                ('optional_configurations', service_count, 84),
                ('initialize_wp_website', service_count + 1, 96),
            ]
            last_progress = progress
            reported_steps = set()

            # 10分钟超时
            used_time = 0
            while used_time < 600:
                if not os.path.exists(task_status):
                    time.sleep(1)
                    used_time += 1
                    continue

                try:
                    wp_log = json.loads(public.readFile(task_status))
                except Exception:
                    time.sleep(1)
                    used_time += 1
                    continue

                # 获取相应的日志信息，异步监控状态机
                for key, guide_step, base_progress in wp_step_map:
                    step_data = wp_log.get(key, {})
                    step_status = int(step_data.get('status', 2))
                    if step_status == 1 and key not in reported_steps:
                        last_progress = max(last_progress, base_progress)
                        # 状态调整，create_website/optional_configurations合并
                        status = 1
                        if key in ['create_website','parameter_verification']:
                            status = 0
                        self.write_deploy_log(
                            step_index=guide_step,
                            ps=step_data.get('ps', ''),
                            progress=last_progress,
                            status=status,
                            error_msg=step_data.get('error', '')
                        )
                        reported_steps.add(key)
                        continue
                    if step_status == 0:
                        last_progress = max(last_progress, base_progress)
                        self.write_deploy_log(
                            step_index=guide_step,
                            ps=step_data.get('ps', ''),
                            progress=last_progress,
                            status=0,
                            error_msg=step_data.get('error', '')
                        )
                        break
                    if step_status == -1:
                        self.write_deploy_log(
                            step_index=guide_step,
                            ps=step_data.get('ps', 'An error has occurred.'),
                            progress=last_progress,
                            status=-1,
                            error_msg=step_data.get('error', '')
                        )
                        return

                if int(wp_log.get('status', 0)) == 1:
                    failed_step = None
                    for key, guide_step, base_progress in wp_step_map:
                        step_data = wp_log.get(key, {})
                        if int(step_data.get('status', 2)) == -1:
                            failed_step = (guide_step, step_data)
                            break
                    if failed_step:
                        guide_step, step_data = failed_step
                        self.write_deploy_log(
                            step_index=guide_step,
                            ps=step_data.get('ps', 'An error has occurred.'),
                            progress=last_progress,
                            status=-1,
                            error_msg=step_data.get('error', '')
                        )
                        return

                    res = {
                        'domain': param['domain'],
                        'databaseStatus': True,
                        'databaseUser': site_args.datauser,
                        'databasePass': site_args.datapassword,
                        'wordpressUser': site_args.user_name,
                        'wordpressPass': site_args.password,
                        'php': 'PHP-83'
                    }
                    self.write_deploy_log(step_index=service_count + 2, ps="WordPress deployment successful", progress=100, status=1, result=res)
                    return

                time.sleep(2)
                used_time += 2

            raise TimeoutError('WordPress deployment timed out.')
        except Exception as ex:
            self.write_deploy_log(step_index=step_index, ps="An error has occurred.", progress=progress, status=-1,error_msg=str(ex))
        finally:
            public.progress_release_lock(self.lock_file)

    # 安装php网站
    def install_php_site(self, param, started=None):
        """
        一键部署 纯PHP网站（后台异步运行）
        """
        service_count = self._init_log_structure('php', param)
        thread_id = threading.get_ident()
        public.writeFile(self.lock_file, str(thread_id))
        if started:
            started.set()

        step_index = 0
        progress = 0
        try:
            # 安装依赖服务（每个服务独立步骤）
            ok = self.install_plugin('php', param, step_index)
            if not ok:
                return

            # 创建网站与数据库
            progress = 55
            step_index = service_count
            self.write_deploy_log(step_index=step_index, ps="Start creating the website...", progress=progress, status=0)
            from panel_site_v2 import panelSite
            site_obj = panelSite()
            webname = json.dumps({'domain': param['domain'], 'domainlist': [], 'count': 0})
            site_args = public.to_dict_obj({
                'webname': webname,
                'type': 'PHP',
                'ps': param['domain'],
                'path': '/www/wwwroot/' + param['domain'],
                'version': param['version'],
                'sql': 'MySQL' if param['database'] else '',
                'datapassword': param['datapassword'],
                'datauser' : param['datauser'],
                'codeing': 'utf8mb4',
                'port': '80',
                'type_id': 0,
                'force_ssl': 0,
                'ftp': False,
                'is_create_default_file': True,
                'ssl_auto': param['ssl_auto'],
                'sub_dir': '',
                'project_type': 'PHP',
            })
            result = site_obj.AddSite(site_args)
            if result.get('status') != 0:
                raise ValueError(f"Failed to create the website: {result['message'].get('result')}")

            res = {
                "siteId": result['message'].get('siteId'),
                "domain": param['domain'],
                "databaseStatus": result['message'].get('databaseStatus'),
                "databaseUser": result['message'].get('databaseUser', ''),
                "databasePass": result['message'].get('databasePass', ''),
                'site_path': '/www/wwwroot/' + param['domain'],
                'php' : 'PHP-'+param['version']
            }
            self.write_deploy_log(step_index=step_index, ps="Success in creation", progress=100, status=1, result=res)
        except Exception as ex:
            self.write_deploy_log(step_index=step_index, ps="An error has occurred.", progress=progress, status=-1,error_msg=str(ex))
        finally:
            public.progress_release_lock(self.lock_file)

    # nodejs项目部署
    def install_nodejs_project(self, param, started=None):
        """
        一键部署 Node.js 项目（后台异步运行）
        流程：安装插件 -> 安装Node.js版本 -> 部署项目
        """
        service_count = self._init_log_structure('nodejs', param)
        public.writeFile(self.lock_file, str(threading.get_ident()))
        if started:
            started.set()

        step_index = 0
        progress = 0
        try:
            # 安装依赖服务（每个服务独立步骤）
            ok = self.install_plugin('nodejs', param, step_index)
            if not ok:
                return

            # 安装Node.js + 部署项目
            progress = 55
            step_index = service_count
            self.write_deploy_log(step_index=step_index, ps="Installing Node.js and deploying project...", progress=progress, status=0)
            version = param['version']
            package_manager = param.get('package_manager', 'npm')
            template = param['template']
            project_name = param['project_name']
            port = str(param['port'])
            project_path = os.path.join('/www/wwwroot', project_name)
            if os.path.exists(project_path):
                project_name = project_name + '_' + str(time.time())[-4:]
                project_path = os.path.join('/www/wwwroot', project_name)
                os.makedirs(project_path, mode=0o755, exist_ok=True)

            # 1. 安装Node.js版本 + PM2 + 包管理器 + 设为默认
            node_res = self._install_nodejs_with_modules(version, package_manager)
            if not node_res.get('status'):
                raise ValueError(node_res.get('error_msg', 'Node.js installation failed'))
            progress = 60
            self.write_deploy_log(step_index=step_index, ps="Node.js runtime ready!", progress=progress, status=1)
            time.sleep(2)

            step_index = service_count + 1
            self.write_deploy_log(step_index=step_index, ps="Scaffolding project files...", progress=progress, status=0)

            # 2. 按框架执行脚手架命令（Express/Fastify 需预建目录，NestJS/Next.js CLI 自行建目录，Astro 手动创建）
            if template in ('express', 'fastify'):
                if os.path.exists(project_path):
                    shutil.rmtree(project_path)
                os.makedirs(project_path, mode=0o755, exist_ok=True)
            elif template == 'astro':
                if os.path.exists(project_path):
                    shutil.rmtree(project_path)
                self._scaffold_astro(project_path, port)
            else:
                # CLI 脚手架会自己创建目录，若已存在则先清理
                if os.path.exists(project_path):
                    shutil.rmtree(project_path)

            if template != 'astro':
                desc, cmd = self._get_scaffold_tasks(template, package_manager, project_name, project_path)
                self.write_deploy_log(step_index=step_index, ps=desc, progress=progress, status=0)
                out, err = public.ExecShell(cmd)
                if err and 'error' in err:
                    raise ValueError(f"{desc} failed: {err.strip()}")

            # Next.js: .env 供 next dev 使用，next start 的 PORT 由启动脚本 export 注入
            if template == 'nextjs':
                public.writeFile(os.path.join(project_path, '.env'), f'PORT={port}\n')

            # NestJS CLI 生成的 main.ts 硬编码 app.listen(3000)，需 patch 为读取 PORT 环境变量
            if template == 'nestjs':
                self._patch_nestjs_main(project_path, port)

            # Express/Fastify 需要手写入口文件
            if template in ('express', 'fastify'):
                self._write_entry_file(project_path, template, port)

            progress = 75
            self.write_deploy_log(step_index=step_index, ps="Installing dependencies...", progress=progress, status=0)

            # 4. 安装项目依赖
            install_cmd = f'cd {project_path} && {package_manager} install'
            out, err = public.ExecShell(install_cmd)
            if err and 'ERR!' in err:
                raise ValueError(f"Dependency installation failed: {err.strip()}")

            # 5. 构建（仅 SSR/SSG 框架需要，Express/Fastify 跳过）
            if template not in ('express', 'fastify'):
                self.write_deploy_log(step_index=step_index, ps="Building project...", progress=80, status=0)
                build_cmd = f'cd {project_path} && {package_manager} run build'
                public.ExecShell(build_cmd)

            progress = 85
            self.write_deploy_log(step_index=step_index, ps="Preparing project configuration...", progress=progress, status=0)

            # 校验脚手架是否成功创建项目目录
            if not os.path.isdir(project_path):
                raise ValueError(f"Scaffolding failed: directory {project_path} does not exist.")

            if template in ('express', 'fastify'):
                # Express / Fastify -> PM2 managed
                self._pm2_deploy(template, project_name, project_path,
                                 version, package_manager, port, param,
                                 step_index, service_count, progress)
            else:
                # NestJS/Next.js/Astro via npm scripts
                package_file = os.path.join(project_path, 'package.json')
                scripts = {}
                if os.path.exists(package_file):
                    scripts = json.loads(public.readFile(package_file)).get('scripts', {})
                if 'dev' in scripts:
                    project_script = 'dev'
                elif 'start' in scripts:
                    project_script = 'start'
                else:
                    project_script = next(iter(scripts), 'start')
                # Astro needs XDG_CONFIG_HOME to avoid www user ~/.config permission errors
                if template == 'astro':
                    xdg_dir = os.path.join(project_path, '.config')
                    os.makedirs(xdg_dir, mode=0o755, exist_ok=True)
                    public.ExecShell('chown -R www:www {}'.format(xdg_dir))
                    project_script = 'env XDG_CONFIG_HOME={} npm run {}'.format(xdg_dir, project_script)

                # Build get object
                get = public.dict_obj()
                get.project_name = project_name
                get.project_cwd = project_path
                get.project_script = project_script
                get.project_ps = f'{template} project'
                get.bind_extranet = 1 if param.get('domain') else 0
                get.domains = [f"{param['domain']}:80"] if param.get('domain') else []
                get.is_power_on = 1
                get.run_user = 'www'
                get.max_memory_limit = 2048
                get.nodejs_version = version
                get.port = port
                get.project_file = ''

                # Create via nodejsModel
                from projectModelV2.nodejsModel import main as nodejsModel
                project_model = nodejsModel()
                res = project_model.create_project(get)
                if res['status'] != 0:
                    raise ValueError(f"Project creation failed: {res['message'].get('error_msg', res['message'])}")

                access_url = f"http://{param['domain']}" if param.get('domain') else f"http://YOUR_SERVER_IP"
                res = {
                    "version": version,
                    "package_manager": package_manager,
                    "template": template,
                    "project_name": project_name,
                    "project_path": project_path,
                    "project_script": project_script,
                    "port": port,
                    "access_url": access_url,
                }
                self.write_deploy_log(step_index=step_index, ps="Node.js project deployed successfully!", progress=100, status=1, result=res)
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self.write_deploy_log(step_index=step_index, ps="An error has occurred.", progress=progress, status=-1, error_msg=str(ex))
        finally:
            public.progress_release_lock(self.lock_file)

    def _pm2_deploy(self, template: str, project_name: str, project_path: str,
                    version: str, package_manager: str, port: str, param: dict,
                    step_index: int, service_count: int, progress: int):
        """Express / Fastify via PM2 deployed"""
        from mod.project.nodejs.pm2Mod import main as pm2Mod

        class _MockWS:
            """Mock WebSocket: discards PM2 progress updates; raises on error"""
            def __init__(self):
                self._error = None

            def send(self, data: str):
                try:
                    msg = json.loads(data)
                    if not msg.get('status', True):
                        self._error = RuntimeError(
                            msg.get('msg', 'PM2 creation failed'))
                except Exception:
                    pass

            def close(self):
                if self._error:
                    raise self._error

        get = public.dict_obj()
        get._ws = _MockWS()
        get.def_name = 'guide_page_nodejs'
        get.project_type = 'pm2'
        get.project_name = project_name
        get.project_cwd = project_path
        get.project_file = os.path.join(project_path, 'app.js')
        get.nodejs_version = version
        get.run_user = 'www'
        get.is_power_on = True
        get.max_memory_limit = 2048
        get.cluster = 1
        get.watch = False
        get.pkg_manager = package_manager
        get.not_install_pkg = True
        get.env = 'PORT={}'.format(port)
        get.project_args = ''
        get.port = port
        get.project_ps = '{} project'.format(template)
        get.bind_extranet = 1 if param.get('domain') else 0
        get.domains = [f"{param['domain']}:80"] if param.get('domain') else []
        get.release_firewall = False

        pm2_obj = pm2Mod()
        pm2_obj.create_project(get)

        access_url = f"http://{param['domain']}" if param.get('domain') else f"http://YOUR_SERVER_IP"
        self.write_deploy_log(
            step_index=step_index,
            ps="Node.js project deployed successfully!",
            progress=100, status=1,
            result={
                "version": version,
                "package_manager": package_manager,
                "template": template,
                "project_name": project_name,
                "project_path": project_path,
                "port": port,
                "access_url": access_url,
            })

    def _write_entry_file(self, project_path: str, framework: str, port: str):
        """为 Express/Fastify 生成入口文件"""
        if framework == 'express':
            content = f"""const express = require('express')
const app = express()
const PORT = process.env.PORT || {port}

app.get('/', (req, res) => {{
  res.json({{ hello: 'express' }})
}})

app.listen(PORT, '0.0.0.0', () => {{
  console.log('server running at http://0.0.0.0:' + PORT)
}})
"""
        elif framework == 'fastify':
            content = f"""const fastify = require('fastify')()
const PORT = process.env.PORT || {port}

fastify.get('/', async (request, reply) => {{
  return {{ hello: 'fastify' }}
}})

fastify.listen({{ port: PORT, host: '0.0.0.0' }}, (err) => {{
  if (err) throw err
  console.log('server running at http://0.0.0.0:' + PORT)
}})
"""
        else:
            return
        public.writeFile(os.path.join(project_path, 'app.js'), content)

    def _patch_nestjs_main(self, project_path: str, port: str):
        """Patch NestJS main.ts: app.listen(3000) → app.listen(process.env.PORT || port)"""
        main_ts = os.path.join(project_path, 'src', 'main.ts')
        if not os.path.exists(main_ts):
            return
        content = public.readFile(main_ts)
        if not content:
            return
        if 'process.env.PORT' not in content:
            content = content.replace('app.listen(3000)', 'app.listen(process.env.PORT || {})'.format(port))
            public.writeFile(main_ts, content)

    def _scaffold_astro(self, project_path: str, port: str):
        """手动创建 Astro 项目结构（绕过 create-astro 的 GitHub 联网校验）"""
        os.makedirs(project_path, mode=0o755, exist_ok=True)

        # package.json
        public.writeFile(os.path.join(project_path, 'package.json'), json.dumps({
            "name": os.path.basename(project_path),
            "type": "module",
            "version": "0.0.1",
            "scripts": {
                "dev": "astro dev",
                "build": "astro build",
                "preview": "astro preview"
            },
            "dependencies": {
                "astro": "^5.0.0"
            }
        }, indent=2))

        # astro.config.mjs
        public.writeFile(os.path.join(project_path, 'astro.config.mjs'),
            'import { defineConfig } from \'astro/config\';\n'
            'export default defineConfig({\n'
            '  server: { host: "0.0.0.0", port: ' + port + ' }\n'
            '});\n'
        )

        # tsconfig.json
        public.writeFile(os.path.join(project_path, 'tsconfig.json'), json.dumps({
            "extends": "astro/tsconfigs/strict"
        }, indent=2))

        # src/pages/index.astro
        pages_dir = os.path.join(project_path, 'src', 'pages')
        os.makedirs(pages_dir, mode=0o755, exist_ok=True)
        public.writeFile(os.path.join(pages_dir, 'index.astro'),
            '---\n'
            '---\n'
            '<html lang="en">\n'
            '  <head><meta charset="utf-8" /><meta name="viewport" content="width=device-width" /><title>Astro</title></head>\n'
            '  <body><h1>Hello, Astro!</h1></body>\n'
            '</html>\n'
        )

    def _get_scaffold_tasks(self, template: str, package_manager: str, project_name: str, project_path: str) -> tuple:
        """
        根据框架类型返回脚手架命令列表
        @return: (description, shell_command)
        """
        if template == 'express':
            return (
                "Initializing Express project...",
                f"cd {project_path} && npm init -y && npm pkg set scripts.start=\"node app.js\" && npm install express"
            )
        elif template == 'fastify':
            return (
                "Initializing Fastify project...",
                f"cd {project_path} && npm init -y && npm pkg set scripts.start=\"node app.js\" && npm install fastify"
            )
        elif template == 'nestjs':
            return (
                "Scaffolding NestJS project...",
                f"cd /www/wwwroot && npx -y @nestjs/cli new {project_name} --package-manager {package_manager} --skip-git"
            )
        elif template == 'nextjs':
            return (
                "Scaffolding Next.js project...",
                f"cd /www/wwwroot && npx -y create-next-app@latest {project_name} --yes"
            )
        elif template == 'astro':
            return (
                "Scaffolding Astro project...",
                f"cd /www/wwwroot && npx -y create-astro@latest {project_name} -- --template basics --install --no-git --skip-houston"
            )
        else:
            raise ValueError(f"Unsupported template: {template}")

    # proxy项目部署
    def install_proxy_project(self, param, started=None):
        service_count = self._init_log_structure('proxy', param)
        thread_id = threading.get_ident()
        public.writeFile(self.lock_file, str(thread_id))
        if started:
            started.set()

        step_index = 0
        progress = 0
        try:
            # 安装依赖服务
            ok = self.install_plugin('proxy', param, step_index)
            if not ok:
                return

            step_index = service_count
            progress = 55
            self.write_deploy_log(step_index=step_index, ps="Start creating the reverse proxy project...", progress=progress, status=0)

            from mod.project.proxy.comMod import main
            obj = main()
            dict_obj = {
                'domains' : param['domain'],
                'proxy_pass' : param['proxy_pass'],
                'proxy_type': 'true',
                'proxy_host': param['proxy_host'],
                'keepuri' : 1,
                'remark' : param['domain'],
            }
            result = obj.create(public.to_dict_obj(dict_obj))
            if result.get('status') != 0:
                raise ValueError(f"Failed to create the website: {result['message'].get('result')}")
            s_id = public.M('sites').where('name=?', (param['domain'],)).field('id,name').find()
            if not s_id:
                raise ValueError(f"Failed to create the website: The website is gone.")

            progress = 85
            self.write_deploy_log(step_index=step_index, ps="Start creating the reverse proxy project...",
                                  progress=progress, status=0)

            # 统一阻塞2秒
            time.sleep(2)

            # SSL申请失败，不影响项目创建
            if param['ssl_auto'] == '1':
                try:
                    from ssl_domainModelV2.service import smart_ssl
                    smart_ssl(int(s_id['id']))
                except:
                    pass

            # 设置缓存
            proxy_cache = False
            if param['proxy_cache'] == '1':
                dict_obj = {
                    'site_name': s_id['name'],
                    'cache_status': 1,
                    'expires': '1d',
                }
                res = obj.set_global_cache(public.to_dict_obj(dict_obj))
                if res['status'] == 0:
                    proxy_cache = True

            result = {
                'domains' : param['domain'],
                'proxy_pass' : param['proxy_pass'],
                'proxy_cache' : proxy_cache,
                'proxy_host': param['proxy_host']
            }
            self.write_deploy_log(step_index=step_index, ps="Start creating the reverse proxy project...",
                                  progress=progress, status=1,result=result)
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self.write_deploy_log(step_index=step_index, ps="An error has occurred.", progress=progress, status=-1,error_msg=str(ex))
        finally:
            public.progress_release_lock(self.lock_file)

    # 获取进度日志
    def get_general_progress(self, get = None):
        from panel_site_v2 import panelSite
        return panelSite().get_general_progress(public.to_dict_obj({'type':'guide_page'}))

    # 写入日志
    def write_deploy_log(self, step_index: int, ps: str, progress: int = 0, status: int = 0, error_msg: str = "", result = None):
        """
        按步骤更新部署日志（与 _init_log_structure 结构对齐）
        @param step_index: 步骤索引（0-based）
        @param ps: 当前步骤的描述信息
        @param progress: 整体进度百分比字符串（例如 '10', '50', '100'）
        @param status: 步骤状态码（0进行中，1完成，-1错误）
        @param error_msg: 错误信息（仅在 status=-1 时传入）
        """
        try:
            # 读取现有日志，不存在则初始化
            try:
                log_data = json.loads(public.readFile(self.status_file))
            except:
                log_data = {'status': 0, 'progress': 0, 'steps': []}

            # 校验步骤索引有效性
            if 0 <= step_index < len(log_data.get('steps', [])):
                log_data['steps'][step_index]['status'] = status
                log_data['steps'][step_index]['ps'] = str(ps)
                log_data['steps'][step_index]['error'] = str(error_msg)

                # 当前步骤进行中时，将下一个未开始的步骤标记为进行中（避免覆盖已有内容的步骤）
                if status == 1 and step_index + 1 < len(log_data['steps']):
                    if log_data['steps'][step_index + 1].get('status') == 2:
                        log_data['steps'][step_index + 1]['status'] = 0

            # 更新整体进度
            log_data['progress'] = progress

            # 如果某个步骤失败，标记整体状态为失败
            if status == -1:
                log_data['status'] = -1

            if result:
                log_data['result'] = result

            # 所有步骤完成时，标记整体状态为成功
            if all(s.get('status') == 1 for s in log_data.get('steps', [])) and result:
                log_data['status'] = 1
                log_data['progress'] = 100

            public.writeFile(self.status_file, json.dumps(log_data, ensure_ascii=False))
            if result or status == -1:
                time.sleep(3)
        except:
            pass

    # 初始化日志结构
    def _init_log_structure(self, install_type, param=None):
        structure_list = {
            'status': 0,
            'progress': 0,
            'result': {},
            'type': install_type
        }

        # 1. 按实际依赖生成服务安装步骤
        install_list = self._init_plugin(install_type, param or {})
        steps = []
        for soft in install_list:
            title = 'Install {}-{}'.format(soft['display_name'], soft['version'])
            if soft['name'] == 'nginx':
                title = 'Install {}'.format(soft['display_name'])

            steps.append({
                'status': 2,
                'error': '',
                'ps': '',
                'title': title
            })
        service_count = len(steps)

        # 2. 追加业务步骤
        if install_type == 'wp':
            # steps.append({'status': 2, 'error': '', 'ps': '', 'title': "Parameter environment verification"})
            steps.append({'status': 2, 'error': '', 'ps': '', 'title': "Creating the website and database"})
            steps.append({'status': 2, 'error': '', 'ps': '', 'title': "Initialize WordPress"})
        elif install_type == 'php':
            db_title = "Creating the website and database" if param and param.get('database') in ['mysql', 'mariadb'] else "Creating the website"
            steps.append({'status': 2, 'error': '', 'ps': '', 'title': db_title})
        elif install_type == 'proxy':
            steps.append({'status': 2, 'error': '', 'ps': '', 'title': "Create a reverse proxy project"})
        elif install_type == 'nodejs':
            steps.append({'status': 2, 'error': '', 'ps': '', 'title': "Installing Node.js and modules"})
            steps.append({'status': 2, 'error': '', 'ps': '', 'title': "Create Nodejs project"})

        structure_list['steps'] = steps
        public.writeFile(self.status_file, json.dumps(structure_list))
        return service_count

    # 简易版插件安装状态判断
    def get_plugin_status(self, plugin_name: str, version: str = '') -> bool:
        try:
            plugin_name = str(plugin_name).strip().lower()
            version = str(version).strip().lower()
            if not plugin_name:
                return False

            if plugin_name == 'mariadb':
                plugin_name = 'mysql'

            soft_list = json.loads(public.readFile('data/softList.conf'))
            root_path = public.GetConfigValue('root_path')
            for soft in soft_list:
                soft_name = str(soft.get('name', '')).strip().lower()

                if soft_name != plugin_name:
                    continue

                if soft_name == 'php':
                    check_file = root_path + '/' + soft.get('check', '').replace('VERSION', version.replace('.', ''))
                else:
                    check_file = root_path + '/' + soft.get('check', '')

                if os.path.exists(check_file):
                    return True

            return False
        except Exception as ex:
            print(ex)
            return False

    # 服务依赖安装
    def install_plugin(self, install_type, param, step_index=0) -> bool:
        install_list = self._init_plugin(install_type, param)
        progress = 5
        progress_step = math.ceil(50 / len(install_list))
        cur_step = step_index
        try:
            for idx, soft in enumerate(install_list):
                cur_step = step_index + idx
                s_name = soft['name']
                version = soft['version']
                display_name = soft['display_name']
                log_name = display_name if s_name == 'nginx' else f"{display_name}-{version}"


                self.write_deploy_log(step_index=cur_step, ps=f"Installation of {log_name} is in progress.", progress=progress, status=0)
                if self.get_plugin_status(s_name, version):
                    self.write_deploy_log(step_index=cur_step, ps=f"{log_name} installation successful!",
                                          progress=progress, status=1)
                    progress += progress_step
                    continue

                if public.get_webserver() in ['apache', 'openlitespeed'] and s_name == 'nginx':
                    progress += progress_step
                    self.write_deploy_log(step_index=cur_step, ps=f"{log_name} installation successful!",
                                          progress=progress, status=1)
                    continue

                # 同步安装
                if soft.get('install_tmp_path', ''):
                    tmp_path = soft['install_tmp_path']
                    self.write_deploy_log(step_index=cur_step, ps=f"Downloading {log_name} package...",
                                          progress=progress, status=0)

                    zip_file = self._download_plugin_zip(s_name, version, tmp_path)
                    if not zip_file:
                        raise Exception(f"Failed to download {log_name} installation package.")

                    public.extract_archive_to_target(zip_file, tmp_path)
                    if os.path.exists(os.path.join(tmp_path, s_name+'.zip')):
                        public.ExecShell(f"rm -rf {os.path.join(tmp_path, s_name+'.zip')}")

                    from panel_plugin_v2 import panelPlugin
                    obj = panelPlugin()
                    ok = obj.input_zip(public.to_dict_obj({'plugin_name': s_name, 'tmp_path': tmp_path}))
                    if ok['status'] != 0:
                        raise Exception(f"The installation of {log_name} failed.")

                else:
                    ok = self.add_soft_install_task(s_name,version)
                    if not ok:
                        raise Exception(f"The installation task for {log_name} failed. Please try again!")

                    time.sleep(3)

                    time_out = 0
                    install = False
                    while time_out < 900:
                        res = public.M('tasks').where("status!=? and name LIKE ?", ('1', '%' + s_name + '%')).count()
                        if not res and self.get_plugin_status(s_name, version):
                            install = True
                            break
                        elif not res:
                            break

                        time.sleep(2)
                        time_out += 2

                    if not install:
                        if time_out >= 900:
                            raise Exception(f"{log_name} installation has timed out. Please try again later or consider skipping the boot process.")
                        raise Exception(f"The installation of {log_name} failed.")

                progress += progress_step
                self.write_deploy_log(step_index=cur_step, ps=f"{log_name} installation successful!",
                                      progress=progress, status=1)

            return True
        except Exception as e:
            self._clean_tasks()
            self.write_deploy_log(step_index=cur_step, ps=f"Error occurred while installing the dependent service.", progress=progress,
                                  status=-1, error_msg=str(e))
            return False

    # 仅清理tasks表和残留安装进程，不重启面板（用于异步线程内）
    def _clean_tasks(self) -> bool:
        try:
            tasks = public.M('tasks').where('status!=?', ('1',)).field('id,status,name').select()
            if not isinstance(tasks, list):
                return True

            has_running = any(str(task.get('status')) == '-1' for task in tasks)
            for task in tasks:
                public.M('tasks').delete(task['id'])

            if has_running:
                public.ExecShell("kill `ps -ef |grep 'install_soft.sh'|grep -v grep|grep -v panelExec|awk '{print $2}'`")
                public.ExecShell('''
pids=`ps aux | grep 'sh'|grep -v grep|grep install|awk '{print $2}'`
arr=($pids)

for p in ${arr[@]}
do
    kill -9 $p
done
                ''')

            public.writeFile('/tmp/panelTask.pl', 'True')
            return True
        except Exception as ex:
            return False

    # 简易版插件安装，直接写入task，不通过云端
    def add_soft_install_task(self, s_name: str, version: str) -> bool:
        try:
            s_name = str(s_name).strip().lower()
            version = str(version).strip()

            if not s_name or not version:
                raise ValueError('Missing software name or version')

            if s_name == 'mariadb':
                s_name = 'mysql'

            if s_name == 'php':
                version = version.replace('.', '')

            if public.get_webserver() == 'openlitespeed' and s_name == 'php':
                s_name = 'php-ols'

            install_type = '4' if os.path.exists('/usr/bin/apt-get') else '1'

            public.writeFile('/var/bt_setupPath.conf', '/www')

            if not public.M('tasks').where("status!=? and name LIKE ?", ('1', '%' + s_name + '%')).count():
                panel_install_path = public.GetConfigValue('setup_path') + '/panel/install'
                execstr = "cd {} && /bin/bash install_soft.sh {} install {} {}".format(
                    panel_install_path,
                    install_type,
                    s_name,
                    version
                )

                public.M('tasks').add(
                    'id,name,type,status,addtime,execstr',
                    (
                        None,
                        'Install[{}-{}]'.format(s_name, version),
                        'execshell',
                        '-1',
                        time.strftime('%Y-%m-%d %H:%M:%S'),
                        execstr
                    )
                )
                public.writeFile('/tmp/panelTask.pl', 'True')
            return True
        except:
            return False

    # 从官方API同步下载插件安装包
    def _download_plugin_zip(self, s_name: str, version: str, tmp_path: str) -> str:
        """
        参照 panel_plugin_v2.__download_plugin 流程，从同步插件API下载zip包
        @return: zip文件路径，失败返回空字符串
        """
        try:
            import requests
            download_url = public.SyncPluginOfficialApiBase() + '/api/panel/download_plugin'
            pdata = public.get_user_info()
            pdata['name'] = s_name
            pdata['version'] = version
            pdata['os'] = 'Linux'
            pdata['environment_info'] = json.dumps(public.fetch_env_info(), ensure_ascii=False)

            if not os.path.exists(tmp_path):
                os.makedirs(tmp_path, mode=0o755, exist_ok=True)
            zip_file = os.path.join(tmp_path, '{}.zip'.format(s_name))
            download_res = requests.post(
                download_url, pdata,
                headers=public.get_requests_headers(),
                timeout=(60, 1800),
                stream=True
            )
            download_res.raise_for_status()

            total_size = int(download_res.headers.get('File-size', 0))
            chunk_size = 1024 * 1024 if total_size > 1024 * 1024 * 5 else 8192
            with open(zip_file, 'wb') as f:
                for chunk in download_res.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)

            # MD5 校验
            content_md5 = download_res.headers.get('Content-md5', '')
            if content_md5 and public.FileMd5(zip_file) != content_md5:
                os.remove(zip_file)
                raise Exception(f"{s_name}-{version} package hash verification failed")

            return zip_file
        except Exception as ex:
            import traceback
            traceback.print_exc()
            return str(ex)

    # 安装nodejs版本并附加PM2、指定包管理器模块
    def _install_nodejs_with_modules(self, version: str, package_manager: str = 'npm') -> dict:
        """
        辅助函数：安装指定Node.js版本，随后安装PM2和指定包管理器并设为默认
        @param version: Node.js版本号，如 'v22.22.3'
        @param package_manager: 包管理器名称，支持 npm/yarn/pnpm
        @return: {'status': bool, 'error_msg': str, 'data': mixed}
        """
        try:
            # 动态加载nodejs插件
            plugin_path = '/www/server/panel/plugin/nodejs'
            if plugin_path not in sys.path:
                sys.path.insert(0, plugin_path)
            from plugin.nodejs.nodejs_main import nodejs_main
            node_obj = nodejs_main()

            get = public.dict_obj()
            get.version = version

            # 1. 安装Node.js
            install_res = node_obj.install_nodejs(get)
            if not install_res.get('status') and 'already installed' not in install_res.get('error_msg'):
                return install_res

            # 2. 安装PM2模块
            pm2_get = public.dict_obj()
            pm2_get.version = version
            pm2_get.module = 'pm2'
            pm2_res = node_obj.install_module(pm2_get)
            if not pm2_res.get('status') and 'has been installed!' not in pm2_res.get('error_msg'):
                return pm2_res

            # 3. 安装指定包管理器（npm内置，无需额外安装）
            if package_manager in ('yarn', 'pnpm'):
                mgr_get = public.dict_obj()
                mgr_get.version = version
                mgr_get.module = package_manager
                mgr_res = node_obj.install_module(mgr_get)
                if not mgr_res.get('status') and 'has been installed!' not in mgr_res.get('error_msg'):
                    return mgr_res

            # 4. 设置为默认版本
            default_get = public.dict_obj()
            default_get.version = version
            default_res = node_obj.set_default_env(default_get)
            return default_res
        except Exception as ex:
            return {'status': False, 'error_msg': str(ex), 'data': {}}

    # 跳过引导
    def close_guide(self, get=None):
        path = os.path.join(public.get_panel_path(), 'data', 'guide_marking.pl')
        public.writeFile(path, 'close')
        return public.return_message(0, 0, public.lang("Operation successful."))

    # 保存配置
    def save_config(self,install_type, param):
        save = {
            'install_type':install_type,
            'param': param
        }
        public.writeFile(self.guide_config, json.dumps(save, ensure_ascii=False))
        return

    def get_save_config(self, get=None):
        param = {}
        if os.path.exists(self.guide_config):
            try:
                param = json.loads(public.readFile(self.guide_config))
            except:
                pass
        param['status'] = 1

        progress = self.get_general_progress()
        if progress['status'] == 0:
            param['status'] = progress['message']['status']

        return public.return_message(0, 0, param)