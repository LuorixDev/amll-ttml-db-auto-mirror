# -*- coding: utf-8 -*-

import logging
import threading

# --- 核心初始化 ---
# 1. 配置日志 (必须最先执行)
from logging_config import setup_logging
setup_logging()

# --- 导入其他模块 ---
# 导入Flask app实例
from app import app
# 导入需要在启动时运行的函数
from database import init_db
from proxy_manager import load_proxy_status
from git_manager import background_updater

# 获取logger实例
logger = logging.getLogger(__name__)


# --- 应用主入口 ---
if __name__ == "__main__":
    logger.info("----------------------- Application Begin -----------------------")
    
    # 1. 初始化数据库
    logger.info("Initializing database...")
    init_db()
    
    # 2. 加载代理状态
    logger.info("Loading proxy status...")
    load_proxy_status()
    
    # 3. 在后台线程中启动仓库更新器
    logger.info("Starting background repository updater...")
    updater_thread = threading.Thread(target=background_updater, daemon=True)
    updater_thread.start()
    
    # 4. 运行Flask Web服务器
    logger.info("Starting Flask server, listening on http://0.0.0.0:5000")
    # 在生产环境中，建议使用Gunicorn或uWSGI等WSGI服务器代替Flask内置的开发服务器
    # 例如: gunicorn --workers 4 --bind 0.0.0.0:5000 main:app
    app.run(host='0.0.0.0', port=5000)
