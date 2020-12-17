#!/bin/bash

# 初始化依赖
cd /auto-sign
pip --default-timeout=1000 --trusted-host mirrors.aliyun.com install -i http://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

pip --version
pip list

# 启动auto-sign
python timer.py