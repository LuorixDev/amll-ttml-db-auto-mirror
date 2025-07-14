# -*- coding: utf-8 -*-

import os
import re
import logging
from datetime import datetime
from flask import Flask, send_from_directory, render_template, url_for, after_this_request, jsonify, request
from urllib.parse import unquote

# --- 导入自定义模块 ---
from config import REPO_DIR, LOG_FILE
from database import (record_ncm_access, record_not_found, get_db_stats,
                      get_ncm_stats, get_song_info, update_song_info,
                      add_ncm_no_lyrics_entry, get_ncm_no_lyrics_stats,
                      remove_ncm_no_lyrics_entry, get_ncm_dashboard_stats)
from proxy_manager import get_proxy_status
from git_manager import get_last_update_status
from utils import get_dir_size_mb
from ncm_api import fetch_song_details_from_api

# --- 初始化 ---
logger = logging.getLogger(__name__)
app = Flask(__name__)

# --- Flask路由 ---

@app.route('/')
def index():
    """主页，只提供页面框架"""
    return render_template('index.html')

@app.route('/api/status')
def api_status():
    """提供主页需要的全部动态数据"""
    dir_size_mb = get_dir_size_mb()
    ncm_count, not_found_count = get_db_stats()
    no_lyrics_count = len(get_ncm_no_lyrics_stats())
    last_update_time, last_update_status = get_last_update_status()
    proxy_status = get_proxy_status()
    
    # 对代理状态进行排序，以便在前端直接使用
    # sorted返回一个列表，列表中的元素是元组 (key, value)
    sorted_proxy_status = sorted(proxy_status.items(), key=lambda item: item[1], reverse=True)

    status_data = {
        'last_update_time': last_update_time,
        'last_update_status': last_update_status,
        'dir_size_mb': dir_size_mb,
        'ncm_count': ncm_count,
        'not_found_count': not_found_count,
        'no_lyrics_count': no_lyrics_count,
        'proxy_status': sorted_proxy_status
    }
    return jsonify(status_data)

@app.route('/api/db/', defaults={'path': ''})
@app.route('/api/db/<path:path>')
def serve_db_path(path):
    """提供对 'db_mirror' 目录中文件和目录列表的访问，并实现点击跳转"""
    base_dir = os.path.abspath(REPO_DIR)
    decoded_path = unquote(path)
    target_path = os.path.join(base_dir, decoded_path)

    if not target_path.startswith(base_dir):
        return "禁止访问。", 403

    if not os.path.exists(base_dir):
        return "仓库尚未克隆，请稍候。", 503

    if not os.path.exists(target_path):
        # 路径不存在，记录404
        record_not_found(decoded_path)
        
        # 检查是否是NCM歌词路径
        match = re.search(r'ncm-lyrics/(\d+)\.ttml', decoded_path)
        if match:
            song_id = match.group(1)
            logger.info(f"路径 {decoded_path} 未找到，检查是否为有效的NCM歌曲...")
            song_details = fetch_song_details_from_api([song_id])
            if song_id in song_details:
                # 歌曲有效，但没有歌词文件，记录到ncm_no_lyrics
                add_ncm_no_lyrics_entry(song_id, song_details[song_id])

        return "路径未找到。", 404

    if os.path.isdir(target_path):
        entries = os.listdir(target_path)
        dirs = sorted([d for d in entries if os.path.isdir(os.path.join(target_path, d))])
        files = sorted([f for f in entries if os.path.isfile(os.path.join(target_path, f))])
        
        breadcrumbs = [{'name': '根目录', 'path': ''}]
        if decoded_path:
            parts = decoded_path.split('/')
            current_path = ''
            for part in parts:
                if not part: continue
                current_path = os.path.join(current_path, part)
                breadcrumbs.append({'name': part, 'path': current_path.replace('\\', '/')})

        return render_template('dir_view.html', 
                               current_dir=decoded_path, 
                               dirs=dirs, 
                               files=files,
                               parent_dir=os.path.dirname(decoded_path).replace('\\', '/') if decoded_path else None,
                               breadcrumbs=breadcrumbs)
    
    else:
        match = re.search(r'ncm-lyrics/(\d+)\.ttml', decoded_path)
        if match:
            song_id = match.group(1)
            # 记录本次成功访问
            record_ncm_access(song_id)
            # 如果这首歌之前在“无歌词”列表里，现在将它移除
            remove_ncm_no_lyrics_entry(song_id)
        
        @after_this_request
        def add_header(response):
            if response.status_code in [200, 304]:
                logger.info(f"成功提供文件: {decoded_path}, 状态码: {response.status_code}")
            return response
            
        return send_from_directory(base_dir, decoded_path)

@app.route('/log')
def log_view():
    """提供日志查看页面的框架"""
    return render_template('log_view.html')

@app.route('/api/log')
def api_log():
    """以JSON格式提供最新的日志内容"""
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            # 读取文件尾部的内容可能更高效，但简单起见，我们继续读取最后1000行
            lines = f.readlines()
            log_content = "".join(lines[-1000:])
    except FileNotFoundError:
        log_content = "日志文件未找到。"
    return jsonify({'log_content': log_content})

@app.route('/ncm_view')
def ncm_view():
    """显示NCM访问统计数据，并附带歌曲名称"""
    raw_stats = get_ncm_stats()
    if not raw_stats:
        return "<h1>NCM访问统计</h1><p>暂无数据。</p><a href='/'>返回主页</a>"

    song_ids_on_page = [str(row['song_id']) for row in raw_stats]
    
    # 1. 从数据库获取已知的歌曲详情
    song_info_map = get_song_info(song_ids_on_page)
    
    # 2. 找出未知歌曲的ID并从API获取
    unknown_ids = [sid for sid in song_ids_on_page if sid not in song_info_map]
    if unknown_ids:
        logger.info(f"发现 {len(unknown_ids)} 首未知歌曲，正在从API获取信息...")
        new_song_details = fetch_song_details_from_api(unknown_ids)
        if new_song_details:
            # 3. 将新获取的歌曲详情更新到数据库
            update_song_info(new_song_details)
            # 合并新旧歌曲详情
            song_info_map.update(new_song_details)

    # 4. 整理最终要在页面上显示的数据
    stats = []
    for row in raw_stats:
        stat_item = dict(row)
        song_id_str = str(stat_item['song_id'])
        info = song_info_map.get(song_id_str, {})
        
        stat_item['song_name'] = info.get('song_name', '（未知）')
        stat_item['artists'] = info.get('artists', 'N/A')
        stat_item['album'] = info.get('album', 'N/A')
        
        # 格式化时间
        try:
            # 数据库中的时间戳可能包含毫秒
            dt_object = datetime.strptime(stat_item['last_accessed'], '%Y-%m-%d %H:%M:%S.%f')
            stat_item['last_accessed'] = dt_object.strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            # 如果格式不匹配或值为None，则直接使用原始值
            pass
        stats.append(stat_item)

    return render_template('ncm_view.html', stats=stats)


@app.route('/ncm_no_lyrics_view')
def ncm_no_lyrics_view():
    """显示所有被记录的、有歌曲但无歌词的NCM条目"""
    stats = get_ncm_no_lyrics_stats()
    return render_template('ncm_no_lyrics_view.html', stats=stats)

@app.route('/ncm_dashboard')
def ncm_dashboard():
    """提供NCM仪表盘页面"""
    return render_template('ncm_dashboard.html')

@app.route('/api/ncm_dashboard')
def api_ncm_dashboard():
    """为NCM仪表盘提供数据"""
    period = request.args.get('period', 'today')
    stats = get_ncm_dashboard_stats(period)
    return jsonify(stats)
