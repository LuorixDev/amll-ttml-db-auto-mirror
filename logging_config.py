# -*- coding: utf-8 -*-

import logging
import logging.handlers
from flask import request
from config import LOG_FILE

class NoApiLogFilter(logging.Filter):
    """一个日志过滤器，用于忽略对特定API端点的访问日志。"""
    def filter(self, record):
        # record.getMessage() 包含完整的日志字符串
        # 我们检查请求的路径是否是我们想要忽略的
        # Werkzeug日志格式通常包含请求行，如 "GET /api/log HTTP/1.1"
        # 同时，我们也要确保 request context 是可用的
        try:
            # 只有在Flask的请求上下文中，request对象才可用
            if request and request.path == '/api/log':
                return False  # 返回False，表示这条日志不应被处理
        except RuntimeError:
            # 如果不在请求上下文中（例如，应用启动时的日志），正常处理
            pass
        
        # 对于其他更通用的日志，也可以通过消息内容来判断
        if 'GET /api/log' in record.getMessage():
            return False
            
        return True # 返回True，表示这条日志应该被处理

def setup_logging():
    """配置全局日志"""
    # 创建 formatter
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # --- 文件处理器 ---
    # 使用 RotatingFileHandler 可以在日志文件达到一定大小时自动轮转
    # 这里设置为5MB一个文件，最多保留5个备份
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    # --- 控制台处理器 ---
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    # --- 配置根 logger ---
    # 使用 basicConfig 配置根 logger。
    # 这将确保任何通过 logging.getLogger(__name__) 创建的 logger
    # 都会继承这些设置。
    # 设置 force=True (Python 3.8+) 可以覆盖任何由库进行的预先配置。
    logging.basicConfig(
        level=logging.INFO,
        handlers=[file_handler, stream_handler],
        force=True  # 强制重新配置
    )

    # --- 添加过滤器 ---
    # 获取Werkzeug的logger，Flask用它来记录访问日志
    werkzeug_logger = logging.getLogger('werkzeug')
    # 为werkzeug logger也设置我们的处理器，以确保格式统一
    werkzeug_logger.setLevel(logging.INFO)
    werkzeug_logger.propagate = False # 防止日志被传递到根logger，避免重复记录
    werkzeug_logger.addHandler(file_handler)
    werkzeug_logger.addHandler(stream_handler)
    
    # 添加我们自定义的过滤器
    werkzeug_logger.addFilter(NoApiLogFilter())

    # 初始日志，确认配置已加载
    logging.info("Logging configuration loaded successfully.")
