#!/usr/bin/env python3
import os, json
from datetime import datetime

# transcripts klasörünün yolu
TRANS_ROOT = 'transcripts'

def iso_date_from_file(path):
    # Dosyanın en son değiştirilme zamanını alıp YYYY-MM-DD formatına çevir
    ts = os.path.getmtime(path)
    return datetime.fromtimestamp(ts).date().isoformat()

def rebuild_instagram(profile_dir):
    videos, images = [], []
    for fname in os.listdir(profile_dir):
        path = os.path.join(profile_dir, fname)
        if not os.path.isfile(path): continue
        if fname.endswith('_transcript.txt'):
            pid = fname.replace('_transcript.txt','')
            videos.append({'id': pid, 'date': iso_date_from_file(path)})
        elif fname.endswith('_description.txt'):
            pid = fname.replace('_description.txt','')
            # eğer transcript yoksa, bu bir görsel açıklaması
            if not os.path.exists(os.path.join(profile_dir, pid+'_transcript.txt')):
                images.append({'id': pid, 'date': iso_date_from_file(path)})
    # tarih sırasına göre sırala
    videos.sort(key=lambda x: x['date'])
    images.sort(key=lambda x: x['date'])
    return {'videos': videos, 'images': images}

def rebuild_youtube(channel_dir):
    videos = []
    for fname in os.listdir(channel_dir):
        if fname.endswith('_transcript.txt'):
            vid = fname.replace('_transcript.txt','')
            videos.append({'id': vid, 'date': iso_date_from_file(os.path.join(channel_dir, fname))})
    videos.sort(key=lambda x: x['date'])
    return {'videos': videos}

def rebuild_x(user_dir):
    videos, images = [], []
    for fname in os.listdir(user_dir):
        path = os.path.join(user_dir, fname)
        if fname.endswith('_transcript.txt'):
            tid = fname.replace('_transcript.txt','')
            videos.append({'id': tid, 'date': iso_date_from_file(path)})
        elif fname.endswith('_tweet.txt'):
            tid = fname.replace('_tweet.txt','')
            # eğer transcript yoksa, bu sadece tweet metni
            if not os.path.exists(os.path.join(user_dir, tid+'_transcript.txt')):
                images.append({'id': tid, 'date': iso_date_from_file(path)})
    videos.sort(key=lambda x: x['date'])
    images.sort(key=lambda x: x['date'])
    return {'videos': videos, 'images': images}

def main():
    for platform in ('instagram','youtube','x'):
        base = os.path.join(TRANS_ROOT, platform)
        if not os.path.isdir(base): continue
        for user in os.listdir(base):
            user_dir = os.path.join(base, user)
            if not os.path.isdir(user_dir): continue

            if platform == 'instagram':
                idx = rebuild_instagram(user_dir)
            elif platform == 'youtube':
                idx = rebuild_youtube(user_dir)
            else:
                idx = rebuild_x(user_dir)

            idx_file = os.path.join(user_dir, 'index.json')
            with open(idx_file, 'w', encoding='utf-8') as f:
                json.dump(idx, f, ensure_ascii=False, indent=2)
            print(f"[i] {platform}/{user}/index.json yeniden oluşturuldu.")

if __name__ == '__main__':
    main()
