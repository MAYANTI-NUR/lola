import requests
import subprocess
import json
import os
import sys
from tqdm import tqdm
import uuid
import re

# --- KONFIGURASI API ---
TRANSLATE_API_URL = "https://api.gungrate.id/subtranslate3.php"
TRANSLATE_API_KEY = "secret1234" # Ganti dengan API key Anda jika ada

def check_dependencies():
    """Memeriksa semua dependensi yang diperlukan."""
    try:
        subprocess.run(['ffmpeg', '-version'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ ERROR: FFmpeg tidak ditemukan. Silakan install dari: https://ffmpeg.org/download.html")
        return False
    try:
        subprocess.run(['rclone', 'version'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ ERROR: Rclone tidak ditemukan atau belum dikonfigurasi. Silakan install dari: https://rclone.org/downloads/")
        return False
    
    print("✅ Semua dependensi (FFmpeg, Rclone) ditemukan.")
    return True

def download_from_direct_url(url, local_filename):
    """Mengunduh file dari direct link dengan progress bar."""
    try:
        print(f"📥 Memulai unduhan video (Direct): {url}")
        headers = {'User-Agent': 'Mozilla/5.0','Referer': url}
        with requests.get(url, stream=True, headers=headers, allow_redirects=True) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            with open(local_filename, 'wb') as f, tqdm(desc=local_filename, total=total_size, unit='iB', unit_scale=True, unit_divisor=1024) as bar:
                for chunk in r.iter_content(chunk_size=8192):
                    size = f.write(chunk)
                    bar.update(size)
        print(f"✅ Unduhan video selesai: {local_filename}")
        return local_filename
    except requests.exceptions.RequestException as e:
        print(f"❌ Gagal mengunduh file video: {e}")
        return None

def download_from_gdrive_by_name(filename, local_filename):
    """Mengunduh file dari Google Drive berdasarkan nama filenya."""
    print(f"📥 Mencari dan mengunduh '{filename}' dari Google Drive via rclone...")
    command = ['rclone', 'copy', f'gdrive:{filename}', '.', '--progress']
    try:
        print(f"🔧 Menjalankan command: {' '.join(command)}")
        subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
        if os.path.exists(filename):
            os.rename(filename, local_filename)
            print(f"✅ Unduhan '{filename}' selesai dan disimpan sebagai '{local_filename}'")
            return local_filename
        else:
            print(f"❌ Unduhan selesai, tapi file '{filename}' tidak ditemukan secara lokal.")
            return None
    except subprocess.CalledProcessError as e:
        error_message = e.stderr
        print(f"❌ Gagal mengunduh dengan rclone.\n   Error: {error_message.strip()}")
        if "Source not found" in error_message:
             print("💡 PASTIKAN nama file yang Anda masukkan sudah benar dan ada di GDrive.")
        return None
    except FileNotFoundError:
        print("❌ Perintah rclone tidak ditemukan.")
        return None

def download_subtitle(url):
    """Mengunduh file subtitle dari URL."""
    print(f"📥 Mengunduh subtitle dari: {url}")
    try:
        r = requests.get(url, allow_redirects=True, timeout=15)
        r.raise_for_status()
        random_name = str(uuid.uuid4()).split('-')[0]
        original_filename = url.split('/')[-1].split('?')[0]
        _, ext = os.path.splitext(original_filename)
        if not ext: ext = ".srt"
        local_filename = f"{random_name}_external{ext}"
        with open(local_filename, 'wb') as f:
            f.write(r.content)
        print(f"✅ Subtitle eksternal berhasil disimpan ke: {local_filename}")
        return local_filename
    except requests.exceptions.RequestException as e:
        print(f"❌ Gagal mengunduh subtitle: {e}")
        return None

def list_audio_tracks(video_path):
    """Mendapatkan daftar track audio dari file video menggunakan ffprobe."""
    print(f"\n🔍 Menganalisis track audio di dalam '{video_path}'...")
    command = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', '-select_streams', 'a', video_path]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
        streams = json.loads(result.stdout).get('streams', [])
        audio_tracks = []
        for stream in streams:
            lang = stream.get('tags', {}).get('language', 'N/A')
            title = stream.get('tags', {}).get('title', '')
            codec_name = stream.get('codec_name', 'N/A')
            display_title = f"Bahasa: {lang}, Codec: {codec_name}"
            if title:
                display_title += f", Judul: {title}"
            audio_tracks.append({'stream_index': stream['index'], 'display_title': display_title})
        return audio_tracks
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
        print(f"❌ Gagal menganalisis track audio: {e}")
        return []

def list_subtitles(video_path):
    """Mendapatkan daftar subtitle dari file video menggunakan ffprobe."""
    print(f"\n🔍 Menganalisis subtitle di dalam '{video_path}'...")
    command = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', '-select_streams', 's', video_path]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
        streams = json.loads(result.stdout).get('streams', [])
        subtitles = []
        for subtitle_idx, stream in enumerate(streams):
            lang = stream.get('tags', {}).get('language', 'N/A')
            title = stream.get('tags', {}).get('title', 'Tanpa Judul')
            subtitles.append({'internal_index': subtitle_idx, 'stream_index': stream['index'], 'language': lang, 'title': title})
        return subtitles
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
        print(f"❌ Gagal menganalisis subtitle: {e}")
        return []

def extract_subtitle(video_path, stream_index, output_path):
    """Mengekstrak satu stream subtitle ke file .srt."""
    print(f" Extracting subtitle stream index {stream_index}...")
    command = ['ffmpeg', '-i', video_path, '-map', f'0:{stream_index}', '-c:s', 'srt', '-y', output_path]
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        print(f"✅ Subtitle berhasil diekstrak ke: {output_path}")
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"❌ Gagal mengekstrak subtitle. Error: {e.stderr.decode()}")
        return None

def translate_subtitle(subtitle_file_path, from_lang, to_lang):
    """Mengirim file subtitle ke API dan menyimpan hasilnya."""
    print(f"🌐 Menerjemahkan subtitle dari '{from_lang}' ke '{to_lang}'...")
    random_name = str(uuid.uuid4()).split('-')[0]
    output_filename = f"{random_name}_translated_{to_lang}.srt"
    payload = {'apikey': TRANSLATE_API_KEY, 'from': from_lang, 'to': to_lang}
    try:
        with open(subtitle_file_path, 'rb') as f:
            files = {'subtitle_content': (os.path.basename(subtitle_file_path), f)}
            response = requests.post(TRANSLATE_API_URL, data=payload, files=files)
            response.raise_for_status()
        with open(output_filename, 'wb') as f:
            f.write(response.content)
        print(f"✅ Terjemahan berhasil disimpan ke: {output_filename}")
        return output_filename
    except (requests.exceptions.RequestException, IOError) as e:
        print(f"❌ Gagal menerjemahkan subtitle: {e}")
        return None

def hardsub_video(input_path, output_path, subtitle_source, audio_stream_index):
    """Melakukan hardsub dengan watermark menggunakan track audio yang dipilih."""
    print(f"\n🔥 Memulai proses hardsub...")
    print(f"   Input: {input_path}")
    print(f"   Output: {output_path}")
    print(f"   Audio Stream Index: {audio_stream_index}")
    print(f"   Subtitle Source: {subtitle_source}")

    watermark_text = "http\\://bioskop.stream"
    watermark_filter = f"drawtext=text='{watermark_text}':font='Sansation':x=10:y=H-th-10:fontsize=20:fontcolor=white@0.7:enable='if(gte(t,600),lt(mod(t,600),120))'"
    subtitle_style = "FontName=Noto Sans,FontSize=20,PrimaryColour=&H00FFFFFF,BorderStyle=1,Outline=1,Shadow=1,BackColour=&H00000000,Alignment=2,MarginV=25"
    
    if isinstance(subtitle_source, int):
        subtitle_filter = f"subtitles='{input_path}':si={subtitle_source}:force_style='{subtitle_style}'"
    else:
        clean_path = subtitle_source.replace('\\', '/').replace(':', '\\:')
        subtitle_filter = f"subtitles='{clean_path}':force_style='{subtitle_style}'"

    video_filter = f"{subtitle_filter},{watermark_filter}"
    
    command = [
        'ffmpeg', '-i', input_path,
        '-vf', video_filter,
        '-map', '0:v:0',
        '-map', f'0:{audio_stream_index}',
        '-c:v', 'libx264', '-preset', 'faster', '-crf', '30',
        '-profile:v', 'main', '-level', '4.1', '-movflags', '+faststart',
        '-c:a', 'aac', '-b:a', '128k', '-ac', '2',
        '-threads', '0', '-y', output_path
    ]
    
    print(f"🔧 Menjalankan command: {' '.join(command)}")
    try:
        subprocess.run(command, check=True)
        print(f"\n🎉 Sukses! Video telah di-hardsub: {output_path}")
        print(f"\n🚀 Mengunggah '{output_path}' dengan rclone...")
        rclone_destination = "file:file/"
        rclone_command = ['rclone', 'copy', output_path, rclone_destination, '--progress']
        subprocess.run(rclone_command, check=True)
        print(f"✅ Upload rclone ke '{rclone_destination}' berhasil.")
        return output_path
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"❌ Proses hardsub atau upload gagal: {e}")
        return None

def process_file(video_path):
    """Fungsi terpisah untuk memproses file setelah didapatkan."""
    # --- LANGKAH 1: PILIH AUDIO ---
    audio_tracks = list_audio_tracks(video_path)
    selected_audio_stream_index = None

    if not audio_tracks:
        print("❌ Tidak ada track audio yang ditemukan di dalam video. Proses tidak dapat dilanjutkan.")
        return []
    
    if len(audio_tracks) == 1:
        selected_audio_stream_index = audio_tracks[0]['stream_index']
        print(f"🎵 Hanya ada 1 track audio, otomatis memilih: {audio_tracks[0]['display_title']}")
    else:
        print("\n🎵 Silakan pilih track audio:")
        for i, track in enumerate(audio_tracks):
            print(f"   [{i+1}] - {track['display_title']}")
        
        while True:
            try:
                choice = int(input(f"Pilih nomor audio (1-{len(audio_tracks)}): "))
                if 1 <= choice <= len(audio_tracks):
                    selected_audio_stream_index = audio_tracks[choice - 1]['stream_index']
                    print(f"Anda memilih audio: {audio_tracks[choice - 1]['display_title']}")
                    break
                else:
                    print("Pilihan tidak valid.")
            except ValueError:
                print("Input tidak valid. Harap masukkan angka.")

    # --- LANGKAH 2: PILIH SUBTITLE ---
    subtitles = list_subtitles(video_path)
    subtitle_source_for_ffmpeg = None
    temp_files_to_clean = []

    print("\n📜 Silakan pilih sumber subtitle:")
    translate_option_num, external_sub_option_num = -1, -1

    if subtitles:
        for i, sub in enumerate(subtitles):
            print(f"   [{i+1}] - [Internal] Judul: {sub['title']} | Bahasa: {sub['language']}")
        translate_option_num = len(subtitles) + 1
        external_sub_option_num = len(subtitles) + 2
        print(f"   [{translate_option_num}] - 🌐 Terjemahkan Subtitle Internal")
        print(f"   [{external_sub_option_num}] - 📥 Gunakan Subtitle dari URL Eksternal")
        max_choice = external_sub_option_num
    else:
        print("😕 Tidak ada subtitle internal yang ditemukan.")
        external_sub_option_num = 1
        print(f"   [{external_sub_option_num}] - 📥 Gunakan Subtitle dari URL Eksternal")
        max_choice = external_sub_option_num
    
    sub_choice_num = -1
    while True:
        try:
            choice_input = input(f"\nPilih nomor opsi subtitle (1-{max_choice}): ")
            sub_choice_num = int(choice_input)
            if 1 <= sub_choice_num <= max_choice: break
            else: print("Pilihan tidak valid.")
        except ValueError:
            print("Input tidak valid. Harap masukkan angka.")

    if subtitles and sub_choice_num == translate_option_num:
        sub_to_translate_choice = -1
        while True:
            try:
                choice_input = input(f"Pilih nomor subtitle internal untuk diterjemahkan (1-{len(subtitles)}): ")
                sub_to_translate_choice = int(choice_input)
                if 1 <= sub_to_translate_choice <= len(subtitles):
                    break
                else:
                    print("Pilihan tidak valid.")
            except ValueError:
                print("Input tidak valid.")
        
        selected_sub = subtitles[sub_to_translate_choice - 1]
        print(f"Anda memilih untuk menerjemahkan subtitle: {selected_sub['title']} ({selected_sub['language']})")
        random_name = str(uuid.uuid4()).split('-')[0]
        original_sub_path = f"{random_name}_original.srt"
        temp_files_to_clean.append(original_sub_path)
        extracted_path = extract_subtitle(video_path, selected_sub['stream_index'], original_sub_path)
        if extracted_path:
            translated_sub_path = translate_subtitle(extracted_path, 'auto', 'id')
            if translated_sub_path:
                subtitle_source_for_ffmpeg = translated_sub_path
                temp_files_to_clean.append(translated_sub_path)

    elif sub_choice_num == external_sub_option_num:
        sub_url = input("\n🔗 Masukkan URL file subtitle: ")
        if sub_url:
            downloaded_sub_path = download_subtitle(sub_url)
            if downloaded_sub_path:
                subtitle_source_for_ffmpeg = downloaded_sub_path
                temp_files_to_clean.append(downloaded_sub_path)
    
    else: 
        selected_sub = subtitles[sub_choice_num - 1]
        subtitle_source_for_ffmpeg = selected_sub['internal_index']
        print(f"\nAnda memilih subtitle internal: [{sub_choice_num}] - {selected_sub['title']}")

    if subtitle_source_for_ffmpeg is None:
        print("❌ Gagal menyiapkan subtitle.")
    else:
        output_filename = input("\n✏️  Masukkan nama file output (e.g., movie.mp4): ")
        if output_filename:
            hardsub_video(video_path, output_filename, subtitle_source_for_ffmpeg, selected_audio_stream_index)

    return temp_files_to_clean

def main():
    """Fungsi utama untuk menjalankan seluruh proses."""
    if not check_dependencies():
        sys.exit(1)

    print("\nSilakan pilih sumber video:")
    print("  [1] URL Direct (MP4/MKV)")
    print("  [2] Google Drive (dari nama file)")
    print("  [3] File Lokal")
    
    choice = input("Pilih nomor (1/2/3): ")
    
    video_path = None
    downloaded_video_filename = "downloaded_video.mkv"

    if choice == '1':
        url = input("\n🔗 Masukkan URL video direct: ")
        video_path = download_from_direct_url(url, downloaded_video_filename)
    elif choice == '2':
        filename = input("\n📄 Masukkan nama file yang ada di Google Drive: ")
        video_path = download_from_gdrive_by_name(filename, downloaded_video_filename)
    elif choice == '3':
        local_file = input("\n🎬 Masukkan nama file video LOKAL: ")
        if os.path.exists(local_file):
            video_path = local_file
        else:
            print(f"❌ ERROR: File '{local_file}' tidak ditemukan.")
    else:
        print("❌ Pilihan tidak valid.")
        return

    if not video_path:
        print("\nGagal mendapatkan file video. Proses dihentikan.")
        return
    
    temp_files_to_clean = process_file(video_path)

    if choice in ['1', '2'] and os.path.exists(video_path):
        delete_original = input(f"\nApakah Anda ingin menghapus file unduhan asli '{video_path}'? (y/n): ").lower()
        if delete_original == 'y':
            os.remove(video_path)
            print(f"🗑️ File unduhan '{video_path}' telah dihapus.")

    if temp_files_to_clean:
        print("\n🧹 Membersihkan file sementara...")
        for f in temp_files_to_clean:
            if os.path.exists(f):
                os.remove(f)
                print(f"   - File '{f}' dihapus.")

if __name__ == "__main__":
    main()
