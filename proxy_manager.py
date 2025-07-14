# -*- coding: utf-8 -*-

import os
import json
import logging
from config import PROXY_STATUS_FILE, MIRRORS

# 获取logger实例
logger = logging.getLogger(__name__)

# 全局变量
proxy_status = {}

def load_proxy_status():
    """从文件加载代理状态，如果文件不存在则初始化"""
    global proxy_status
    if os.path.exists(PROXY_STATUS_FILE):
        with open(PROXY_STATUS_FILE, 'r') as f:
            proxy_status = json.load(f)
        # 确保所有在MIRRORS中的代理都在状态文件中
        for mirror in MIRRORS:
            if mirror not in proxy_status:
                proxy_status[mirror] = 0
    else:
        # 初始化所有镜像的可用次数为1，给它们一个初始机会
        proxy_status = {mirror: 1 for mirror in MIRRORS}
    save_proxy_status()
    logger.info("代理状态加载完成。")

def save_proxy_status():
    """保存代理状态到文件"""
    with open(PROXY_STATUS_FILE, 'w') as f:
        json.dump(proxy_status, f, indent=4)

def get_best_proxy():
    """选择可用次数最多的代理"""
    if not proxy_status:
        return None
    # 过滤掉可用次数小于等于0的代理
    available_proxies = {p: c for p, c in proxy_status.items() if c > 0}
    if not available_proxies:
        # 如果所有代理都不可用，则重置所有代理的可用次数为1，重新开始
        logger.warning("所有代理均不可用，正在重置所有代理状态。")
        for mirror in MIRRORS:
            proxy_status[mirror] = 1
        save_proxy_status()
        return max(proxy_status, key=proxy_status.get)

    # 返回可用次数最多的代理
    best_proxy = max(available_proxies, key=available_proxies.get)
    logger.info(f"选择最优代理: {best_proxy} (可用次数: {proxy_status[best_proxy]})")
    return best_proxy

def update_proxy_status(mirror, success):
    """更新代理的可用状态"""
    if mirror not in proxy_status:
        return
    if success:
        # 如果成功，增加可用次数
        proxy_status[mirror] += 1
        logger.info(f"代理 {mirror} 使用成功，可用次数增加到 {proxy_status[mirror]}")
    else:
        # 如果失败，可用次数归零
        proxy_status[mirror] = 0
        logger.warning(f"代理 {mirror} 使用失败，可用次数归零。")
    save_proxy_status()

def get_proxy_status():
    """返回当前的代理状态"""
    return proxy_status
