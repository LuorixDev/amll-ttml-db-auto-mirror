# -*- coding: utf-8 -*-

import os
import re
import json
import logging
import requests
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, send_from_directory, render_template, url_for, after_this_request, jsonify, request, session, redirect
from urllib.parse import unquote

# --- 导入自定义模块 ---
from config import REPO_DIR, LOG_FILE
from database import (record_ncm_access, record_not_found, get_db_stats,
                      get_ncm_stats, get_song_info, update_song_info,
                      add_ncm_no_lyrics_entry, get_ncm_no_lyrics_stats,
                      remove_ncm_no_lyrics_entry, get_ncm_dashboard_stats,
                      get_contributors_info, update_contributors_info,
                      record_traffic, get_traffic_stats)
from proxy_manager import get_proxy_status
from git_manager import get_last_update_status
from utils import get_dir_size_mb
from ncm_api import fetch_song_details_from_api

# --- 初始化 ---
logger = logging.getLogger(__name__)
app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- 中间件 ---

@app.after_request
def after_request_func(response):
    """在每次请求后记录流量和响应大小"""
    # 定义不需要记录流量的、用于仪表盘数据接口的API端点
    excluded_api_paths = [
        '/api/status',
        '/api/log',
        '/api/ncm_dashboard',
        '/api/traffic',
        '/api/contributors'
    ]

    # 排除对静态文件、特定API端点、非成功响应或无内容响应的记录
    # 这样可以确保对 /api/db/ 资源的访问被正确统计
    if (request.path.startswith('/static/') or
        request.path in excluded_api_paths or
        not response.content_length):
        return response
    
    # 获取真实IP，优先从 X-Forwarded-For 获取，并处理多IP地址的情况
    x_forwarded_for = request.headers.get('X-Forwarded-For')
    if x_forwarded_for:
        ip_address = x_forwarded_for.split(',')[0].strip()
    else:
        ip_address = request.remote_addr
        
    user_agent = request.headers.get('User-Agent')
    response_size = response.content_length

    record_traffic(request.path, ip_address, user_agent, response_size)
    
    return response

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
            if response.status_code == 200:
                logger.info(f"成功提供文件: {decoded_path}, 状态码: {response.status_code}")
                response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
                response.headers['Pragma'] = 'no-cache'
                response.headers['Expires'] = '0'
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

@app.route('/ncm/refresh/<song_id>', methods=['POST'])
def ncm_refresh_song(song_id):
    """刷新指定歌曲的网易云信息"""
    try:
        logger.info(f"收到刷新歌曲 {song_id} 信息的请求。")
        new_song_details = fetch_song_details_from_api([song_id])
        
        if song_id in new_song_details:
            #print(f"刷新歌曲 {song_id} 的信息: {new_song_details[song_id]}")
            update_song_info({song_id: new_song_details[song_id]})
            logger.info(f"成功刷新并更新了歌曲 {song_id} 的信息。")
            return jsonify({'success': True, 'message': '歌曲信息已刷新。'})
        else:
            logger.warning(f"无法从网易云API获取歌曲 {song_id} 的信息。")
            return jsonify({'success': False, 'message': '无法获取歌曲信息，可能ID无效或API暂时不可用。'})
            
    except Exception as e:
        logger.error(f"刷新歌曲 {song_id} 信息时发生错误: {e}")
        return jsonify({'success': False, 'message': f'服务器内部错误: {e}'}), 500

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

@app.route('/traffic')
def traffic_view():
    """提供流量统计页面的框架"""
    return render_template('traffic_stats.html')

@app.route('/api/traffic')
def api_traffic():
    """以JSON格式提供流量统计数据"""
    period = request.args.get('period', 'today')
    stats = get_traffic_stats(period)
    return jsonify(stats)

@app.route('/contributors')
def contributors_view():
    """提供贡献者页面的框架"""
    return render_template('contributors.html')

@app.route('/api/contributors')
def api_contributors():
    """
    以JSON格式提供贡献者数据，优先从数据库缓存读取，
    仅当数据不存在或陈旧时才从API获取，并处理GitHub API限速。
    """
    contributors_file = os.path.join(REPO_DIR, 'metadata', 'contributors.jsonl')
    if not os.path.exists(contributors_file):
        logger.error(f"贡献者文件未找到: {contributors_file}")
        return jsonify({'error': '贡献者数据文件未找到。'}), 404

    # 1. 从.jsonl文件读取所有贡献者基本信息
    all_contributors = {}
    with open(contributors_file, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                data = json.loads(line)
                github_id = str(data.get('githubId'))
                if github_id:
                    all_contributors[github_id] = {'count': data.get('count', 0)}
            except json.JSONDecodeError:
                logger.warning(f"无法解析行: {line.strip()}")
    
    github_ids = list(all_contributors.keys())
    
    # 2. 从数据库批量获取缓存信息
    cached_info = get_contributors_info(github_ids)
    
    # 3. 确定哪些贡献者需要从API更新
    ids_to_fetch = []
    now = datetime.now()
    for gid in github_ids:
        info = cached_info.get(gid)
        if not info:
            ids_to_fetch.append(gid)
        else:
            last_updated = datetime.strptime(info['last_updated'], '%Y-%m-%d %H:%M:%S.%f')
            if now - last_updated > timedelta(days=1): # 缓存有效期为1天
                ids_to_fetch.append(gid)

    # 4. 从API获取需要更新的数据
    rate_limited = False
    if ids_to_fetch:
        logger.info(f"需要从API获取 {len(ids_to_fetch)} 位贡献者的信息。")
        newly_fetched_info = {}
        avatar_dir = os.path.join('static', 'avatars')
        os.makedirs(avatar_dir, exist_ok=True)

        for gid in ids_to_fetch:
            if rate_limited:
                break
            
            api_url = f"https://api.github.com/user/{gid}"
            try:
                response = requests.get(api_url, timeout=5)
                if response.status_code in [403, 429]:
                    logger.warning(f"GitHub API速率限制已触发。")
                    rate_limited = True
                    continue
                
                response.raise_for_status()
                user_data = response.json()
                avatar_url = user_data.get('avatar_url')

                # 下载并保存头像
                if avatar_url:
                    try:
                        avatar_response = requests.get(avatar_url, timeout=10)
                        avatar_response.raise_for_status()
                        avatar_path = os.path.join(avatar_dir, f"{gid}.png")
                        with open(avatar_path, 'wb') as f:
                            f.write(avatar_response.content)
                    except requests.RequestException as e:
                        logger.error(f"下载ID {gid} 的头像失败: {e}")

                newly_fetched_info[gid] = {
                    'login': user_data.get('login'),
                    'name': user_data.get('name'),
                    'avatar_url': avatar_url # 数据库中仍然存储原始URL
                }
            except requests.RequestException as e:
                logger.error(f"无法从GitHub API获取ID {gid} 的信息: {e}")

        # 5. 更新数据库缓存
        if newly_fetched_info:
            update_contributors_info(newly_fetched_info)
            cached_info.update(newly_fetched_info)

    # 6. 组合最终数据
    final_contributors_data = []
    for gid, data in all_contributors.items():
        info = cached_info.get(gid)
        local_avatar_path = os.path.join('static', 'avatars', f"{gid}.png")
        
        if info:
            # 检查本地头像是否存在，决定使用本地路径还是远程URL
            if os.path.exists(local_avatar_path):
                avatar = url_for('static', filename=f'avatars/{gid}.png')
            else:
                avatar = info.get('avatar_url') # 回退到原始URL

            final_contributors_data.append({
                'login': info.get('login'),
                'avatar_url': avatar,
                'name': info.get('name'),
                'count': data.get('count', 0)
            })
        else:
            # 如果API限速或失败，则显示占位符
            final_contributors_data.append({
                'login': f"ID: {gid}",
                'avatar_url': 'https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png',
                'name': '（加载失败或被限速）',
                'count': data.get('count', 0)
            })

    # 按贡献数量降序排序
    final_contributors_data.sort(key=lambda x: x['count'], reverse=True)
    
    return jsonify({
        'contributors': final_contributors_data,
        'rate_limited': rate_limited
    })

# --- 数据库管理 ---
DB_DIR = os.path.join('data', 'db')
PASSWORD_FILE = 'config_passpord.txt'

def get_password():
    try:
        with open(PASSWORD_FILE, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        return None

@app.route('/db_admin', methods=['GET'])
def db_admin():
    if not session.get('logged_in'):
        return render_template('db_admin.html', logged_in=False)

    db_files = [f for f in os.listdir(DB_DIR) if f.endswith('.db')]
    return render_template('db_admin.html', logged_in=True, db_files=db_files)

@app.route('/db_admin/login', methods=['POST'])
def db_admin_login():
    password = request.form.get('password')
    correct_password = get_password()
    if correct_password and password == correct_password:
        session['logged_in'] = True
        return redirect(url_for('db_admin'))
    else:
        return render_template('db_admin.html', logged_in=False, error="密码错误")

@app.route('/db_admin/logout')
def db_admin_logout():
    session.pop('logged_in', None)
    return redirect(url_for('db_admin'))

def get_db_connection(db_name):
    """安全地获取数据库连接"""
    db_path = os.path.join(DB_DIR, db_name)
    # 安全检查，确保路径仍然在预期的目录下
    if not os.path.abspath(db_path).startswith(os.path.abspath(DB_DIR)):
        return None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logger.error(f"连接数据库 {db_name} 失败: {e}")
        return None

@app.route('/db_admin/view/<db_name>')
def db_view(db_name):
    if not session.get('logged_in'):
        return redirect(url_for('db_admin'))

    conn = get_db_connection(db_name)
    if not conn:
        return "数据库连接失败或无效的数据库文件。", 404

    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()

    # 我们需要再次渲染db_admin.html，但这次要带上数据库和表的信息
    db_files = [f for f in os.listdir(DB_DIR) if f.endswith('.db')]
    return render_template('db_admin.html', 
                           logged_in=True, 
                           db_files=db_files, 
                           selected_db=db_name, 
                           tables=tables)

@app.route('/db_admin/view/<db_name>/<table_name>', methods=['GET', 'POST'])
def table_view(db_name, table_name):
    if not session.get('logged_in'):
        return redirect(url_for('db_admin'))

    conn = get_db_connection(db_name)
    if not conn:
        return "数据库连接失败或无效的数据库文件。", 404

    cursor = conn.cursor()
    
    # 安全检查：确保表名是合法的，防止SQL注入
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    if cursor.fetchone() is None:
        conn.close()
        return "表不存在。", 404

    # 获取表数据和列名
    search_query = request.form.get('search_query', '')
    search_column = request.form.get('search_column', '')

    query = f"SELECT * FROM {table_name}"
    params = []
    
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns_info = cursor.fetchall()
    columns = [col['name'] for col in columns_info]
    pk_column = next((col['name'] for col in columns_info if col['pk']), None)

    if request.method == 'POST' and search_query and search_column in columns:
        query += f" WHERE {search_column} LIKE ?"
        params.append(f"%{search_query}%")

    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    # 获取列名
    columns = [description[0] for description in cursor.description]
    
    # 获取该数据库中所有表的列表
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    
    conn.close()

    # 获取所有数据库文件的列表
    db_files = [f for f in os.listdir(DB_DIR) if f.endswith('.db')]

    return render_template('db_admin.html',
                           logged_in=True,
                           db_files=db_files,
                           selected_db=db_name,
                           tables=tables,
                           selected_table=table_name,
                           columns=columns,
                           rows=rows,
                           pk_column=pk_column,
                           search_query=search_query,
                           search_column=search_column)

@app.route('/db_admin/delete/<db_name>/<table_name>', methods=['POST'])
def delete_row(db_name, table_name):
    if not session.get('logged_in'):
        return redirect(url_for('db_admin'))

    conn = get_db_connection(db_name)
    if not conn:
        return "数据库连接失败或无效的数据库文件。", 404

    cursor = conn.cursor()
    
    # 获取主键
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns_info = cursor.fetchall()
    pk_column = None
    for col in columns_info:
        if col['pk']:
            pk_column = col['name']
            break
    
    if not pk_column:
        conn.close()
        return "无法找到主键，无法删除。", 400

    row_id = request.form.get('row_id')
    if not row_id:
        conn.close()
        return "未提供行ID。", 400

    try:
        query = f"DELETE FROM {table_name} WHERE {pk_column} = ?"
        cursor.execute(query, (row_id,))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"删除行失败: {e}")
        return f"删除失败: {e}", 500
    finally:
        conn.close()

    return redirect(url_for('table_view', db_name=db_name, table_name=table_name))

@app.route('/db_admin/update_cell', methods=['POST'])
def update_cell():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    data = request.json
    db_name = data.get('db_name')
    table_name = data.get('table_name')
    pk_val = data.get('pk')
    column = data.get('column')
    new_value = data.get('value')

    if not all([db_name, table_name, pk_val, column, new_value is not None]):
        return jsonify({'success': False, 'error': 'Missing data'}), 400

    conn = get_db_connection(db_name)
    if not conn:
        return jsonify({'success': False, 'error': 'Database connection failed'}), 500

    cursor = conn.cursor()

    # Security check: Validate table_name from a list of allowed tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    if cursor.fetchone() is None:
        conn.close()
        return jsonify({'success': False, 'error': 'Table not found'}), 404

    # Get column names and primary key
    cursor.execute(f"PRAGMA table_info('{table_name}')")
    columns_info = cursor.fetchall()
    columns = [col['name'] for col in columns_info]
    pk_column = next((col['name'] for col in columns_info if col['pk']), None)

    if not pk_column:
        conn.close()
        return jsonify({'success': False, 'error': 'Primary key not found'}), 400

    # Security check: Validate column name
    if column not in columns:
        conn.close()
        return jsonify({'success': False, 'error': 'Column not found'}), 404

    # Prevent updating the primary key itself
    if column == pk_column:
        conn.close()
        return jsonify({'success': False, 'error': 'Cannot update primary key'}), 400

    try:
        # Using f-strings here is safe because table_name and column have been validated
        query = f'UPDATE "{table_name}" SET "{column}" = ? WHERE "{pk_column}" = ?'
        cursor.execute(query, (new_value, pk_val))
        conn.commit()

        return jsonify({'success': True})
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"更新单元格失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/db_admin/add/<db_name>/<table_name>', methods=['POST'])
def add_row(db_name, table_name):
    if not session.get('logged_in'):
        return redirect(url_for('db_admin'))

    conn = get_db_connection(db_name)
    if not conn:
        return "数据库连接失败或无效的数据库文件。", 404

    cursor = conn.cursor()
    
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns_info = cursor.fetchall()
    columns = [col['name'] for col in columns_info]
    
    form_data = request.form.to_dict()
    values = []
    for col in columns:
        values.append(form_data.get(col))

    try:
        placeholders = ', '.join(['?'] * len(columns))
        query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
        cursor.execute(query, values)
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"添加行失败: {e}")
        return f"添加失败: {e}", 500
    finally:
        conn.close()

    return redirect(url_for('table_view', db_name=db_name, table_name=table_name))
