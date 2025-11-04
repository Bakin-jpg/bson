import asyncio
from playwright.async_api import async_playwright
import json
from urllib.parse import urljoin, urlparse, parse_qs, urlencode
import re
import os
import time

async def scrape_kickass_anime():
    """
    Scrape data anime lengkap dari kickass-anime.ru dengan struktur JSON yang rapi.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()

        try:
            base_url = "https://kickass-anime.ru/"
            await page.goto(base_url, timeout=90000, wait_until="domcontentloaded")
            print("Berhasil membuka halaman utama.")

            await page.wait_for_selector(".latest-update .row.mt-0 .show-item", timeout=60000)
            print("Bagian 'Latest Update' ditemukan.")

            anime_items = await page.query_selector_all(".latest-update .row.mt-0 .show-item")
            print(f"Menemukan {len(anime_items)} item anime terbaru.")

            # Load existing data jika ada
            existing_data = []
            if os.path.exists('anime_data.json'):
                try:
                    with open('anime_data.json', 'r', encoding='utf-8') as f:
                        file_content = f.read().strip()
                        if file_content:
                            existing_data = json.loads(file_content)
                            print(f"Data existing ditemukan: {len(existing_data)} anime")
                        else:
                            print("File anime_data.json kosong, mulai dari nol")
                except (json.JSONDecodeError, Exception) as e:
                    print(f"Error membaca anime_data.json: {e}. Mulai dari nol")
            else:
                print("File anime_data.json tidak ditemukan, mulai dari nol")

            scraped_data = []

            for index, item in enumerate(anime_items[:36]):
                print(f"\n--- Memproses Item #{index + 1} ---")
                detail_page = None
                watch_page = None
                
                try:
                    # Ambil URL Poster
                    await item.scroll_into_view_if_needed()
                    poster_url = "Tidak tersedia"
                    for attempt in range(5):
                        poster_div = await item.query_selector(".v-image__image--cover")
                        if poster_div:
                            poster_style = await poster_div.get_attribute("style")
                            if poster_style and 'url("' in poster_style:
                                parts = poster_style.split('url("')
                                if len(parts) > 1:
                                    poster_url_path = parts[1].split('")')[0]
                                    poster_url = urljoin(base_url, poster_url_path)
                                    break
                        await page.wait_for_timeout(300)
                    print(f"URL Poster: {poster_url}")

                    # Ambil URL detail
                    detail_link_element = await item.query_selector("h2.show-title a")
                    if not detail_link_element:
                        print("Gagal menemukan link judul seri, melewati item ini.")
                        continue
                    
                    detail_url_path = await detail_link_element.get_attribute("href")
                    full_detail_url = urljoin(base_url, detail_url_path)
                    
                    # Cek apakah anime sudah ada di data existing
                    existing_anime = None
                    anime_needs_update = False
                    
                    for anime in existing_data:
                        anime_url = anime.get('url_detail', '')
                        if anime_url == full_detail_url:
                            existing_anime = anime
                            print(f"Anime sudah ada di data existing: {anime.get('title', 'Unknown')}")
                            
                            total_existing_episodes = len(anime.get('episodes', []))
                            last_scraped_time = anime.get('last_updated', 0)
                            current_time = time.time()
                            
                            # **PERBAIKAN: Tentukan apakah perlu update berdasarkan progress**
                            total_expected_episodes = anime.get('total_episodes', 0)
                            
                            # Selalu update jika ada episode error atau belum selesai
                            if (total_existing_episodes < total_expected_episodes or
                                any(ep.get('status') == 'error' for ep in anime.get('episodes', []))):
                                anime_needs_update = True
                                print(f"  → Anime perlu update ({total_existing_episodes}/{total_expected_episodes} episode)")
                            else:
                                print(f"  → Anime sudah up-to-date ({total_existing_episodes}/{total_expected_episodes} episode), skip")
                            break

                    # Jika anime sudah ada dan tidak perlu update, skip
                    if existing_anime and not anime_needs_update:
                        scraped_data.append(existing_anime)
                        continue

                    # Buka halaman detail
                    detail_page = await context.new_page()
                    await detail_page.goto(full_detail_url, timeout=90000)
                    await detail_page.wait_for_selector(".anime-info-card", timeout=30000)
                    
                    # Scrape informasi dasar
                    title_element = await detail_page.query_selector(".anime-info-card .v-card__title span")
                    title = await title_element.inner_text() if title_element else "Judul tidak ditemukan"

                    # Scrape sinopsis
                    synopsis_card_title = await detail_page.query_selector("div.v-card__title:has-text('Synopsis')")
                    synopsis = "Sinopsis tidak ditemukan"
                    if synopsis_card_title:
                        parent_card = await synopsis_card_title.query_selector("xpath=..")
                        synopsis_element = await parent_card.query_selector(".text-caption")
                        if synopsis_element:
                            synopsis = await synopsis_element.inner_text()
                    
                    # Scrape genre
                    genre_elements = await detail_page.query_selector_all(".anime-info-card .v-chip--outlined .v-chip__content")
                    all_tags = [await el.inner_text() for el in genre_elements]
                    irrelevant_tags = ['TV', 'PG-13', 'Airing', '2025', '2024', '23 min', '24 min', 'SUB', 'DUB', 'ONA']
                    genres = [tag for tag in all_tags if tag not in irrelevant_tags and not tag.startswith('EP')]

                    # Scrape metadata
                    metadata_selector = ".anime-info-card .d-flex.mb-3, .anime-info-card .d-flex.mt-2.mb-3"
                    metadata_container = await detail_page.query_selector(metadata_selector)
                    metadata = []
                    if metadata_container:
                        metadata_elements = await metadata_container.query_selector_all(".text-subtitle-2")
                        all_meta_texts = [await el.inner_text() for el in metadata_elements]
                        metadata = [text.strip() for text in all_meta_texts if text and text.strip() != 'â€¢']

                    # Cari tombol "Watch Now" untuk mendapatkan URL pertama
                    watch_button = await detail_page.query_selector('a.v-btn[href*="/ep-"]')
                    first_episode_url = None
                    if watch_button:
                        watch_url_path = await watch_button.get_attribute("href")
                        first_episode_url = urljoin(base_url, watch_url_path)
                        print(f"URL Episode Pertama: {first_episode_url}")
                    else:
                        print("Tombol Watch Now tidak ditemukan")
                        await detail_page.close()
                        continue

                    # Buka halaman watch untuk scrape iframe dan episode
                    watch_page = await context.new_page()
                    await watch_page.goto(first_episode_url, timeout=90000)
                    await watch_page.wait_for_selector(".player-container", timeout=30000)
                    
                    # **PERBAIKAN: Deteksi sub/dub yang tersedia**
                    available_subdub = []
                    optimal_subdub = None  # Sub/dub yang terbukti bekerja
                    
                    try:
                        # Cari dropdown sub/dub
                        subdub_selectors = [
                            ".v-select:has(.v-label:has-text('Sub/Dub'))",
                            ".v-select .v-select__selection.v-select__selection--comma",
                            "[aria-label*='Sub/Dub']"
                        ]
                        
                        subdub_dropdown = None
                        for selector in subdub_selectors:
                            subdub_dropdown = await watch_page.query_selector(selector)
                            if subdub_dropdown:
                                break
                        
                        if subdub_dropdown:
                            # Dapatkan sub/dub saat ini
                            current_selection = await subdub_dropdown.query_selector(".v-select__selection.v-select__selection--comma")
                            if current_selection:
                                current_subdub = await current_selection.inner_text()
                                optimal_subdub = current_subdub  # Set sebagai default
                                print(f"  → Sub/Dub saat ini: {current_subdub}")
                            
                            # Buka dropdown untuk mendapatkan opsi
                            await subdub_dropdown.click()
                            await watch_page.wait_for_timeout(1000)
                            
                            # Ambil hanya opsi yang berisi bahasa (SUB/DUB)
                            all_options = await watch_page.query_selector_all(".v-list-item .v-list-item__title")
                            for option in all_options:
                                option_text = await option.inner_text()
                                # Filter hanya yang mengandung kata kunci bahasa
                                if any(keyword in option_text.lower() for keyword in ['sub', 'dub', 'japanese', 'english', 'spanish', 'chinese', 'french', 'german']):
                                    available_subdub.append(option_text)
                            
                            # Jika tidak ada yang terdeteksi, gunakan semua opsi kecuali menu navigasi
                            if not available_subdub:
                                for option in all_options:
                                    option_text = await option.inner_text()
                                    # Exclude menu navigasi
                                    if option_text not in ['Home', 'Trending', 'Schedule', 'Anime', 'Popular Shows', 'Random', '']:
                                        available_subdub.append(option_text)
                            
                            print(f"  → Tersedia sub/dub: {available_subdub}")
                            
                            # Tutup dropdown
                            await watch_page.keyboard.press("Escape")
                            await watch_page.wait_for_timeout(500)
                        else:
                            print("  → Dropdown sub/dub tidak ditemukan, menggunakan default")
                            available_subdub = ["Japanese (SUB)", "English (DUB)"]
                            optimal_subdub = "Japanese (SUB)"
                    except Exception as e:
                        print(f"  → Error detect sub/dub: {e}")
                        available_subdub = ["Japanese (SUB)", "English (DUB)"]
                        optimal_subdub = "Japanese (SUB)"

                    # **SISTEM YANG DIPERBAIKI: Sistem cicilan episode dengan optimal sub/dub**
                    episodes_data = []
                    try:
                        await watch_page.wait_for_selector(".episode-item", timeout=30000)
                        
                        # Dapatkan total episode
                        episode_items = await watch_page.query_selector_all(".episode-item")
                        total_episodes = len(episode_items)
                        print(f"Menemukan {total_episodes} episode")
                        
                        # **PERBAIKAN: Tentukan berapa episode yang akan di-scrape SEKARANG**
                        max_episodes_per_run = 10  # Maksimal 10 episode per eksekusi script
                        
                        # Gunakan data existing jika ada
                        if existing_anime:
                            episodes_data = existing_anime.get('episodes', [])
                            existing_episode_count = len(episodes_data)
                            print(f"  → Data existing: {existing_episode_count}/{total_episodes} episode")
                            
                            # Tentukan start episode
                            start_episode = existing_episode_count
                            episodes_remaining = total_episodes - start_episode
                            
                            if episodes_remaining <= 0:
                                print("  → Semua episode sudah di-scrape, skip")
                                # Tetap simpan data existing
                                anime_info = {
                                    "title": title.strip(),
                                    "synopsis": synopsis.strip(),
                                    "genres": genres,
                                    "metadata": metadata,
                                    "poster": poster_url,
                                    "url_detail": full_detail_url,
                                    "total_episodes": total_episodes,
                                    "episodes": episodes_data,
                                    "available_subdub": available_subdub,
                                    "last_updated": time.time()
                                }
                                
                                if existing_anime:
                                    existing_anime.update(anime_info)
                                    scraped_data.append(existing_anime)
                                else:
                                    scraped_data.append(anime_info)
                                
                                if watch_page and not watch_page.is_closed():
                                    await watch_page.close()
                                if detail_page and not detail_page.is_closed():
                                    await detail_page.close()
                                continue
                            else:
                                print(f"  → Sisa episode: {episodes_remaining}")
                        else:
                            start_episode = 0
                            episodes_remaining = total_episodes
                            print(f"  → Anime baru, mulai dari episode 1")
                        
                        # **PERBAIKAN: Tentukan berapa episode yang akan diambil SEKARANG**
                        if total_episodes <= 15:
                            # Anime pendek: ambil semua sekaligus
                            episodes_to_scrape_now = episodes_remaining
                            print(f"  → Anime pendek ({total_episodes} episode), ambil semua {episodes_to_scrape_now} episode sekaligus")
                        else:
                            # Anime panjang: sistem cicilan (maksimal 10 episode per run)
                            episodes_to_scrape_now = min(episodes_remaining, max_episodes_per_run)
                            print(f"  → Anime panjang ({total_episodes} episode), ambil {episodes_to_scrape_now} episode sekarang")
                        
                        end_episode = start_episode + episodes_to_scrape_now
                        print(f"  → Akan scrape episode {start_episode + 1}-{end_episode}")
                        
                        # **PERBAIKAN BESAR: Cari optimal sub/dub di episode 1, lalu gunakan untuk semua episode**
                        optimal_subdub_found = False
                        
                        for ep_index in range(start_episode, end_episode):
                            try:
                                print(f"\n  --- Memproses Episode {ep_index + 1} ---")
                                
                                if ep_index >= len(episode_items):
                                    print(f"    × Episode index {ep_index} tidak ditemukan (hanya {len(episode_items)} episode)")
                                    continue
                                    
                                # **PERBAIKAN: Dapatkan ulang episode items karena mungkin berubah setelah klik**
                                if ep_index > start_episode:
                                    episode_items = await watch_page.query_selector_all(".episode-item")
                                    if ep_index >= len(episode_items):
                                        print(f"    × Episode index {ep_index} tidak ditemukan setelah refresh")
                                        continue
                                
                                ep_item = episode_items[ep_index]
                                
                                if not ep_item:
                                    print(f"    × Gagal menemukan episode {ep_index + 1}")
                                    continue
                                    
                                # Dapatkan nomor episode
                                ep_badge = await ep_item.query_selector(".episode-badge .v-chip__content")
                                ep_number = await ep_badge.inner_text() if ep_badge else f"EP {ep_index + 1}"
                                
                                print(f"  - Mengklik episode {ep_number}...")
                                
                                # **LOGIKA UTAMA: Gunakan optimal sub/dub jika sudah ditemukan**
                                iframe_src = None
                                status = "error"
                                all_qualities = {}
                                used_subdub = optimal_subdub
                                
                                # Jika optimal sub/dub belum ditemukan (episode 1), cari dulu
                                if not optimal_subdub_found:
                                    print(f"    → Mencari optimal sub/dub...")
                                    
                                    # Coba semua available sub/dub sampai ketemu yang berhasil
                                    for subdub_option in available_subdub:
                                        print(f"    → Mencoba dengan: {subdub_option}")
                                        
                                        # Set sub/dub ke opsi ini
                                        if subdub_option != optimal_subdub:
                                            try:
                                                # Cari dropdown sub/dub
                                                subdub_dropdown = None
                                                for selector in subdub_selectors:
                                                    subdub_dropdown = await watch_page.query_selector(selector)
                                                    if subdub_dropdown:
                                                        break
                                                
                                                if subdub_dropdown:
                                                    await subdub_dropdown.click()
                                                    await watch_page.wait_for_timeout(1000)
                                                    
                                                    # Cari dan klik opsi yang diinginkan
                                                    subdub_choice = await watch_page.query_selector(f".v-list-item .v-list-item__title:has-text('{subdub_option}')")
                                                    if subdub_choice:
                                                        await subdub_choice.click()
                                                        await watch_page.wait_for_timeout(3000)
                                                        optimal_subdub = subdub_option
                                                        used_subdub = subdub_option
                                                        print(f"    ✓ Berhasil set ke: {subdub_option}")
                                                    else:
                                                        print(f"    ! Opsi {subdub_option} tidak ditemukan")
                                                        await watch_page.keyboard.press("Escape")
                                                        continue
                                                else:
                                                    print(f"    ! Dropdown sub/dub tidak ditemukan")
                                                    continue
                                            except Exception as subdub_error:
                                                print(f"    ! Gagal set sub/dub ke {subdub_option}: {subdub_error}")
                                                continue
                                        
                                        # Klik episode
                                        clicked = False
                                        for attempt in range(3):
                                            try:
                                                await ep_item.scroll_into_view_if_needed()
                                                await watch_page.wait_for_timeout(500)
                                                await watch_page.evaluate("(element) => { element.click(); }", ep_item)
                                                await watch_page.wait_for_timeout(3000)
                                                
                                                current_url = watch_page.url
                                                if "/ep-" in current_url:
                                                    clicked = True
                                                    break
                                                else:
                                                    if attempt < 2:
                                                        await watch_page.wait_for_timeout(1000)
                                            except Exception as click_error:
                                                if attempt < 2:
                                                    await watch_page.wait_for_timeout(1000)
                                                else:
                                                    print(f"    × Gagal mengklik episode: {click_error}")
                                        
                                        if not clicked and ep_index == 0:
                                            try:
                                                await watch_page.goto(first_episode_url, timeout=30000)
                                                await watch_page.wait_for_selector(".player-container", timeout=10000)
                                                clicked = True
                                            except Exception:
                                                pass
                                        
                                        if clicked:
                                            # Cari iframe
                                            await watch_page.wait_for_timeout(3000)
                                            for iframe_attempt in range(3):
                                                try:
                                                    iframe_selectors = [
                                                        "iframe.player:not([src=''])",
                                                        "iframe[src*='krussdomi']",
                                                        "iframe[src*='player']",
                                                        "iframe"
                                                    ]
                                                    
                                                    for selector in iframe_selectors:
                                                        try:
                                                            await watch_page.wait_for_selector(selector, timeout=2000)
                                                            iframe_element = await watch_page.query_selector(selector)
                                                            if iframe_element:
                                                                iframe_src = await iframe_element.get_attribute("src")
                                                                if iframe_src and iframe_src != "about:blank":
                                                                    break
                                                        except:
                                                            continue
                                                    
                                                    if iframe_src and any(pattern in iframe_src for pattern in [
                                                        "krussdomi.com/cat-player/player", "vidstream", "type=hls", 
                                                        "cat-player/player", "player", "video"
                                                    ]):
                                                        print(f"    ✓ Iframe ditemukan dengan {subdub_option}: {iframe_src[:50]}...")
                                                        status = "success"
                                                        all_qualities = {"Current": iframe_src}
                                                        optimal_subdub_found = True
                                                        optimal_subdub = subdub_option
                                                        print(f"    🎯 Optimal sub/dub ditemukan: {optimal_subdub}")
                                                        break
                                                    elif iframe_attempt < 2:
                                                        await watch_page.wait_for_timeout(1000)
                                                except Exception as iframe_error:
                                                    if iframe_attempt < 2:
                                                        await watch_page.wait_for_timeout(1000)
                                            
                                            if status == "success":
                                                break  # Keluar dari loop sub/dub jika berhasil
                                        else:
                                            print(f"    × Gagal klik episode dengan {subdub_option}")
                                
                                else:
                                    # **Episode 2+ sudah ada optimal sub/dub, langsung gunakan**
                                    print(f"    → Menggunakan optimal sub/dub: {optimal_subdub}")
                                    
                                    # Pastikan sub/dub sudah sesuai optimal
                                    current_selection = await watch_page.query_selector(".v-select__selection.v-select__selection--comma")
                                    if current_selection:
                                        current_subdub = await current_selection.inner_text()
                                        if current_subdub != optimal_subdub:
                                            print(f"    → Mengatur sub/dub ke optimal: {optimal_subdub}")
                                            try:
                                                subdub_dropdown = None
                                                for selector in subdub_selectors:
                                                    subdub_dropdown = await watch_page.query_selector(selector)
                                                    if subdub_dropdown:
                                                        break
                                                
                                                if subdub_dropdown:
                                                    await subdub_dropdown.click()
                                                    await watch_page.wait_for_timeout(1000)
                                                    subdub_choice = await watch_page.query_selector(f".v-list-item .v-list-item__title:has-text('{optimal_subdub}')")
                                                    if subdub_choice:
                                                        await subdub_choice.click()
                                                        await watch_page.wait_for_timeout(3000)
                                                        print(f"    ✓ Berhasil set ke optimal sub/dub")
                                                    else:
                                                        print(f"    ! Opsi optimal {optimal_subdub} tidak ditemukan")
                                                        await watch_page.keyboard.press("Escape")
                                            except Exception as e:
                                                print(f"    ! Gagal set optimal sub/dub: {e}")
                                    
                                    # Klik episode dengan optimal sub/dub
                                    clicked = False
                                    for attempt in range(3):
                                        try:
                                            await ep_item.scroll_into_view_if_needed()
                                            await watch_page.wait_for_timeout(500)
                                            await watch_page.evaluate("(element) => { element.click(); }", ep_item)
                                            await watch_page.wait_for_timeout(3000)
                                            
                                            current_url = watch_page.url
                                            if "/ep-" in current_url:
                                                clicked = True
                                                break
                                            else:
                                                if attempt < 2:
                                                    await watch_page.wait_for_timeout(1000)
                                        except Exception as click_error:
                                            if attempt < 2:
                                                await watch_page.wait_for_timeout(1000)
                                            else:
                                                print(f"    × Gagal mengklik episode: {click_error}")
                                    
                                    if clicked:
                                        # Cari iframe
                                        await watch_page.wait_for_timeout(3000)
                                        for iframe_attempt in range(3):
                                            try:
                                                iframe_selectors = [
                                                    "iframe.player:not([src=''])",
                                                    "iframe[src*='krussdomi']", 
                                                    "iframe[src*='player']",
                                                    "iframe"
                                                ]
                                                
                                                for selector in iframe_selectors:
                                                    try:
                                                        await watch_page.wait_for_selector(selector, timeout=2000)
                                                        iframe_element = await watch_page.query_selector(selector)
                                                        if iframe_element:
                                                            iframe_src = await iframe_element.get_attribute("src")
                                                            if iframe_src and iframe_src != "about:blank":
                                                                break
                                                    except:
                                                        continue
                                                
                                                if iframe_src and any(pattern in iframe_src for pattern in [
                                                    "krussdomi.com/cat-player/player", "vidstream", "type=hls",
                                                    "cat-player/player", "player", "video"
                                                ]):
                                                    print(f"    ✓ Iframe ditemukan: {iframe_src[:50]}...")
                                                    status = "success"
                                                    all_qualities = {"Current": iframe_src}
                                                    break
                                                elif iframe_attempt < 2:
                                                    await watch_page.wait_for_timeout(1000)
                                            except Exception as iframe_error:
                                                if iframe_attempt < 2:
                                                    await watch_page.wait_for_timeout(1000)
                                
                                # Simpan data episode
                                episode_data = {
                                    "number": ep_number,
                                    "iframe": iframe_src or "Gagal diambil",
                                    "subdub": used_subdub,
                                    "status": status,
                                    "all_qualities": all_qualities
                                }
                                
                                if ep_index < len(episodes_data):
                                    episodes_data[ep_index] = episode_data
                                else:
                                    episodes_data.append(episode_data)
                                
                            except Exception as ep_e:
                                print(f"Gagal memproses episode {ep_index + 1}: {type(ep_e).__name__}: {ep_e}")
                                
                                episode_data = {
                                    "number": f"EP {ep_index + 1}",
                                    "iframe": "Gagal diambil",
                                    "subdub": optimal_subdub or "None",
                                    "status": "error",
                                    "all_qualities": {}
                                }
                                
                                if ep_index < len(episodes_data):
                                    episodes_data[ep_index] = episode_data
                                else:
                                    episodes_data.append(episode_data)
                                continue
                                    
                    except Exception as e:
                        print(f"Gagal scrape daftar episode: {e}")
                        if existing_anime:
                            episodes_data = existing_anime.get('episodes', [])
                            print("  → Menggunakan data episode existing karena gagal scrape")

                    # **STRUKTUR FINAL**
                    anime_info = {
                        "title": title.strip(),
                        "synopsis": synopsis.strip(),
                        "genres": genres,
                        "metadata": metadata,
                        "poster": poster_url,
                        "url_detail": full_detail_url,
                        "total_episodes": total_episodes,
                        "episodes": episodes_data,
                        "available_subdub": available_subdub,
                        "optimal_subdub": optimal_subdub,
                        "last_updated": time.time()
                    }
                    
                    # Update atau tambah data baru
                    if existing_anime:
                        existing_anime.update(anime_info)
                        scraped_data.append(existing_anime)
                    else:
                        scraped_data.append(anime_info)
                    
                    success_count = sum(1 for ep in episodes_data if ep.get('status') in ['success'])
                    current_episode_count = len(episodes_data)
                    
                    print(f"✓ Data {title} {'diperbarui' if existing_anime else 'ditambahkan'} ({success_count}/{current_episode_count} berhasil, {current_episode_count - success_count} error)")
                    print(f"  → Progress: {current_episode_count}/{total_episodes} episode ({current_episode_count/total_episodes*100:.1f}%)")
                    if optimal_subdub_found:
                        print(f"  → Optimal sub/dub: {optimal_subdub}")
                    
                    # Tutup halaman
                    if watch_page and not watch_page.is_closed():
                        await watch_page.close()
                    if detail_page and not detail_page.is_closed():
                        await detail_page.close()

                except Exception as e:
                    print(f"!!! Gagal memproses item #{index + 1}: {type(e).__name__}: {e}")
                    if existing_anime:
                        scraped_data.append(existing_anime)
                        print(f"  → Tetap menyimpan data existing untuk {existing_anime.get('title')}")
                    
                    if watch_page and not watch_page.is_closed():
                        await watch_page.close()
                    if detail_page and not detail_page.is_closed():
                        await detail_page.close()

            # Gabungkan data baru dengan data existing yang tidak di-update
            updated_urls = [anime.get('url_detail') for anime in scraped_data]
            for existing_anime in existing_data:
                if existing_anime.get('url_detail') not in updated_urls:
                    scraped_data.append(existing_anime)

            print("\n" + "="*50)
            print(f"HASIL SCRAPING SELESAI. Total {len(scraped_data)} data berhasil diambil/diperbarui.")
            
            # Hitung statistik
            total_scraped_episodes = sum(len(anime.get('episodes', [])) for anime in scraped_data)
            total_expected_episodes = sum(anime.get('total_episodes', 0) for anime in scraped_data)
            successful_episodes = sum(1 for anime in scraped_data for ep in anime.get('episodes', []) if ep.get('status') in ['success'])
            
            progress_percentage = (total_scraped_episodes / total_expected_episodes * 100) if total_expected_episodes > 0 else 0
            success_rate = (successful_episodes / total_scraped_episodes * 100) if total_scraped_episodes > 0 else 0
            
            print(f"Progress Episode: {total_scraped_episodes}/{total_expected_episodes} ({progress_percentage:.1f}%)")
            print(f"Success Rate: {successful_episodes}/{total_scraped_episodes} ({success_rate:.1f}%)")
            print("="*50)
                
            # Simpan data final
            try:
                with open('anime_data.json', 'w', encoding='utf-8') as f:
                    json.dump(scraped_data, f, ensure_ascii=False, indent=4)
                print("\nData berhasil disimpan ke anime_data.json")
            except Exception as e:
                print(f"Error menyimpan data: {e}")

        except Exception as e:
            print(f"Terjadi kesalahan fatal: {type(e).__name__}: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_kickass_anime())
