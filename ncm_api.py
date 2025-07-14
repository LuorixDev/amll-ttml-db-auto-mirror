# -*- coding: utf-8 -*-

import logging
import requests

logger = logging.getLogger(__name__)

def fetch_song_details_from_api(song_ids):
    """从网易云API获取歌曲详情"""
    if not song_ids:
        return {}
    
    # 确保所有ID都是字符串
    song_ids_str = [str(sid) for sid in song_ids]
    
    url = f"https://music.163.com/api/song/detail?ids=[{','.join(song_ids_str)}]"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': 'https://music.163.com/',
        'Accept': 'application/json'
    }
    song_details_map = {}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data.get('code') == 200 and 'songs' in data:
            for song in data['songs']:
                song_id_str = str(song['id'])
                artists = ', '.join([artist['name'] for artist in song.get('ar', [])])
                album = song.get('al', {}).get('name', 'N/A')
                song_details_map[song_id_str] = {
                    'name': song.get('name', 'N/A'),
                    'artists': artists,
                    'album': album
                }
    except requests.RequestException as e:
        logger.error(f"请求歌曲详情API失败: {e}")
    except Exception as e:
        logger.error(f"处理歌曲详情API响应时出错: {e}")
        
    return song_details_map
