from flask import Flask, session, redirect, request, make_response
import json
import datetime
import os
import hashlib

from .DataMgr import DataMgr
from .PushSvr import PushServer
from .WatchDog import WatchDog, EventSink

def pack_rsp(obj):
    rsp = make_response(json.dumps(obj))
    rsp.headers["content-type"]= "text/json;charset=utf-8"
    return rsp

def parse_data():
    try:
        data = request.get_data()
        json_data = json.loads(data.decode("utf-8"))
        return True,json_data
    except:
        return False, {
            "result": -998,
            "message": "请求数据解析失败"
        }

def get_param(json_data, key:str, type=str, defVal = ""):
    if key not in json_data:
        return defVal
    else:
        return type(json_data[key])

#获取文件最后N行的函数
def get_tail(filename, N:int = 100) :
    filesize = os.path.getsize(filename)
    blocksize = 10240
    dat_file = open(filename, 'r')
    last_line = ""
    if filesize > blocksize :
        maxseekpoint = (filesize // blocksize)
        dat_file.seek((maxseekpoint-1)*blocksize)
    elif filesize :
        dat_file.seek(0, 0)
    lines =  dat_file.readlines()
    if lines :
        last_line = lines[-N:]
    dat_file.close()
    return ''.join(last_line), len(last_line)

def check_auth():
    usrInfo = session.get("userinfo")
    # session里没有用户信息
    if usrInfo is None:
        
        return False, {
            "result":-999,
            "message":"请先登录"
        }

    # session里有用户信息，则要读取
    exptime = session.get("expiretime")
    now = datetime.datetime.now()
    if now > exptime:
        return False, {
            "result":-999,
            "message":"登录已超时，请重新登录"
        }

    return True, usrInfo

def get_path_tree(root:str, name:str):
    if not os.path.exists(root):
        return {
            "label":name,
            "path":root,
            "exist":False,
            "isfile":False,
            "children":[]
        }

    if os.path.isfile(root):
        return {
            "label":name,
            "path":root,
            "exist":False,
            "isfile":True
        }

    ret = {
        "label":name,
        "path":root,
        "exist":True,
        "isfile":False,
        "children":[]
    }
    files = os.listdir(root, )
    for filename in files:
        filepath = os.path.join(root, filename)
        if not os.path.isfile(filepath):
            ret["children"].append(get_path_tree(filepath, filename))
    return ret



class WtMonSvr(EventSink):

    def __init__(self, static_folder:str="", static_url_path="/", deploy_dir="C:/"):
        if len(static_folder) == 0:
            static_folder = 'static'

        # 数据管理器，主要用于缓存各组合的数据
        self.__data_mgr__ = DataMgr('monitor.json')

        # 看门狗模块，主要用于调度各个组合启动关闭
        self._dog = WatchDog(sink=self, cfgfile="schedule.json")

        app = Flask(__name__, instance_relative_config=True, static_folder=static_folder, static_url_path=static_url_path)
        app.secret_key = "!@#$%^&*()"
        # app.debug = True
        self.app = app
        self.worker = None
        self.deploy_dir = deploy_dir
        self.deploy_tree = None

        self.push_svr = PushServer(app, self.__data_mgr__)

        @app.route("/console", methods=["GET"])
        def stc_console_index():
            return redirect("./console/index.html")

        @app.route("/mobile", methods=["GET"])
        def stc_mobile_index():
            return redirect("./mobile/index.html")


        '''下面是API接口的编写'''
        @app.route("/mgr/login", methods=["POST"])
        def cmd_login():
            
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            if True:
                user = get_param(json_data, "loginid")
                pwd = get_param(json_data, "passwd")

                if len(user) == 0 or len(pwd) == 0:
                    ret = {
                        "result":-1,
                        "message":"用户名和密码不能为空"
                    }
                else:
                    encpwd = hashlib.md5((user+pwd).encode("utf-8")).hexdigest()
                    now = datetime.datetime.now()
                    if user == "superman":
                        superpwd = '25ed305a56504e95fd1ca9900a1da174'
                        if encpwd != superpwd:
                            ret = {
                                "result":-1,
                                "message":"登录密码错误"
                            }
                        else:
                            usrInf = {
                                "loginid":user,
                                "name":"超管",
                                "loginip":request.remote_addr,
                                "logintime":now.strftime("%Y/%m/%d %H:%M:%S"),
                                "role":"admin"
                            }

                            exptime = now + datetime.timedelta(minutes=30)  #30分钟令牌超时
                            session["userinfo"] = usrInf
                            session["expiretime"] = exptime

                            ret = {
                                "result":0,
                                "message":"Ok",
                                "userinfo":usrInf
                            }
                    else:
                        usrInf = {
                            "loginid":user,
                            "name":"张三",
                            "loginip":request.remote_addr,
                            "logintime":now.strftime("%Y/%m/%d %H:%M:%S"),
                            "role":"user"
                        }

                        exptime = now + datetime.timedelta(minutes=30)  #30分钟令牌超时
                        session["userinfo"] = usrInf
                        session["expiretime"] = exptime

                        ret = {
                            "result":0,
                            "message":"Ok",
                            "userinfo":usrInf
                        }
            else:
                ret = {
                    "result":-1,
                    "message":"请求处理出现异常",
                }
                if session.get("userinfo") is not None:
                    session.pop("userinfo")

            return pack_rsp(ret)

        # 添加组合
        @app.route("/mgr/addgrp", methods=["POST"])
        def cmd_add_group():
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            bSucc, usrInfo = check_auth()
            if not bSucc:
                return pack_rsp(usrInfo)

            id = get_param(json_data, "groupid")
            name = get_param(json_data, "name")
            path = get_param(json_data, "path")
            info = get_param(json_data, "info")
            gtype = get_param(json_data, "gtype")

            if len(id) == 0 or len(name) == 0 or len(gtype) == 0:
                ret = {
                    "result":-1,
                    "message":"组合ID、名称、类型都不能为空"
                }
            elif not os.path.exists(path) or not os.path.isdir(path):
                ret = {
                    "result":-2,
                    "message":"组合运行目录不正确"
                }
            elif self.__data_mgr__.has_group(id):
                ret = {
                    "result":-3,
                    "message":"组合ID不能重复"
                }
            else:
                try:
                    grpInfo = {
                        "id":id,
                        "name":name,
                        "path":path,
                        "info":info,
                        "gtype":gtype
                    }   

                    self.__data_mgr__.add_group(grpInfo)
                    ret = {
                        "result":0,
                        "message":"Ok"
                    }
                except:
                    ret = {
                        "result":-1,
                        "message":"请求解析失败"
                    }

            return pack_rsp(ret)

        # 组合停止
        @app.route("/mgr/stopgrp", methods=["POST"])
        def cmd_stop_group():
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            bSucc, usrInfo = check_auth()
            if not bSucc:
                return pack_rsp(usrInfo)
            
            grpid = get_param(json_data, "groupid")
            if not self.__data_mgr__.has_group(grpid):
                ret = {
                    "result":-1,
                    "message":"组合不存在"
                }
            else:
                if self._dog.isRunning(grpid):
                    self._dog.stop(grpid)
                ret = {
                    "result":0,
                    "message":"Ok"
                }

            return pack_rsp(ret)
        
        # 组合启动
        @app.route("/mgr/startgrp", methods=["POST"])
        def cmd_start_group():
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            bSucc, usrInfo = check_auth()
            if not bSucc:
                return pack_rsp(usrInfo)
            
            grpid = get_param(json_data, "groupid")
            if not self.__data_mgr__.has_group(grpid):
                ret = {
                    "result":-1,
                    "message":"组合不存在"
                }
            else:
                if not self._dog.isRunning(grpid):
                    self._dog.start(grpid)
                ret = {
                    "result":0,
                    "message":"Ok"
                }

            return pack_rsp(ret)

        # 配置监控
        @app.route("/mgr/qrymon", methods=["POST"])
        def qry_mon_cfg():
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            bSucc, usrInfo = check_auth()
            if not bSucc:
                return pack_rsp(usrInfo)

            grpid = get_param(json_data, "groupid")
            if not self.__data_mgr__.has_group(grpid):
                ret = {
                    "result":-1,
                    "message":"组合不存在"
                }
            else:
                monCfg = self._dog.getAppConf(grpid)
                if monCfg is None:
                    ret = {
                        "result":0,
                        "message":"ok"
                    }
                else:
                    ret = {
                        "result":0,
                        "message":"ok",
                        "config":monCfg
                    }

            return pack_rsp(ret)

        # 配置监控
        @app.route("/mgr/cfgmon", methods=["POST"])
        def cmd_config_monitor():
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            bSucc, usrInfo = check_auth()
            if not bSucc:
                return pack_rsp(usrInfo)

            #这里本来是要做检查的，算了，先省事吧
            
            self._dog.applyAppConf(json_data)
            ret = {
                "result":0,
                "message":"ok"
            }

            return pack_rsp(ret)

        # 查询目录结构
        @app.route("/mgr/qrydir", methods=["POST"])
        def qry_directories():
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            bSucc, usrInfo = check_auth()
            if not bSucc:
                return pack_rsp(usrInfo)

            if True:
                if self.deploy_tree is None:
                    self.deploy_tree = get_path_tree(self.deploy_dir, "root")

                ret = {
                    "result":0,
                    "message":"Ok",
                    "tree":self.deploy_tree
                }
            else:
                ret = {
                    "result":-1,
                    "message":"请求解析失败"
                }

            return pack_rsp(ret)

        # 查询组合列表
        @app.route("/mgr/qrygrp", methods=["POST"])
        def qry_groups():
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            bSucc, usrInfo = check_auth()
            if not bSucc:
                return pack_rsp(usrInfo)

            try:
                groups = self.__data_mgr__.get_groups()
                for grpInfo in groups:
                    grpInfo["running"] = self._dog.isRunning(grpInfo["id"])
                ret = {
                    "result":0,
                    "message":"Ok",
                    "groups":groups
                }
            except:
                ret = {
                    "result":-1,
                    "message":"请求解析失败"
                }

            return pack_rsp(ret)
        
        # 查询策略列表
        @app.route("/mgr/qrystras", methods=["POST"])
        def qry_strategys():
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            bSucc, usrInfo = check_auth()
            if not bSucc:
                return pack_rsp(usrInfo)

            grpid = get_param(json_data, "groupid")
            if not self.__data_mgr__.has_group(grpid):
                ret = {
                    "result":-1,
                    "message":"组合不存在"
                }
            else:
                ret = {
                    "result":0,
                    "message":"Ok",
                    "strategies":self.__data_mgr__.get_strategies(grpid)
                }

            return pack_rsp(ret)

        # 查询通道列表
        @app.route("/mgr/qrychnls", methods=["POST"])
        def qry_channels():
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            bSucc, usrInfo = check_auth()
            if not bSucc:
                return pack_rsp(usrInfo)

            grpid = get_param(json_data, "groupid")
            if not self.__data_mgr__.has_group(grpid):
                ret = {
                    "result":-1,
                    "message":"组合不存在"
                }
            else:
                ret = {
                    "result":0,
                    "message":"Ok",
                    "channels":self.__data_mgr__.get_channels(grpid)
                }

            return pack_rsp(ret)

        # 查询组合日志
        @app.route("/mgr/qrylogs", methods=["POST"])
        def qry_logs():
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            bSucc, usrInfo = check_auth()
            if not bSucc:
                return pack_rsp(usrInfo)

            grpid = get_param(json_data, "id")
            logtype = get_param(json_data, "type")

            if not self.__data_mgr__.has_group(grpid):
                ret = {
                    "result":-1,
                    "message":"组合不存在"
                }
            else:
                grpInfo = self.__data_mgr__.get_group(grpid)
                if True:
                    logfolder = os.path.join(grpInfo["path"], "./Logs/")
                    file_list = os.listdir(logfolder)
                    targets = list()
                    for fname in file_list:
                        if fname[:6] == "Runner":
                            targets.append(fname)

                    targets.sort()
                    filename = os.path.join(logfolder, targets[-1])
                    content,lines = get_tail(filename, 100)
                    ret = {
                        "result":0,
                        "message":"Ok",
                        "content":content,
                        "lines":lines
                    }
                else:
                    ret = {
                        "result":-1,
                        "message":"请求解析失败"
                    }

            return pack_rsp(ret)

        # 查询策略成交
        @app.route("/mgr/qrytrds", methods=["POST"])
        def qry_trades():
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            bSucc, usrInfo = check_auth()
            if not bSucc:
                return pack_rsp(usrInfo)

            gid = get_param(json_data, "groupid")
            sid = get_param(json_data, "strategyid")

            if not self.__data_mgr__.has_group(gid):
                ret = {
                    "result":-1,
                    "message":"组合不存在"
                }
            else:
                ret = {
                    "result":0,
                    "message":"",
                    "trades": self.__data_mgr__.get_trades(gid, sid)
                }
                    

            return pack_rsp(ret)

        # 查询策略信号
        @app.route("/mgr/qrysigs", methods=["POST"])
        def qry_signals():
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            bSucc, usrInfo = check_auth()
            if not bSucc:
                return pack_rsp(usrInfo)

            gid = get_param(json_data, "groupid")
            sid = get_param(json_data, "strategyid")

            if not self.__data_mgr__.has_group(gid):
                ret = {
                    "result":-1,
                    "message":"组合不存在"
                }
            else:
                ret = {
                    "result":0,
                    "message":"",
                    "signals": self.__data_mgr__.get_signals(gid, sid)
                }
                    

            return pack_rsp(ret)

        # 查询策略回合
        @app.route("/mgr/qryrnds", methods=["POST"])
        def qry_rounds():
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            bSucc, usrInfo = check_auth()
            if not bSucc:
                return pack_rsp(usrInfo)

            gid = get_param(json_data, "groupid")
            sid = get_param(json_data, "strategyid")

            if not self.__data_mgr__.has_group(gid):
                ret = {
                    "result":-1,
                    "message":"组合不存在"
                }
            else:
                ret = {
                    "result":0,
                    "message":"",
                    "rounds": self.__data_mgr__.get_rounds(gid, sid)
                }

            return pack_rsp(ret)

        # 查询策略持仓
        @app.route("/mgr/qrypos", methods=["POST"])
        def qry_positions():
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            bSucc, usrInfo = check_auth()
            if not bSucc:
                return pack_rsp(usrInfo)

            gid = get_param(json_data, "groupid")
            sid = get_param(json_data, "strategyid")

            if not self.__data_mgr__.has_group(gid):
                ret = {
                    "result":-1,
                    "message":"组合不存在"
                }
            else:
                ret = {
                    "result":0,
                    "message":"",
                    "positions": self.__data_mgr__.get_positions(gid, sid)
                }

            return pack_rsp(ret)

        # 查询策略持仓
        @app.route("/mgr/qryfunds", methods=["POST"])
        def qry_funds():
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            bSucc, usrInfo = check_auth()
            if not bSucc:
                return pack_rsp(usrInfo)

            gid = get_param(json_data, "groupid")
            sid = get_param(json_data, "strategyid")

            if not self.__data_mgr__.has_group(gid):
                ret = {
                    "result":-1,
                    "message":"组合不存在"
                }
            else:
                ret = {
                    "result":0,
                    "message":"",
                    "funds": self.__data_mgr__.get_funds(gid, sid)
                }

            return pack_rsp(ret)

        # 查询通道订单
        @app.route("/mgr/qrychnlords", methods=["POST"])
        def qry_channel_orders():
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            bSucc, usrInfo = check_auth()
            if not bSucc:
                return pack_rsp(usrInfo)

            gid = get_param(json_data, "groupid")
            cid = get_param(json_data, "channelid")

            if not self.__data_mgr__.has_group(gid):
                ret = {
                    "result":-1,
                    "message":"组合不存在"
                }
            else:
                ret = {
                    "result":0,
                    "message":"",
                    "orders": self.__data_mgr__.get_channel_orders(gid, cid)
                }

            return pack_rsp(ret)

        # 查询通道成交
        @app.route("/mgr/qrychnltrds", methods=["POST"])
        def qry_channel_trades():
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            bSucc, usrInfo = check_auth()
            if not bSucc:
                return pack_rsp(usrInfo)

            gid = get_param(json_data, "groupid")
            cid = get_param(json_data, "channelid")

            if not self.__data_mgr__.has_group(gid):
                ret = {
                    "result":-1,
                    "message":"组合不存在"
                }
            else:
                ret = {
                    "result":0,
                    "message":"",
                    "trades": self.__data_mgr__.get_channel_trades(gid, cid)
                }

            return pack_rsp(ret)

        # 查询通道持仓
        @app.route("/mgr/qrychnlpos", methods=["POST"])
        def qry_channel_position():
            bSucc, json_data = parse_data()
            if not bSucc:
                return pack_rsp(json_data)

            bSucc, usrInfo = check_auth()
            if not bSucc:
                return pack_rsp(usrInfo)

            gid = get_param(json_data, "groupid")
            cid = get_param(json_data, "channelid")

            if not self.__data_mgr__.has_group(gid):
                ret = {
                    "result":-1,
                    "message":"组合不存在"
                }
            else:
                ret = {
                    "result":0,
                    "message":"",
                    "positions": self.__data_mgr__.get_channel_positions(gid, cid)
                }

            return pack_rsp(ret)
    
    def __run_impl__(self, port:int, host:str):
        self.push_svr.run(port = port, host = host)
    
    def run(self, port:int = 8080, host="0.0.0.0", bSync:bool = True):
        if bSync:
            self.__run_impl__(port, host)
        else:
            import threading
            self.worker = threading.Thread(target=self.__run_impl__, args=(port,host,))
            self.worker.setDaemon(True)
            self.worker.start()

    def init_logging(self):
        pass

    def on_start(self, grpid:str):
        self.push_svr.notifyGrpEvt(grpid, 'start')

    def on_stop(self, grpid:str):
        self.push_svr.notifyGrpEvt(grpid, 'stop')
    
    def on_output(self, grpid:str, message:str):
        self.push_svr.notifyGrpLog(grpid, message)