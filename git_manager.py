# -*- coding: utf-8 -*-

import os
import subprocess
import shutil
import time
import logging
import stat
from datetime import datetime
from config import REPO_DIR, REPO_URL, REPO_USER, REPO_NAME, UPDATE_INTERVAL
from proxy_manager import get_best_proxy, update_proxy_status

# 获取logger实例
logger = logging.getLogger(__name__)

# 全局变量
last_update_time = "N/A"
last_update_status = "N/A"

def get_clone_url(mirror):
    """根据镜像地址构建完整的克隆URL"""
    repo_path = f"{REPO_USER}/{REPO_NAME}.git"
    if "gitclone.com" in mirror:
        return f"https://gitclone.com/github.com/{repo_path}"
    if "hub.fastgit.xyz" in mirror:
        return f"https://hub.fastgit.xyz/{repo_path}"
    # 其他代理类镜像的通用拼接规则
    return f"{mirror}https://github.com/{repo_path}"

def update_repo():
    """克隆或更新仓库，并管理代理状态"""
    global last_update_time, last_update_status

    def do_clone():
        """执行克隆操作"""
        cloned_successfully = False
        # 尝试使用最优代理进行克隆
        while True:
            best_proxy = get_best_proxy()
            if not best_proxy:
                logger.error("没有可用的代理进行克隆。")
                break
            
            clone_url = get_clone_url(best_proxy)
            logger.info(f"尝试从最优代理 {clone_url} 克隆...")
            try:
                # 移除 capture_output=True 让日志直接显示在终端
                subprocess.run(["git", "clone", "--depth=1", clone_url, REPO_DIR], check=True, timeout=300)
                logger.info(f"从 {clone_url} 克隆成功。")
                update_proxy_status(best_proxy, True)
                cloned_successfully = True
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                logger.error(f"从 {clone_url} 克隆失败: {e}")
                update_proxy_status(best_proxy, False)
                if os.path.exists(REPO_DIR):
                    shutil.rmtree(REPO_DIR)
        
        # 如果所有代理都失败了，尝试从原始地址克隆
        if not cloned_successfully:
            logger.info("所有代理克隆失败，尝试从原始GitHub地址克隆...")
            try:
                subprocess.run(["git", "clone", "--depth=1", REPO_URL, REPO_DIR], check=True, timeout=300)
                logger.info("从原始GitHub地址克隆成功。")
                cloned_successfully = True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                logger.critical(f"从原始GitHub地址克隆失败: {e}")
        return cloned_successfully

    def do_pull():
        """执行拉取更新操作"""
        try:
            # 清理可能存在的锁文件
            if os.path.exists(os.path.join(REPO_DIR, '.git', 'index.lock')):
                os.remove(os.path.join(REPO_DIR, '.git', 'index.lock'))
            # 重置本地改动并拉取最新
            subprocess.run(["git", "-C", REPO_DIR, "fetch", "--all"], check=True, timeout=120)
            subprocess.run(["git", "-C", REPO_DIR, "reset", "--hard", "origin/main"], check=True, timeout=120) # 修正：使用 main 分支
            subprocess.run(["git", "-C", REPO_DIR, "pull"], check=True, timeout=120)
            logger.info("仓库更新成功。")
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error(f"更新仓库失败: {e}")
            return False

    if not os.path.exists(REPO_DIR):
        logger.info(f"目录 '{REPO_DIR}' 不存在。正在克隆仓库...")
        if do_clone():
            last_update_status = "克隆成功"
        else:
            last_update_status = "克隆失败"
    else:
        logger.info("仓库已存在。正在拉取最新更改...")
        if do_pull():
            last_update_status = "更新成功"
        else:
            logger.warning("更新失败。尝试删除并重新克隆...")
            last_update_status = "更新失败，正在尝试重新克隆"
            try:
                # 添加onerror处理函数以解决Windows下的文件锁定问题
                shutil.rmtree(REPO_DIR, onerror=handle_remove_readonly)
                logger.info(f"成功删除旧的仓库目录: {REPO_DIR}")
                if do_clone():
                    last_update_status = "重新克隆成功"
                else:
                    last_update_status = "重新克隆失败"
            except OSError as e:
                logger.error(f"删除仓库目录 {REPO_DIR} 失败: {e}")
                last_update_status = f"删除仓库失败: {e}"


    last_update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def handle_remove_readonly(func, path, exc_info):
    """
    错误处理函数，用于shutil.rmtree。
    如果发生权限错误，它会修改文件权限并重试。
    """
    # exc_info[1]是异常实例
    if not isinstance(exc_info[1], PermissionError):
        raise
    logger.warning(f"删除 {path} 时权限被拒绝。尝试修改权限后重试...")
    os.chmod(path, stat.S_IWRITE)
    func(path)

def background_updater():
    """后台定时任务，周期性地更新仓库。"""
    logger.info("启动后台更新器...")
    while True:
        logger.info("开始执行周期性仓库同步...")
        update_repo()
        logger.info(f"同步任务完成。下一次更新在 {UPDATE_INTERVAL} 秒后。")
        time.sleep(UPDATE_INTERVAL)

def get_last_update_status():
    """返回最后更新时间和状态"""
    return last_update_time, last_update_status
