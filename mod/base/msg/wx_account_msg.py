# coding: utf-8
# +-------------------------------------------------------------------
# | aapanel
# +-------------------------------------------------------------------
# | Copyright (c) 2015-2020 aapanel(http://www.aapanel.com) All rights reserved.
# +-------------------------------------------------------------------
# | Author: baozi <baozi@bt.cn>
# | 消息通道微信公众号模块
# +-------------------------------------------------------------------

import os, sys
import time, base64

import re
import json
import requests
import traceback
import socket
import public

import requests.packages.urllib3.util.connection as urllib3_cn
from requests.packages import urllib3
from typing import Optional, Union, List, Dict, Any

from .util import write_push_log, get_test_msg, read_file, public_http_post
from mod.base.push_mod import WxAccountMsg, SenderConfig
from mod.base import json_response

# 关闭警告
urllib3.disable_warnings()


class WeChatAccountMsg:
    USER_PATH = '/www/server/panel/data/userInfo.json'
    need_refresh_file = '/www/server/panel/data/mod_push_data/refresh_wechat_account.tip'
    refresh_time = '/www/server/panel/data/mod_push_data/refresh_wechat_account_time.pl'

    def __init__(self, *config_data):
        if len(config_data) == 0:
            self.config = None
        elif len(config_data) == 1:
            self.config = config_data[0]["data"]
        else:
            self.config = config_data[0]["data"]
            self.config["users"] = [i["data"]['id'] for i in config_data]
            self.config["users_nickname"] = [i["data"]['nickname'] for i in config_data]
        try:
            self.user_info = json.loads(read_file(self.USER_PATH))
        except:
            self.user_info = None

    @classmethod
    def get_user_info(cls) -> Optional[dict]:
        try:
            return json.loads(read_file(cls.USER_PATH))
        except:
            return None

    @classmethod
    def last_refresh(cls):
        tmp = read_file(cls.refresh_time)
        if not tmp:
            last_refresh_time = 0
        else:
            try:
                last_refresh_time = int(tmp)
            except:
                last_refresh_time = 0
        return last_refresh_time

    @staticmethod
    def get_local_ip() -> str:
        """获取内网IP"""
        import socket
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            return ip
        except:
            pass
        finally:
            if s is not None:
                s.close()
        return '127.0.0.1'

    def send_msg(self, msg: WxAccountMsg) -> Optional[str]:
        if self.user_info is None:
            return public.lang('No user information was obtained')

        msg.set_ip_address(self.user_info["address"], self.get_local_ip())
        template_id, msg_data = msg.to_send_data()
        url = f"{public.OfficialWaf2Base()}/api/v2/user/wx_web/send_template_msg_v3"
        wx_account_ids = self.config["users"] if "users" in self.config else [self.config["id"], ]
        data = {
            "uid": self.user_info["uid"],
            "access_key": 'B' * 32,
            "data": base64.b64encode(json.dumps(msg_data).encode('utf-8')).decode('utf-8'),
            "wx_account_ids": base64.b64encode(json.dumps(wx_account_ids).encode('utf-8')).decode('utf-8'),
        }
        if template_id != "":
            data["template_id"] = template_id

        status = False
        error = None
        user_name = self.config["users_nickname"] if "users_nickname" in self.config else [self.config["nickname"], ]
        try:

            resp = public_http_post(url, data)
            x = json.loads(resp)
            if x["success"]:
                status = True
            else:
                status = False
                error = x["res"]
        except:
            error = traceback.format_exc()

        write_push_log("wx_account", status, msg.thing_type, user_name)

        return error

    @classmethod
    def refresh_config(cls, force: bool = False):
        if os.path.exists(cls.need_refresh_file):
            force = True
            os.remove(cls.need_refresh_file)
        if force or cls.last_refresh() + 60 * 10 < time.time():
            cls._get_by_web()

    @classmethod
    def _get_by_web(cls) -> Optional[List]:
        user_info = cls.get_user_info()
        if user_info is None:
            return None
        url = f"{public.OfficialWaf2Base()}/api/v2/user/wx_web/bound_wx_accounts"
        data = {
            "uid": user_info["uid"],
            "access_key": 'B' * 32,
            "serverid": user_info["server_id"]
        }
        try:
            data = json.loads(public_http_post(url, data))
            if not data["success"]:
                return None
        except:
            return None

        cls._save_user_info(data["res"])
        return data["res"]

    @staticmethod
    def _save_user_info(user_config_list: List[Dict[str, Any]]):
        print(user_config_list)
        user_config_dict = {i["hex"]: i for i in user_config_list}

        remove_list = []
        sc = SenderConfig()
        for i in sc.config:
            if i['sender_type'] != "wx_account":
                continue
            if i['data'].get("hex", None) in user_config_dict:
                i['data'].update(user_config_dict[i['data']["hex"]])
                user_config_dict.pop(i['data']["hex"])
            else:
                remove_list.append(i)

        for r in remove_list:
            sc.config.remove(r)

        if user_config_dict:  # 还有多的
            for v in user_config_dict.values():
                v["title"] = v["nickname"]
                sc.config.append({
                    "id": sc.nwe_id(),
                    "used": True,
                    "sender_type": "wx_account",
                    "data": v
                })
        sc.save_config()

    @classmethod
    def unbind(cls, wx_account_uid: str):
        user_info = cls.get_user_info()
        if user_info is None:
            return json_response(status=True, msg=public.lang('The user binding information was not obtained'))
        url = f"{public.OfficialWaf2Base()}/api/v2/user/wx_web/unbind_wx_accounts"
        data = {
            "uid": user_info["uid"],
            "access_key": 'B' * 32,
            "serverid": user_info["server_id"],
            "ids":  str(wx_account_uid)
        }
        try:
            datas = json.loads(public_http_post(url, data))
            if datas["success"]:
                return json_response(status=True, data=datas, msg=public.lang('The unbinding is successful'))
            else:
                return json_response(status=False, data=datas, msg=datas["res"])
        except:
            return json_response(status=True, msg=public.lang('Failed to link to the cloud'))

    @classmethod
    def get_auth_url(cls):
        user_info = cls.get_user_info()
        if user_info is None:
            return json_response(status=True, msg=public.lang('The user binding information was not obtained'))
        url = f"{public.OfficialWaf2Base()}/api/v2/user/wx_web/get_auth_url"
        data = {
            "uid": user_info["uid"],
            "access_key": 'B' * 32,
            "serverid": user_info["server_id"],
        }
        try:
            datas = json.loads(public_http_post(url, data))
            if datas["success"]:
                return json_response(status=True, data=datas)
            else:
                return json_response(status=False, data=datas, msg=datas["res"])
        except:
            return json_response(status=True, msg=public.lang('Failed to link to the cloud'))

    def test_send_msg(self) -> Optional[str]:
        test_msg = {
            "msg_list": ['>configuration state: <font color=#20a53a> Success </font>\n\n']
        }
        test_task = get_test_msg("Message channel configuration reminders")
        res = self.send_msg(
            test_task.to_wx_account_msg(test_msg, test_task.the_push_public_data()),
        )
        if res is None:
            return None
        return res

