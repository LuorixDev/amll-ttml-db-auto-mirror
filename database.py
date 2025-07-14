# -*- coding: utf-8 -*-

import sqlite3
import logging
from datetime import datetime
from config import DB_FILE

# 获取logger实例
logger = logging.getLogger(__name__)

def init_db():
    """初始化数据库"""
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        # 创建ncm访问日志表
        c.execute('''
            CREATE TABLE IF NOT EXISTS ncm_access_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                song_id TEXT NOT NULL,
                accessed_at TIMESTAMP NOT NULL
            )
        ''')
        # 创建ncm歌曲信息表
        c.execute('''
            CREATE TABLE IF NOT EXISTS ncm_song_info (
                song_id TEXT PRIMARY KEY,
                song_name TEXT,
                artists TEXT,
                album TEXT,
                last_updated TIMESTAMP
            )
        ''')
        # 创建NCM无歌词记录表
        c.execute('''
            CREATE TABLE IF NOT EXISTS ncm_no_lyrics (
                song_id TEXT PRIMARY KEY,
                song_name TEXT,
                artists TEXT,
                album TEXT,
                first_seen TIMESTAMP,
                attempt_count INTEGER DEFAULT 0
            )
        ''')
        # 创建404记录表
        c.execute('''
            CREATE TABLE IF NOT EXISTS not_found (
                path TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0,
                last_seen TIMESTAMP
            )
        ''')
        conn.commit()
    logger.info("数据库初始化完成。")

def record_ncm_access(song_id):
    """记录每一次NCM歌曲的访问"""
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        now = datetime.now()
        c.execute(
            "INSERT INTO ncm_access_log (song_id, accessed_at) VALUES (?, ?)",
            (song_id, now)
        )
        conn.commit()
        logger.info(f"记录NCM访问: song_id={song_id} at {now}")

def record_not_found(path):
    """记录404路径"""
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        now = datetime.now()
        c.execute('''
            INSERT INTO not_found (path, count, last_seen) VALUES (?, 1, ?)
            ON CONFLICT(path) DO UPDATE SET
            count = count + 1, last_seen = ?
        ''', (path, now, now))
        conn.commit()
        logger.warning(f"记录404路径: {path}")

def get_db_stats():
    """获取数据库的统计信息"""
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        # 统计独立歌曲ID的数量
        c.execute("SELECT COUNT(DISTINCT song_id) FROM ncm_access_log")
        ncm_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM not_found")
        not_found_count = c.fetchone()[0]
    return ncm_count, not_found_count

def get_ncm_stats():
    """计算并获取NCM访问统计数据"""
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        # 通过分组和计数来动态计算访问次数
        c.execute('''
            SELECT
                song_id,
                COUNT(song_id) AS access_count,
                MAX(accessed_at) AS last_accessed
            FROM ncm_access_log
            GROUP BY song_id
            ORDER BY access_count DESC, last_accessed DESC
            LIMIT 1000
        ''')
        stats = c.fetchall()
    return stats

def get_song_info(song_ids):
    """根据song_id列表从数据库获取已知的歌曲详情"""
    if not song_ids:
        return {}
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        placeholders = ','.join('?' for _ in song_ids)
        query = f"SELECT song_id, song_name, artists, album FROM ncm_song_info WHERE song_id IN ({placeholders})"
        c.execute(query, song_ids)
        # 将结果转换为 {song_id: {info}} 的形式
        return {str(row['song_id']): dict(row) for row in c.fetchall()}

def update_song_info(song_details_map):
    """批量更新或插入歌曲详情到数据库"""
    if not song_details_map:
        return
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        now = datetime.now()
        data_to_insert = [
            (
                song_id,
                details['name'],
                details['artists'],
                details['album'],
                now
            ) for song_id, details in song_details_map.items()
        ]
        c.executemany('''
            INSERT INTO ncm_song_info (song_id, song_name, artists, album, last_updated) 
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(song_id) DO UPDATE SET
                song_name = excluded.song_name,
                artists = excluded.artists,
                album = excluded.album,
                last_updated = excluded.last_updated
        ''', data_to_insert)
        conn.commit()
        logger.info(f"更新了 {len(data_to_insert)} 首歌曲的信息。")

def add_ncm_no_lyrics_entry(song_id, details):
    """添加一条NCM无歌词记录，如果已存在则增加尝试次数"""
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        now = datetime.now()
        # 尝试插入，如果冲突（已存在），则更新尝试次数
        c.execute('''
            INSERT INTO ncm_no_lyrics (song_id, song_name, artists, album, first_seen, attempt_count)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(song_id) DO UPDATE SET
            attempt_count = attempt_count + 1
        ''', (song_id, details['name'], details['artists'], details['album'], now))
        logger.info(f"记录一次对无歌词NCM歌曲的访问尝试: {song_id}")
        conn.commit()

def get_ncm_no_lyrics_stats():
    """获取所有NCM无歌词的歌曲记录，按尝试次数排序"""
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM ncm_no_lyrics ORDER BY attempt_count DESC")
        return c.fetchall()

def remove_ncm_no_lyrics_entry(song_id):
    """如果歌曲已有歌词，从无歌词记录中移除"""
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM ncm_no_lyrics WHERE song_id = ?", (song_id,))
        if c.rowcount > 0:
            logger.info(f"歌曲 {song_id} 已找到歌词，从'无歌词'列表中移除。")
        conn.commit()

def get_ncm_dashboard_stats(period='today'):
    """获取NCM仪表盘的统计数据"""
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # 根据period确定时间范围
        if period == 'today':
            time_filter = "WHERE date(accessed_at) = date('now')"
            no_lyrics_time_filter = "WHERE date(first_seen) = date('now')"
        elif period == 'monthly':
            time_filter = "WHERE strftime('%Y-%m', accessed_at) = strftime('%Y-%m', 'now')"
            no_lyrics_time_filter = "WHERE strftime('%Y-%m', first_seen) = strftime('%Y-%m', 'now')"
        elif period == 'yearly':
            time_filter = "WHERE strftime('%Y', accessed_at) = strftime('%Y', 'now')"
            no_lyrics_time_filter = "WHERE strftime('%Y', first_seen) = strftime('%Y', 'now')"
        else: # total
            time_filter = ""
            no_lyrics_time_filter = ""

        # 查询统计数据
        c.execute(f"SELECT COUNT(DISTINCT song_id) FROM ncm_access_log {time_filter}")
        acquired = c.fetchone()[0]
        
        c.execute(f"SELECT COUNT(*) FROM ncm_no_lyrics {no_lyrics_time_filter}")
        no_lyrics = c.fetchone()[0]

        # 查询热度歌曲
        c.execute(f'''
            SELECT s.song_name, COUNT(l.song_id) as count
            FROM ncm_access_log l
            JOIN ncm_song_info s ON l.song_id = s.song_id
            {time_filter}
            GROUP BY l.song_id, s.song_name
            ORDER BY count DESC
            LIMIT 10
        ''')
        hot_songs = [dict(row) for row in c.fetchall()]

        # 查询热度歌手
        c.execute(f'''
            SELECT s.artists, COUNT(l.song_id) as count
            FROM ncm_access_log l
            JOIN ncm_song_info s ON l.song_id = s.song_id
            {time_filter}
            GROUP BY s.artists
            ORDER BY count DESC
            LIMIT 10
        ''')
        hot_artists = [dict(row) for row in c.fetchall()]
        
    return {
        "stats": {"acquired": acquired, "no_lyrics": no_lyrics},
        "hot_songs": hot_songs,
        "hot_artists": hot_artists
    }
