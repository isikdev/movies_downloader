import asyncio
import yt_dlp
from tqdm import tqdm
import os
import logging
from concurrent.futures import ThreadPoolExecutor
import re
from urllib.parse import urlparse, parse_qs
import subprocess
import sys
import certifi
import ssl

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('download.log'),
        logging.StreamHandler()
    ]
)

def setup_ssl_context():
    """Настраивает SSL контекст"""
    try:
        # Создаем SSL контекст
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        # Устанавливаем его как глобальный
        ssl._create_default_https_context = lambda: ssl_context
    except Exception as e:
        logging.warning(f"Не удалось настроить SSL контекст: {str(e)}")

def check_ffmpeg():
    """Проверяет наличие FFmpeg в системе"""
    try:
        subprocess.run(['ffmpeg', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except FileNotFoundError:
        return False

def install_ffmpeg():
    """Выводит инструкции по установке FFmpeg"""
    if sys.platform == 'win32':
        print("""
FFmpeg не установлен. Для установки FFmpeg на Windows:
1. Скачайте FFmpeg с https://www.gyan.dev/ffmpeg/builds/ (версия ffmpeg-git-full.7z)
2. Распакуйте архив
3. Добавьте путь к папке bin в переменную PATH
4. Перезапустите терминал

Или используйте Chocolatey:
choco install ffmpeg

Или Scoop:
scoop install ffmpeg
""")
    else:
        print("""
FFmpeg не установлен. Для установки FFmpeg:
Ubuntu/Debian: sudo apt-get install ffmpeg
MacOS: brew install ffmpeg
""")

def get_yt_dlp_opts(cookies_file=None):
    """Возвращает настройки yt-dlp с учетом cookies"""
    return {
        'format': 'best',  # Просто выбираем лучший доступный формат
        'outtmpl': 'downloads_180/%(title)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'cookiefile': cookies_file,
        'age_limit': 99,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'referer': 'https://www.youtube.com/',
        'nocheckcertificate': True,
        'no_check_certificate': True,
        'prefer_insecure': True,
        'legacy_server_connect': True,
        'socket_timeout': 30,
        'retries': 10,
        'extractor_args': {'youtubetab': {'skip': ['authcheck']}}
    }

def clean_url(url):
    """Очищает URL от лишних параметров"""
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    
    # Оставляем только нужные параметры
    cleaned_params = {k: v[0] for k, v in query_params.items() if k in ['list', 'v']}
    
    # Собираем новый URL
    if 'list' in cleaned_params:
        return f'https://www.youtube.com/playlist?list={cleaned_params["list"]}'
    return url

class ProgressHook:
    def __init__(self, video_title):
        self.pbar = None
        self.video_title = video_title
        self.downloaded_bytes = 0

    def __call__(self, d):
        if d['status'] == 'downloading':
            if self.pbar is None:
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                self.pbar = tqdm(
                    total=total,
                    unit='B',
                    unit_scale=True,
                    desc=f"Скачивание: {self.video_title}"
                )
            
            current = d.get('downloaded_bytes', 0)
            if current > self.downloaded_bytes:
                self.pbar.update(current - self.downloaded_bytes)
                self.downloaded_bytes = current
        
        elif d['status'] == 'finished':
            if self.pbar:
                self.pbar.close()
            logging.info(f"Завершено скачивание: {self.video_title}")

async def download_video(url, semaphore, cookies_file=None):
    async with semaphore:
        try:
            # Получаем базовые настройки только для получения информации
            info_opts = {
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,
                'cookiefile': cookies_file,
                'age_limit': 99,
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'referer': 'https://www.youtube.com/',
                'nocheckcertificate': True,
                'no_check_certificate': True,
                'prefer_insecure': True,
                'socket_timeout': 30,
                'retries': 10
            }
            
            # Сначала получаем информацию о видео без скачивания
            with yt_dlp.YoutubeDL(info_opts) as ydl:
                try:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        logging.error(f"Не удалось получить информацию о видео: {url}")
                        return None
                    
                    video_title = info.get('title', 'Неизвестное видео')
                    logging.info(f"Получена информация о видео: {video_title}")
                    
                    # Теперь настраиваем опции для скачивания с учетом доступных форматов
                    download_opts = {
                        'format': 'best',  # Просто выбираем лучший доступный формат
                        'outtmpl': 'downloads/%(title)s.%(ext)s',
                        'cookiefile': cookies_file,
                        'age_limit': 99,
                        'quiet': True,
                        'no_warnings': True,
                        'ignoreerrors': True,
                        'nocheckcertificate': True,
                        'progress_hooks': [ProgressHook(video_title)]
                    }
                    
                    logging.info(f"Начинаю скачивание: {video_title}")
                    
                    # Скачиваем видео
                    with yt_dlp.YoutubeDL(download_opts) as ydl_download:
                        with ThreadPoolExecutor(max_workers=1) as executor:
                            await asyncio.get_event_loop().run_in_executor(
                                executor, 
                                lambda: ydl_download.download([url])
                            )
                    
                    logging.info(f"Успешно скачано: {video_title}")
                    return video_title
                except Exception as e:
                    logging.error(f"Ошибка при скачивании {url}: {str(e)}")
                    return None
                
        except Exception as e:
            logging.error(f"Критическая ошибка при скачивании {url}: {str(e)}")
            return None

async def process_playlist(playlist_url, video_limit=None):
    """Обрабатывает плейлист YouTube и скачивает все видео
    
    Args:
        playlist_url (str): URL плейлиста
        video_limit (int, optional): Максимальное количество видео для скачивания
    """
    try:
        # Настраиваем SSL контекст
        setup_ssl_context()
        
        # Очищаем URL
        playlist_url = clean_url(playlist_url)
        logging.info(f"Обработка плейлиста: {playlist_url}")
        
        # Проверяем наличие cookies.txt
        cookies_file = None
        if os.path.exists('cookies.txt'):
            cookies_file = 'cookies.txt'
            logging.info("Используем cookies.txt для авторизации")
        else:
            logging.warning("Файл cookies.txt не найден. Доступ к закрытым видео может быть ограничен.")
        
        # Простая стратегия для получения информации о плейлисте
        playlist_opts = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'extract_flat': True,
            'cookiefile': cookies_file,
            'age_limit': 99,
            'nocheckcertificate': True,
            'extractor_args': {'youtubetab': {'skip': ['authcheck']}}
        }
        
        # Получаем информацию о плейлисте
        with yt_dlp.YoutubeDL(playlist_opts) as ydl:
            playlist_info = ydl.extract_info(playlist_url, download=False)
            
            if not playlist_info:
                logging.error("Не удалось получить информацию о плейлисте. Проверьте URL и доступ к плейлисту.")
                return []
            
            # Проверяем наличие видео в плейлисте
            entries = playlist_info.get('entries', [])
            if not entries:
                logging.error("Плейлист не содержит доступных видео. Проверьте настройки приватности плейлиста.")
                return []
            
            # Ограничиваем количество видео если указано
            if video_limit and isinstance(video_limit, int) and video_limit > 0:
                entries = entries[:video_limit]
                logging.info(f"Найдено видео в плейлисте: {len(playlist_info.get('entries', []))}, будет скачано: {len(entries)}")
            else:
                logging.info(f"Найдено {len(entries)} видео в плейлисте")
            
            # Создаем семафор для ограничения числа одновременных загрузок
            semaphore = asyncio.Semaphore(1)  # Загружаем не более 2-х видео одновременно
            
            # Создаем задачи для скачивания видео
            tasks = []
            for entry in entries:
                video_url = f"https://www.youtube.com/watch?v={entry['id']}"
                task = download_video(video_url, semaphore, cookies_file)
                tasks.append(task)
            
            # Запускаем задачи параллельно и ожидаем их завершения
            downloaded_videos = await asyncio.gather(*tasks)
            
            # Фильтруем None значения (неуспешные загрузки)
            successful_downloads = [video for video in downloaded_videos if video]
            
            logging.info(f"Успешно скачано {len(successful_downloads)} из {len(entries)} видео")
            
            return successful_downloads
            
    except Exception as e:
        logging.error(f"Ошибка при обработке плейлиста: {str(e)}")
        return []

def main():
    try:
        # Настраиваем логирование
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler()]
        )
        
        # Проверяем наличие FFmpeg
        if not check_ffmpeg():
            install_ffmpeg()
            raise SystemExit("Установите FFmpeg и перезапустите скрипт")
        
        # Создаем директорию для загрузок
        os.makedirs('downloads_180', exist_ok=True)
        
        # Запрашиваем URL плейлиста
        playlist_url = input("Введите URL плейлиста YouTube: ")
        if not playlist_url:
            raise ValueError("URL не может быть пустым")
        
        # Запрашиваем количество видео для скачивания
        video_limit = input("Введите количество видео для скачивания (нажмите Enter для загрузки всего плейлиста): ")
        
        # Преобразуем ввод в число если возможно
        if video_limit.strip():
            try:
                video_limit = int(video_limit)
                if video_limit <= 0:
                    print("Количество видео должно быть положительным числом. Будет загружен весь плейлист.")
                    video_limit = None
            except ValueError:
                print("Введено некорректное значение. Будет загружен весь плейлист.")
                video_limit = None
        else:
            video_limit = None
        
        # Запускаем скачивание
        asyncio.run(process_playlist(playlist_url, video_limit))
        
        print("\nЗагрузка завершена. Все видео сохранены в папке 'downloads_180'")
        
    except KeyboardInterrupt:
        print("\nСкачивание остановлено пользователем")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Произошла ошибка: {str(e)}")
        print("\nСоветы по устранению проблем:")
        print("1. Убедитесь, что URL плейлиста корректный")
        print("2. Проверьте наличие файла cookies.txt для доступа к закрытым видео")
        print("3. Убедитесь, что у вас стабильное интернет-соединение")
        print("4. Обновите yt-dlp командой: pip install --upgrade yt-dlp")

if __name__ == "__main__":
    main() 