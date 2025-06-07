#!/usr/bin/env python3
import os
import sys
import json
import http.cookiejar as cj
import instaloader
from faster_whisper import WhisperModel
import requests
from yt_dlp import YoutubeDL
import snscrape.modules.twitter as sntwitter
from git import Repo
import torch
from datetime import datetime
import time
import random

# ---------- AYARLAR ----------
INSTAGRAM_PROFILES = 'anahtarparti', 'anahtarpartidijital', 'yavuzagiralioglu', 'yadijitalofis'     # ← Instagram profil kullanıcı adlarını gir
YOUTUBE_USERS      = 'UCrJPM4VxMojTRwd3VpoBFXA', 'YavuzAgiralioglu', 'UCMOVQXyA5ErrZCKFI8g48wA'  # ← YouTube kullanıcı adlarını gir
X_USERS            = 'APartiDijital', 'anahtarparti', 'yavuzagiraliog', 'YAdijitalofis'            # ← X (Twitter) kullanıcı adlarını gir
COOKIE_FILE        = 'cookies.txt'
TRANS_ROOT         = 'transcripts'


def ensure(path):
    os.makedirs(path, exist_ok=True)

# —————————————————————————————
# 1) INSTAGRAM: Instaloader + Cookie Yükleme
# —————————————————————————————
L = instaloader.Instaloader()
if not os.path.exists(COOKIE_FILE):
    print(f"[!] '{COOKIE_FILE}' bulunamadı. Lütfen tarayıcıdan dışa aktarın.")
    sys.exit(1)
jar = cj.MozillaCookieJar(COOKIE_FILE)
jar.load(ignore_discard=True, ignore_expires=True)
L.context._session.cookies = jar
print("[i] Instagram çerezleri yüklendi.")

# —————————————————————————————
# 2) faster-whisper Modelini Yükle (GPU veya CPU)
# —————————————————————————————
device = "cuda" if torch.cuda.is_available() else "cpu"
compute_type = "float16" if device == "cuda" else "int8"
model = WhisperModel("base", device=device, compute_type=compute_type)
print(f"[i] Faster-Whisper modeli yüklendi. CUDA kullanılıyor: {torch.cuda.is_available()}")

# —————————————————————————————
# 3) Git Repo Referansı
# —————————————————————————————
try:
    repo = Repo(os.getcwd())
except:
    repo = None
changed = False

# —————————————————————————————
# 4) INSTAGRAM Profillerini İşle (Skip + Rate-Limit)
#    → Her post’u tek tek kontrol ediyoruz.
# —————————————————————————————
for prof in INSTAGRAM_PROFILES:
    out_dir = os.path.join(TRANS_ROOT, 'instagram', prof)
    ensure(out_dir)

    # 4.1) Önceden indirilmiş video ID’lerini bul (_transcript.txt’lerden)
    processed_video_ids = set()
    for fname in os.listdir(out_dir):
        if fname.endswith('_transcript.txt'):
            processed_video_ids.add(fname.replace('_transcript.txt', ''))

    # 4.2) Önceden indirilmiş görsel post ID’lerini bul (_description.txt’lerden, video olmayan)
    processed_image_ids = set()
    for fname in os.listdir(out_dir):
        if fname.endswith('_description.txt'):
            pid = fname.replace('_description.txt', '')
            if pid not in processed_video_ids:
                processed_image_ids.add(pid)

    try:
        profile = instaloader.Profile.from_username(L.context, prof)
        posts = profile.get_posts()
    except Exception as e:
        print(f"[!] Instagram profili ({prof}) yüklenirken hata: {e}")
        continue

    videos_meta = []
    images_meta = []

    for post in posts:
        post_id = post.shortcode if post.is_video else post.mediaid
        post_date = post.date_utc.date().isoformat()

        # 4.3) Eğer bu ID önceden işlenmişse, sadece skip et, döngüye devam et
        if post.is_video and post_id in processed_video_ids:
            print(f"[i] Instagram: {prof} → video '{post_id}' zaten işlenmiş, atlanıyor.")
            break
        if (not post.is_video) and (post_id in processed_image_ids):
            print(f"[i] Instagram: {prof} → görsel '{post_id}' zaten işlenmiş, atlanıyor.")
            continue

        # 4.4) Açıklama dosyasını kaydet
        desc_path = os.path.join(out_dir, f"{post_id}_description.txt")
        if not os.path.exists(desc_path):
            caption = post.caption or ""
            with open(desc_path, "w", encoding="utf-8") as f_desc:
                f_desc.write(caption)
            if repo:
                repo.index.add([desc_path])
            changed = True

        if post.is_video:
            # 4.5) Video metadata
            videos_meta.append({"id": post_id, "date": post_date})

            # 4.6) Transkript indir + transkripte et
            txt_path = os.path.join(out_dir, f"{post_id}_transcript.txt")
            if not os.path.exists(txt_path):
                print(f"[i] Instagram’dan video indiriliyor: {post_id}")
                try:
                    resp = L.context._session.get(post.video_url, stream=True)
                    resp.raise_for_status()
                    tmp_video = f"{post_id}.mp4"
                    with open(tmp_video, 'wb') as vf:
                        for chunk in resp.iter_content(8192):
                            vf.write(chunk)
                except Exception as e:
                    print(f"[!] Instagram indirilemedi ({post_id}): {e}")
                    if os.path.exists(tmp_video):
                        os.remove(tmp_video)
                    t_wait = random.uniform(5, 15)
                    print(f"[i] {post_id} işlenemedi, {t_wait:.1f}s bekleniyor...")
                    time.sleep(t_wait)
                    continue

                print(f"[i] Transkript (faster-whisper): {post_id}")
                try:
                    segments, _ = model.transcribe(tmp_video, beam_size=5)
                    # Segmentleri birleştirirken basit tekrar kontrolü
                    combined = []
                    prev_text = ""
                    for seg in segments:
                        text = seg.text.strip()
                        if prev_text and text in prev_text:
                            continue
                        combined.append(text)
                        prev_text = text
                    full_text = " ".join([seg for seg in combined if seg])
                    with open(txt_path, "w", encoding="utf-8") as f_txt:
                        f_txt.write(full_text)
                except Exception as e:
                    print(f"[!] Transkript hatası ({post_id}): {e}")
                finally:
                    if os.path.exists(tmp_video):
                        os.remove(tmp_video)

                if repo:
                    repo.index.add([txt_path])
                changed = True

        else:
            # 4.7) Görsel metadata
            images_meta.append({"id": post_id, "date": post_date})

        # 4.8) Rate-Limit: 5–15s uyku
        t_sleep = random.uniform(5, 15)
        print(f"[i] Instagram post {post_id} işlendi. {t_sleep:.1f}s bekleniyor...")
        time.sleep(t_sleep)

    # 4.9) index.json yaz
    idx = {
        "videos": sorted(videos_meta, key=lambda x: x["date"]),
        "images": sorted(images_meta, key=lambda x: x["date"])
    }
    idx_file = os.path.join(out_dir, 'index.json')
    with open(idx_file, "w", encoding="utf-8") as idxf:
        json.dump(idx, idxf, ensure_ascii=False, indent=2)
    if repo:
        repo.index.add([idx_file])
    changed = True

# —————————————————————————————
# 5) YOUTUBE: Sadece Audio İndir → Transkript (Skip + Rate-Limit)
# —————————————————————————————
ydl_list_opts = {
    'extract_flat': 'in_playlist',
    'skip_download': True,
    'quiet': True
}
# Audio-only indirme: mümkün olan en küçük dosya
ydl_dl_opts = {
    'format': 'bestaudio/best',
    'outtmpl': '%(id)s.%(ext)s',
    'quiet': True
}

with YoutubeDL(ydl_list_opts) as ydl_list:
    for user in YOUTUBE_USERS:
        out_dir = os.path.join(TRANS_ROOT, 'youtube', user)
        ensure(out_dir)

        # 5.1) Önceden işlenmiş video ID’leri (_transcript.txt)
        processed_youtube_ids = set()
        for fname in os.listdir(out_dir):
            if fname.endswith('_transcript.txt'):
                processed_youtube_ids.add(fname.replace('_transcript.txt', ''))

        # 5.2) “user”ın UserName mi yoksa ChannelID mi olduğunu kontrol et
        if user.startswith("UC"):
            channel_url = f"https://www.youtube.com/channel/{user}/videos"
        else:
            channel_url = f"https://www.youtube.com/user/{user}/videos"

        try:
            info = ydl_list.extract_info(channel_url, download=False)
        except Exception as e:
            print(f"[!] YouTube kanalı ({user}) yüklenirken hata: {e}")
            continue

        videos_meta = []

        for entry in info.get('entries', []):
            vid = entry.get('id')
            if not vid:
                continue

            # 5.3) Eğer işlenmişse, sadece skip et, döngüye devam et
            if vid in processed_youtube_ids:
                print(f"[i] YouTube: {user} → '{vid}' zaten var, atlanıyor.")
                continue

            # 5.4) Tarihi al (YYYYMMDD → YYYY-MM-DD)
            upload_raw = entry.get('upload_date') or ""
            if upload_raw and len(upload_raw) == 8:
                vid_date = f"{upload_raw[0:4]}-{upload_raw[4:6]}-{upload_raw[6:8]}"
            else:
                ts = entry.get('release_timestamp') or entry.get('timestamp') or None
                if ts:
                    vid_date = datetime.utcfromtimestamp(ts).date().isoformat()
                else:
                    vid_date = ""

            # 5.5) Açıklama dosyası
            desc_path = os.path.join(out_dir, f"{vid}_description.txt")
            if not os.path.exists(desc_path):
                description = entry.get('description', "") or ""
                with open(desc_path, "w", encoding="utf-8") as f_desc:
                    f_desc.write(description)
                if repo:
                    repo.index.add([desc_path])
                changed = True

            # 5.6) Metadata
            videos_meta.append({"id": vid, "date": vid_date})

            # 5.7) Audio indir + faster-whisper ile transkript al
            txt_path = os.path.join(out_dir, f"{vid}_transcript.txt")
            if not os.path.exists(txt_path):
                print(f"[i] YouTube’dan audio indiriliyor: {vid}")
                try:
                    with YoutubeDL(ydl_dl_opts) as ydl_dl:
                        # extract_info döndürürken download=True ile dosya indirilir
                        info_dict = ydl_dl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=True)
                        tmp_audio = ydl_dl.prepare_filename(info_dict)
                except Exception as e:
                    print(f"[!] YouTube audio indirilemedi ({vid}): {e}")
                    t_wait = random.uniform(5, 15)
                    print(f"[i] Bekleniyor {t_wait:.1f}s...")
                    time.sleep(t_wait)
                    continue

                print(f"[i] Transkript (faster-whisper): {vid}")
                try:
                    segments, _ = model.transcribe(tmp_audio, beam_size=5)
                    # Tekrarlayan parçaları azaltmak için kontrollü birleştirme
                    combined = []
                    prev_text = ""
                    for seg in segments:
                        text = seg.text.strip()
                        if prev_text and text in prev_text:
                            continue
                        combined.append(text)
                        prev_text = text
                    full_text = " ".join([seg for seg in combined if seg])
                    with open(txt_path, "w", encoding="utf-8") as f_txt:
                        f_txt.write(full_text)
                except Exception as e:
                    print(f"[!] Transkript hatası ({vid}): {e}")
                finally:
                    if os.path.exists(tmp_audio):
                        os.remove(tmp_audio)

                if repo:
                    repo.index.add([txt_path])
                changed = True

            # 5.8) Rate-Limit: 5–15 saniye rastgele uyku
            t_sleep = random.uniform(5, 15)
            print(f"[i] YouTube video {vid} işlendi. {t_sleep:.1f}s bekleniyor...")
            time.sleep(t_sleep)

        # 5.9) index.json yaz
        idx = {"videos": sorted(videos_meta, key=lambda x: x["date"])}
        idx_file = os.path.join(out_dir, 'index.json')
        with open(idx_file, "w", encoding="utf-8") as idxf:
            json.dump(idx, idxf, ensure_ascii=False, indent=2)
        if repo:
            repo.index.add([idx_file])
        changed = True

# —————————————————————————————
# 6) X (TWITTER): Tweet’lerdeki Video ve Görseller (Skip + Rate-Limit)
#    → Her tweet’i tek tek kontrol ediyoruz.
# —————————————————————————————
for user in X_USERS:
    out_dir = os.path.join(TRANS_ROOT, 'x', user)
    ensure(out_dir)

    # 6.1) Önceden indirilmiş video ID’leri (_transcript.txt’lerden)
    processed_twitter_vid_ids = set()
    for fname in os.listdir(out_dir):
        if fname.endswith('_transcript.txt'):
            processed_twitter_vid_ids.add(fname.replace('_transcript.txt', ''))

    # 6.2) Önceden indirilmiş görsel tweet ID’leri (_tweet.txt’lerden, video olmayan)
    processed_twitter_img_ids = set()
    for fname in os.listdir(out_dir):
        if fname.endswith('_tweet.txt'):
            tid = fname.replace('_tweet.txt', '')
            if tid not in processed_twitter_vid_ids:
                processed_twitter_img_ids.add(tid)

    videos_meta = []
    images_meta = []

    scraper = sntwitter.TwitterUserScraper(user)
    for tweet in scraper.get_items():
        tid = str(tweet.id)
        tweet_date = tweet.date.date().isoformat()

        # 6.3) Eğer video ID zaten işlenmişse / görsel tweet zaten işlenmişse, skip et
        if tid in processed_twitter_vid_ids:
            print(f"[i] X (Twitter): {user} → video '{tid}' zaten işlenmiş, atlanıyor.")
            continue
        if (tid in processed_twitter_img_ids) and not getattr(tweet, 'media', None):
            print(f"[i] X (Twitter): {user} → görsel tweet '{tid}' zaten işlenmiş, atlanıyor.")
            continue

        # 6.4) Tweet metnini kaydet
        tweet_txt = os.path.join(out_dir, f"{tid}_tweet.txt")
        if not os.path.exists(tweet_txt):
            content = tweet.rawContent if hasattr(tweet, 'rawContent') else (tweet.content if hasattr(tweet, 'content') else "")
            with open(tweet_txt, "w", encoding="utf-8") as f_desc:
                f_desc.write(content or "")
            if repo:
                repo.index.add([tweet_txt])
            changed = True

        # 6.5) Medya varsa
        if getattr(tweet, 'media', None):
            for m in tweet.media:
                if getattr(m, 'type', '') == 'video':
                    videos_meta.append({"id": tid, "date": tweet_date})

                    txt_path = os.path.join(out_dir, f"{tid}_transcript.txt")
                    if not os.path.exists(txt_path):
                        url = f"https://twitter.com/{user}/status/{tid}"
                        print(f"[i] Tweet videosu indiriliyor: {tid}")
                        try:
                            with YoutubeDL({'format': 'bestaudio/best', 'outtmpl': '%(id)s.%(ext)s', 'quiet': True}) as ydl3:
                                info3 = ydl3.extract_info(url, download=True)
                                filename = ydl3.prepare_filename(info3)
                        except Exception as e:
                            print(f"[!] Tweet indirilemedi ({tid}): {e}")
                            t_wait = random.uniform(5, 15)
                            print(f"[i] Bekleniyor {t_wait:.1f}s...")
                            time.sleep(t_wait)
                            continue

                        print(f"[i] Tweet transkripti (faster-whisper): {tid}")
                        try:
                            segments, _ = model.transcribe(filename, beam_size=5)
                            # Tekrarlayan parçaları azaltmak için basit kontrol
                            combined = []
                            prev_text = ""
                            for seg in segments:
                                text = seg.text.strip()
                                if prev_text and text in prev_text:
                                    continue
                                combined.append(text)
                                prev_text = text
                            full_text = " ".join([seg for seg in combined if seg])

                            with open(txt_path, "w", encoding="utf-8") as f_txt:
                                f_txt.write(full_text)
                        except Exception as e:
                            print(f"[!] Tweet transkript hatası ({tid}): {e}")
                        finally:
                            if os.path.exists(filename):
                                os.remove(filename)

                        if repo:
                            repo.index.add([txt_path])
                        changed = True

                        # 6.6) Rate-Limit: Tweet video işlendikten sonra 5–15s uyku
                        t_sleep = random.uniform(5, 15)
                        print(f"[i] X video {tid} işlendi. {t_sleep:.1f}s bekleniyor...")
                        time.sleep(t_sleep)

                elif getattr(m, 'type', '') == 'photo':
                    images_meta.append({"id": tid, "date": tweet_date})
                    # 6.7) Rate-Limit: Görsel tweet işlendikten sonra 3–7s uyku
                    t_sleep = random.uniform(3, 7)
                    print(f"[i] X görsel tweet {tid} işlendi. {t_sleep:.1f}s bekleniyor...")
                    time.sleep(t_sleep)

    # 6.8) index.json yaz
    idx = {
        "videos": sorted(videos_meta, key=lambda x: x["date"]),
        "images": sorted(images_meta, key=lambda x: x["date"])
    }
    idx_file = os.path.join(out_dir, 'index.json')
    with open(idx_file, "w", encoding="utf-8") as idxf:
        json.dump(idx, idxf, ensure_ascii=False, indent=2)
    if repo:
        repo.index.add([idx_file])
    changed = True

# —————————————————————————————
# 7) Git Commit & Push
# —————————————————————————————
if changed and repo:
    repo.index.commit("🔄 YouTube: audio-only indirme ve transkript eklendi")
    try:
        repo.remote(name='origin').push()
        print("[i] Değişiklikler GitHub’a pushtandı.")
    except Exception as e:
        print(f"[!] GitHub’a push hatası: {e}")
else:
    print("[i] Yeni içerik yok veya Git repo yok; atlanıyor.")
