# -*- coding: utf-8 -*-
import sys
import json
import uuid
import oss2
import yaml
import base64
import requests
import smtplib
from email.mime.text import MIMEText
from pyDes import des, CBC, PAD_PKCS5
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from urllib3.exceptions import InsecureRequestWarning

# debug模式
debug = True
if debug:
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


# 读取yml配置
def getYmlConfig(yaml_file='config.yml'):
    file = open(yaml_file, 'r', encoding="utf-8")
    file_data = file.read()
    file.close()
    config = yaml.load(file_data, Loader=yaml.FullLoader)
    return dict(config)


# 全局配置
config = getYmlConfig(yaml_file='config.yml')


# 获取当前utc时间，并格式化为北京时间
def getTimeStr():
    utc_dt = datetime.utcnow().replace(tzinfo=timezone.utc)
    bj_dt = utc_dt.astimezone(timezone(timedelta(hours=8)))
    return bj_dt.strftime("%Y-%m-%d %H:%M:%S")


# 输出调试信息，并及时刷新缓冲区
def log(content):
    print(getTimeStr() + ' ' + str(content))
    sys.stdout.flush()


# 获取今日校园api
def getCpdailyApis(user):
    apis = {}
    user = user['user']
    schools = requests.get(url='https://mobile.campushoy.com/v6/config/guest/tenant/list', verify=not debug).json()['data']
    flag = True
    for one in schools:
        if one['name'] == user['school']:
            if one['joinType'] == 'NONE':
                log(user['school'] + ' 未加入今日校园')
                exit(-1)
            flag = False
            params = {
                'ids': one['id']
            }
            res = requests.get(url='https://mobile.campushoy.com/v6/config/guest/tenant/info', params=params,
                               verify=not debug)
            data = res.json()['data'][0]
            joinType = data['joinType']
            idsUrl = data['idsUrl']
            ampUrl = data['ampUrl']
            if 'campusphere' in ampUrl or 'cpdaily' in ampUrl:
                parse = urlparse(ampUrl)
                host = parse.netloc
                res = requests.get(parse.scheme + '://' + host)
                parse = urlparse(res.url)
                apis['login-url'] = idsUrl + '/login?service=' + parse.scheme + r"%3A%2F%2F" + host + r'%2Fportal%2Flogin'
                apis['host'] = host

            ampUrl2 = data['ampUrl2']
            if 'campusphere' in ampUrl2 or 'cpdaily' in ampUrl2:
                parse = urlparse(ampUrl2)
                host = parse.netloc
                res = requests.get(parse.scheme + '://' + host)
                parse = urlparse(res.url)
                apis['login-url'] = idsUrl + '/login?service=' + parse.scheme + r"%3A%2F%2F" + host + r'%2Fportal%2Flogin'
                apis['host'] = host
            break
    if flag:
        log(user['school'] + ' 未找到该院校信息，请检查是否是学校全称错误')
        exit(-1)
    return apis


# 登陆并获取session
def getSession(user, apis):
    user = user['user']
    params = {
        'login_url': apis['login-url'],
        'needcaptcha_url': '',
        'captcha_url': '',
        'username': user['username'],
        'password': user['password']
    }

    cookies = {}
    # 借助上一个项目开放出来的登陆API，模拟登陆
    res = ''
    try:
        res = requests.post(url=config['login']['api'], data=params, verify=not debug)
    except Exception as e:
        res = requests.post(url='http://127.0.0.1:8080/wisedu-unified-login-api-v1.0/api/login', data=params, verify=not debug)
    
    # cookieStr可以使用手动抓包获取到的cookie，有效期暂时未知，请自己测试
    cookieStr = str(res.json()['cookies'])
    if cookieStr == 'None':
        log(res.json())
        exit(-1)

    # 解析cookie
    for line in cookieStr.split(';'):
        name, value = line.strip().split('=', 1)
        cookies[name] = value
    session = requests.session()
    session.cookies = requests.utils.cookiejar_from_dict(cookies, cookiejar=None, overwrite=True)
    return session


# 获取最新未签到任务并全部签到
def getUnSignedTasksAndSign(session, apis, user):
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.97 Safari/537.36',
        'content-type': 'application/json',
        'Accept-Encoding': 'gzip,deflate',
        'Accept-Language': 'zh-CN,en-US;q=0.8',
        'Content-Type': 'application/json;charset=UTF-8'
    }
    # 第一次请求每日签到任务接口，主要是为了获取MOD_AUTH_CAS
    res = session.post(
        url='https://{host}/wec-counselor-sign-apps/stu/sign/queryDailySginTasks'.format(host=apis['host']),
        headers=headers, data=json.dumps({}), verify=not debug)
    # 第二次请求每日签到任务接口，拿到具体的签到任务
    res = session.post(
        url='https://{host}/wec-counselor-sign-apps/stu/sign/queryDailySginTasks'.format(host=apis['host']),
        headers=headers, data=json.dumps({}), verify=not debug)
    if len(res.json()['datas']['unSignedTasks']) < 1:
        log('当前没有未签到任务')
        exit(-1)
    for i in range(0, len(res.json()['datas']['unSignedTasks'])):
            latestTask = res.json()['datas']['unSignedTasks'][i]
            params = {
              'signInstanceWid': latestTask['signInstanceWid'],
              'signWid': latestTask['signWid']
            }
            task = getDetailTask(session, params, apis)
            form = fillForm(task, session, user, apis)
            submitForm(session, user, form, apis)


# 获取签到任务详情
def getDetailTask(session, params, apis):
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.97 Safari/537.36',
        'content-type': 'application/json',
        'Accept-Encoding': 'gzip,deflate',
        'Accept-Language': 'zh-CN,en-US;q=0.8',
        'Content-Type': 'application/json;charset=UTF-8'
    }
    res = session.post(
        url='https://{host}/wec-counselor-sign-apps/stu/sign/detailSignTaskInst'.format(host=apis['host']),
        headers=headers, data=json.dumps(params), verify=not debug)
    data = res.json()['datas']
    return data


# 填充表单
def fillForm(task, session, user, apis):
    user = user['user']
    form = {}
    if task['isPhoto'] == 1:
        fileName = uploadPicture(session, user['photo'], apis)
        form['signPhotoUrl'] = getPictureUrl(session, fileName, apis)
    else:
        form['signPhotoUrl'] = ''
    if task['isNeedExtra'] == 1:
        extraFields = task['extraField']
        defaults = config['cpdaily']['defaults']
        extraFieldItemValues = []
        for i in range(0, len(extraFields)):
            default = defaults[i]['default']
            extraField = extraFields[i]
            if config['cpdaily']['check'] and str(extraField['title']).startswith(default['title']) is False:
                log(extraField['title'])
                log(default['title'])
                log('第%d个默认配置项错误，请检查' % (i + 1))
                exit(-1)
            extraFieldItems = extraField['extraFieldItems']
            for extraFieldItem in extraFieldItems:
                if extraFieldItem['content'] == default['value']:
                    extraFieldItemValue = {'extraFieldItemValue': default['value'],
                                           'extraFieldItemWid': extraFieldItem['wid']}
                    # 其他，额外文本
                    if extraFieldItem['isOtherItems'] == 1:
                        extraFieldItemValue = {'extraFieldItemValue': default['other'],
                                               'extraFieldItemWid': extraFieldItem['wid']}
                    extraFieldItemValues.append(extraFieldItemValue)
        # log(extraFieldItemValues)
        # 处理带附加选项的签到
        form['extraFieldItems'] = extraFieldItemValues
    # form['signInstanceWid'] = params['signInstanceWid']
    form['signInstanceWid'] = task['signInstanceWid']
    form['longitude'] = user['lon']
    form['latitude'] = user['lat']
    form['isMalposition'] = task['isMalposition']
    form['abnormalReason'] = user['abnormalReason']
    form['position'] = user['address']
    return form



# DES加密
def DESEncrypt(s, key='ST83=@XV'):
    key = key
    iv = b"\x01\x02\x03\x04\x05\x06\x07\x08"
    k = des(key, CBC, iv, pad=None, padmode=PAD_PKCS5)
    encrypt_str = k.encrypt(s)
    return base64.b64encode(encrypt_str).decode()


# 提交签到任务
def submitForm(session, user, form, apis):
    user = user['user']
    # Cpdaily-Extension
    extension = {
        "lon": user['lon'],
        "model": "OPPO R11 Plus",
        "appVersion": "8.1.14",
        "systemVersion": "8.0",
        "userId": user['username'],
        "systemName": "android",
        "lat": user['lat'],
        "deviceId": str(uuid.uuid1())
    }

    headers = {
        # 'tenantId': '1019318364515869',
        'User-Agent': 'Mozilla/5.0 (Linux; Android 4.4.4; OPPO R11 Plus Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/33.0.0.0 Safari/537.36 okhttp/3.12.4',
        'CpdailyStandAlone': '0',
        'extension': '1',
        'Cpdaily-Extension': DESEncrypt(json.dumps(extension)),
        'Content-Type': 'application/json; charset=utf-8',
        'Accept-Encoding': 'gzip',
        'Connection': 'Keep-Alive'
    }
    res = session.post(url='https://{host}/wec-counselor-sign-apps/stu/sign/completeSignIn'.format(host=apis['host']),
                       headers=headers, data=json.dumps(form), verify=not debug)
    message = res.json()['message']
    if message == 'SUCCESS':
        log('自动签到成功')
        m = config['mail'];
        sendEmail(m['smtpserver'], m['pwd'], m['sender'], user['email'], '自动签到成功')
    else:
        log('自动签到失败，原因是：' + message)
        exit(-1)


# 发送邮件通知
def sendEmail(server, pwd, sender, receiver, content):
    if content.count("未开始")>0:
        return ''
    log('正在发送邮件通知')
    log(getTimeStr())

    msg = MIMEText(content, 'plain', 'utf-8')
    msg['from'] = sender
    msg['to'] = receiver
    msg['subject'] = "今日校园自动签到结果通知"

    # 发送邮件
    smtp = smtplib.SMTP()
    smtp.connect(server)
    smtp.login(sender, pwd)    
    smtp.sendmail(sender, receiver, msg.as_string())  
    smtp.quit()
    log('发送邮件通知成功')


# 主函数
def main():
    for user in config['users']:
        apis = config['core-api'] or getCpdailyApis(user)
        session = getSession(user, apis)
        getUnSignedTasksAndSign(session, apis, user)


# 提供给腾讯云函数调用的启动函数
def main_handler(event, context):
    try:
        main()
    except Exception as e:
        raise e
    else:
        return 'success'


if __name__ == '__main__':
    print(main_handler({}, {}))