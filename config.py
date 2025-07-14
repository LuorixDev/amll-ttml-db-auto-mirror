# -*- coding: utf-8 -*-

# --- 配置部分 ---

# 目标Git仓库地址
REPO_URL = "https://github.com/Steve-xmh/amll-ttml-db.git"
# 本地克隆目录
REPO_DIR = "db_mirror"
# 自动更新间隔（秒），这里是10分钟
UPDATE_INTERVAL = 10 * 60
# 数据库文件
DB_FILE = "stats.db"
# 代理状态持久化文件
PROXY_STATUS_FILE = "proxy_status.json"
# 日志文件
LOG_FILE = "app.log"
# Git镜像代理前缀列表
MIRRORS = [
    "https://ghproxy.com/", "https://github.91chi.fun/", "https://gh.api.99988866.xyz/",
    "https://mirror.ghproxy.com/", "https://gh.con.sh/", "https://hub.fastgit.xyz/",
    "https://gitclone.com/", "https://github.moeyy.xyz/"
]
# 仓库的用户名和仓库名
REPO_USER = "Steve-xmh"
REPO_NAME = "amll-ttml-db"
