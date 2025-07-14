# -*- coding: utf-8 -*-

import os
from config import REPO_DIR

def get_dir_size_mb():
    """获取db_mirror目录的大小(MB)"""
    dir_size = 0
    if os.path.exists(REPO_DIR):
        for path, dirs, files in os.walk(REPO_DIR):
            for f in files:
                fp = os.path.join(path, f)
                if not os.path.islink(fp):
                    dir_size += os.path.getsize(fp)
    return f"{dir_size / (1024 * 1024):.2f} MB"
