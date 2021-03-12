#coding=utf-8
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for,jsonify,current_app,Flask
)
from flaskr.auth import login_required
from werkzeug.exceptions import abort
from requests.packages import urllib3
from flask_pymongo import PyMongo
from urllib import parse
import threading
import requests
import base64
import json
import time
import os
import re
import IPy
import redis
import pymmh3
from .rules import ruleDatas #引入Web组件指纹库

#消除安全请求的提示信息,增加重试连接次数
urllib3.disable_warnings()
requests.adapters.DEFAULT_RETRIES = 3
s = requests.session()

#关闭连接，防止出现最大连接数限制错误
s.keep_alive = False

#openssl 拒绝短键，防止SSL错误
urllib3.util.ssl_.DEFAULT_CIPHERS += 'HIGH:!DH:!aNULL'

# 设置最大线程数
thread_max = threading.BoundedSemaphore(value=305)


pool = redis.ConnectionPool(host='127.0.0.1', port=6379,decode_responses=True, encoding='UTF-8')
re_dis = redis.Redis(connection_pool=pool)

targets=[]  #所有目标存储用list
ipc_list=[] #本次任务所有ip段
e_mail = "cnno.1@protonmail.com"
cookies=dict(rememberMe='axxxxxxxxxx123456')
k_key ="86b1a3ae6a597782a0394041c7d1908c"

bp = Blueprint('admin', __name__,url_prefix='/admin')


@bp.route('/')
@login_required
def index():
    return render_template('admin/admin.html')

@bp.route('/tasklist')
@login_required
def tasklist():
    mongo = PyMongo(current_app)
    all_tasklist = mongo.db.tasks.find()
    return render_template('admin/tasklist.html',lists=all_tasklist)

def CDN(host,ip,port):
    if host[0:5]=='https' and host[9].isdigit():
        url=host
    else:
        url='http://'+ip+":"+port
    try:
        if ':' not in ip: #去掉IPV6
            resp = requests.get(url,timeout=12,verify=False)
            if resp.status_code !=400:
                return 'nocdn'
            elif resp.status_code ==400:
                return 'iscdn'
            else:
                return 'orcdn'
        else:
            return 'nocdn'
    except Exception as ex:
        return 'timeout'

#添加任务（包括任务下发）
@bp.route('/create-task', methods=('GET', 'POST'))
def create_task():
    mongo = PyMongo(current_app)
    if request.method == 'POST':
        taskName = request.form['task_name']
        taskTargets = request.form['targets']
        error = None

        if not taskName:
            error = '任务名称不能为空'

        if error is not None:
            flash(error)
        else:
            create_tm=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            mongo.db.tasks.insert({'title':taskName,
            'target':taskTargets,'create':create_tm})
            taskTargets=taskTargets.split('\n')#将字符串拆分转成列表
            for target in taskTargets:
                target=target.rstrip(' ')
                if target[0].isalpha():
                    subs=Subdomain(target)
                    resualt = list(subs.values())
                    data = resualt[5:]	#数据集的数据部分
                    #print(data[0]) #输出最后的结果
                    for line in data[0]:
                        line.append(taskName)
                        mongo.db.subdomains.insert({'host':line[0],'ip':line[1],'port':line[2],'web_title':line[3],'country':line[4],'province':line[5],'city':line[6],'task_name':line[7]})
                        
                        host=line[0].rstrip() 
                        ip=line[1].rstrip() 
                        port=line[2].rstrip()
                        cdn_status = CDN(host,ip,port)
                        if cdn_status == 'nocdn':
                            print(ip+"目标不存在CDN: Over ++++++")
                        elif cdn_status == 'iscdn':
                            mongo.db.subdomains.update({'ip':ip,'port':port},{'$set':{'ip':'CDN'}})
                            print(ip+"目标存在CDN：Over !!!")
                        elif cdn_status == 'timeout':
                            mongo.db.subdomains.update({'ip':ip,'port':port},{'$set':{'ip':str(ip)+' 连接超时'}})
                            print(ip+"目标连接超时：Stop ~~~")
                        else:
                            mongo.db.subdomains.update({'ip':ip,'port':port},{'$set':{'ip':'可能存在CDN'}})
                            print(ip+"目标存在CDN：Over !!!")

                else:
                    webs=Webs(target)
                    resualt = list(webs.values())
                    data = resualt[5:]	#数据集的数据部分
                    for line in data[0]:
                        line.append(taskName)
                        line.append('-')
                        if (line[4] != 'web') and (line[4] !='Proxy'):
                            mongo.db.webs.insert({'host':line[0],'ip':line[1],'port':line[2],'web_title':line[3],'container':line[4],'country':line[5],'province':line[6],'city':line[7],'task_name':line[8],'tag':line[9]})
                    whatweb(taskName)
    return render_template('admin/create-task.html')


#删除任务
@bp.route('/<string:taskName>/task-del', methods=('GET', 'POST'))
@login_required
def task_del(taskName):
    mongo = PyMongo(current_app)
    mongo.db.tasks.remove({'title':taskName})
    mongo.db.webs.remove({'task_name':taskName})
    mongo.db.subdomains.remove({'task_name':taskName})

    return redirect(url_for('admin.tasklist'))

#子域名列表
@bp.route('/<string:taskName>/subdomain-list',methods=('GET', 'POST'))
@login_required
def subdomain_list(taskName):
    mongo = PyMongo(current_app)
    if taskName is not None:
        lists = mongo.db.subdomains.find({'task_name':taskName})
    else:
        lists = mongo.db.subdomains.find()
    return render_template('admin/subdomain-list.html', lists=lists)

#Web资产列表
@bp.route('/<string:taskName>/web-list',methods=('GET', 'POST'))
@login_required
def web_list(taskName):
    mongo = PyMongo(current_app)
    if taskName is not None:
        tags = mongo.db.webs.find({'task_name':taskName},{'tag':1,'_id':0}).distinct('tag')   #只查tag
        if request.method == 'POST':
            web_tag = request.form['webtag']
            if not web_tag:
                lists = mongo.db.webs.find({'task_name':taskName})
            else:
                lists = mongo.db.webs.find({'task_name':taskName,'tag':web_tag})
            return render_template('admin/web-list.html', lists=lists,tags=tags,taskname=taskName,web_tag=web_tag)
        else:
            lists = mongo.db.webs.find({'task_name':taskName})
            return render_template('admin/web-list.html', lists=lists,tags=tags,taskname=taskName)
    else:
        return render_template('admin/web-list.html')

def Subdomain(rootdomain):
    cmd = '(domain="{dom}") || (cert="{dom}" &&  (status_code="200" || status_code="403") )'.format(dom=rootdomain)
    fofa_query = base64.b64encode(cmd.encode('utf-8')).decode("utf-8")
    fofa_size="2000"
    fields = "host,ip,port,title,country,province,city"
    api = "https://fofa.so/api/v1/search/all?email={email}&key={key}&qbase64={query}&size={size}&fields={fields}".format(email=e_mail,key=k_key,query=fofa_query,size=fofa_size,fields=fields)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.110 Safari/537.36'
    }
    rs = requests.get(api, verify=False, headers=headers)
    rs_text = rs.text
    res = json.loads(rs_text)
    error = res['error']
    if error:
        errmsg = res['errmsg']
        if '401 Unauthorized' in errmsg:
            print('用户名或API 无效！')
            exit(1)
    else:
        return(res)


def Webs(ipc):
    cmd ='ip="'+ipc+'" && (status_code="200" || status_code=="302" || status_code=="403" || status_code=="301" || status_code=="502" || status_code=="404")'
    fofa_query = base64.b64encode(cmd.encode('utf-8')).decode("utf-8")
    fofa_size="2000"
    fields = "host,ip,port,title,server,country,province,city"
    api = "https://fofa.so/api/v1/search/all?email={email}&key={key}&qbase64={query}&size={size}&fields={fields}".format(email=e_mail,key=k_key,query=fofa_query,size=fofa_size,fields=fields)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.110 Safari/537.36'
    }
    r = requests.get(api, verify=False, headers=headers)
    rs_text = r.text
    res = json.loads(rs_text)
    error = res['error']
    if error:
        errmsg = res['errmsg']
        if '401 Unauthorized' in errmsg:
            print('用户名或API 无效！')
            exit(1)
    else:
        return(res)
#根据ICON_HASH匹配资产
def iconhash_search(icon_hash):
    cmd =icon_hash
    fofa_query = base64.b64encode(cmd.encode('utf-8')).decode("utf-8")
    fofa_size="2000"
    fields = "host,ip,port,title,server,country,province,city"
    api = "https://fofa.so/api/v1/search/all?email={email}&key={key}&qbase64={query}&size={size}&fields={fields}".format(email=e_mail,key=k_key,query=fofa_query,size=fofa_size,fields=fields)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.110 Safari/537.36'
    }
    r = requests.get(api, verify=False, headers=headers)
    rs_text = r.text
    res = json.loads(rs_text)
    error = res['error']
    if error:
        errmsg = res['errmsg']
        if '401 Unauthorized' in errmsg:
            print('用户名或API 无效！')
            exit(1)
    else:
        return(res)

#修改密码
@bp.route('/<int:uid>/pass-edit', methods=('GET', 'POST'))
@login_required
def pass_edit(uid):
    if request.method == 'POST':
        password = request.form['password']
        error = None

        if not password:
            error = '密码不能为空'

        if error is not None:
            flash(error)
        else:
            mongo = PyMongo(current_app)
            mongo.db.user.update({'uid':uid},{'$set':{'password':password}})

    return render_template('admin/password-edit.html')

#导出URL
@bp.route('/<string:taskName>/export_url', methods=('GET', 'POST'))
def export_url(taskName):
    all_url=[]
    mongo=PyMongo(current_app)
    web_tag = request.args.get("web_tag")
    if web_tag:
        URLS = mongo.db.webs.find({'task_name':taskName,'tag':web_tag},{'host':1,'_id':0})
    else:
        URLS = mongo.db.webs.find({'task_name':taskName},{'host':1,'_id':0})
    for url in URLS:
        url=url['host'].rstrip()
        if(url[0:4]=="http"):
            url=url
        else:
            url="http://"+url
        if url not in all_url:
            all_url.append(url)
    return render_template('admin/exp-url.html',all_url=all_url)

#Web指纹识别
def resWeb(url,host,taskName):
    app = Flask(__name__)
    with app.app_context():
        app.config['MONGO_URI'] =  "mongodb://{host}:{port}/{database}".format(
        host='localhost',
        port=27017,
        database='webapp'
        )
        try:
            mongo = PyMongo(app)
            tags = mongo.db.webs.find({'task_name':taskName,'host':host},{'tag':1,'_id':0})
            for line in tags:
                tag = line['tag']
            resp = requests.get(url,cookies=cookies,timeout=8,verify=False)#忽略对 SSL 证书的验证
            resp_err = requests.get(url+'/tt',timeout=8,verify=False)#请求不存在的页面去让页面报错
            for cms,finger in ruleDatas.items():
                hitHeads = re.findall(finger, str(resp.headers))
                hitBody = re.findall(finger, resp.text)
                hitBody_err = re.findall(finger, resp_err.text)
                if hitHeads or hitBody or hitBody_err:
                    if tag =='-':
                        print("===========组件信息-{0}：".format(cms)+url)
                        mongo.db.webs.update({'host':host,'task_name':taskName},{'$set':{'tag':cms}})
                else:
                    pass
            mongo.db.client.close()
            mongo = None
            resp.close()
            print("--正在识别--"+url)
        except Exception as ex:
            mongo.db.webs.update({'host':host,'task_name':taskName},{'$set':{'tag':'连接失败'}})
            #mongo.db.webs.remove({'host':host,'task_name':taskName})
            mongo.db.client.close()
            mongo = None
        finally:
            mongo = None
            thread_max.release()

def whatweb(taskName):
    mongo = PyMongo(current_app)
    hosts = mongo.db.webs.find({'task_name':taskName},{'host':1,'_id':0})
    threads = []
    for hs in hosts:
        if hs['host'][0:4]=='http':
            host = hs['host']
            url = hs['host']
        else:
            host = hs['host']
            url = "http://"+hs['host']
        thread_max.acquire()
        t = threading.Thread(target=resWeb,args=(url,host,taskName,))
        threads.append(t)
        t.start()
    for j in threads:
        j.join()

#ICON_HASH计算
@bp.route('/icohash', methods=('GET', 'POST'))
def icohash():
    if request.method == 'POST':
        ico_url = request.form['icourl']
        i_hash = getfaviconhash(ico_url)
        icon_hash='icon_hash="{0}"'.format(str(i_hash))
        print(icon_hash)

        re_dis.flushall()#先清空Redis缓存
        re_dis.set('fofa_icon',icon_hash)
        fofa_icon=re_dis.get('fofa_icon')
        
        ico_webs=iconhash_search(icon_hash)
        resualt = list(ico_webs.values())
        data = resualt[5:]	#数据集的数据部分

        num = 1
        for line in data[0]:
            #存储进所有公司名 和 组织架构信息进缓存数据库
            re_dis.rpush('all_ico_webs',num)   
            re_dis.hmset(num,{'index':str(num),'host':line[0],'ip':line[1],'port':line[2],'web_title':line[3],'container':line[4],'country':line[5],'province':line[6],'city':line[7]})
            #打印进展
            #print(re_dis.hmget(num,['index','host','ip','port','web_title','container','country','province','city']))
            num = num+1
    else:
        icon_hash="None"
        fofa_icon=re_dis.get('fofa_icon')
    return render_template('admin/icoHash.html',fofa_icon=fofa_icon)
    
def change_format(content):
    count = len(content) % 76
    items = re.findall(r".{76}", content)
    final_item = content[-count:]
    items.append(final_item)
    return "{0}\n".format("\n".join(items))


def getfaviconhash(url):
    try:
        response = requests.get(url, verify=False)
        if response.headers['Content-Type'] == "image/x-icon":
            favicon = base64.b64encode(response.content).decode('utf-8')
            hash = pymmh3.hash(change_format(favicon))
        else:
            hash = None
    except Exception:
        print("[!] Request Error")
        hash = None
    return hash           

#POC插件漏扫
@bp.route('/poc-scan', methods=('GET', 'POST'))
def poc_scan():
    return render_template('admin/poc-scan.html')