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

            # Load existing data jika ada - DENGAN ERROR HANDLING
            existing_data = []
            if os.path.exists('anime_data.json'):
                try:
                    with open('anime_data.json', 'r', encoding='utf-8') as f:
                        file_content = f.read().strip()
                        if file_content:  # Cek jika file tidak kosong
                            existing_data = json.loads(file_content)
                            print(f"Data existing ditemukan: {len(existing_data)} anime")
                        else:
                            print("File anime_data.json kosong, mulai dari nol")
                except json.JSONDecodeError as e:
                    print(f"Error membaca anime_data.json: {e}. Mulai dari nol")
                except Exception as e:
                    print(f"Error membaca file: {e}. Mulai dari nol")
            else:
                print("File anime_data.json tidak ditemukan, mulai dari nol")

            scraped_data = []

            for index, item in enumerate(anime_items[:36]):  # Batasi untuk testing
                print(f"\n--- Memproses Item #{index + 1} ---")
                detail_page = None
                watch_page = None
                
                try:
                    # Ambil URL Poster dari halaman utama
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
                    
                    # Gunakan URL sebagai identifier untuk existing data
                    for anime in existing_data:
                        # Cek berdasarkan URL detail jika ada, atau berdasarkan judul
                        anime_url = anime.get('url_detail', '') if 'url_detail' in anime else ''
                        if anime_url == full_detail_url:
                            existing_anime = anime
                            print(f"Anime sudah ada di data existing: {anime.get('title', 'Unknown')}")
                            
                            # Cek apakah perlu update
                            total_existing_episodes = len(anime.get('episodes', []))
                            last_scraped_time = anime.get('last_updated', 0)
                            current_time = time.time()
                            
                            if (total_existing_episodes == 0 or 
                                (current_time - last_scraped_time) > 3600 or
                                any(ep.get('status') == 'error' for ep in anime.get('episodes', []))):
                                anime_needs_update = True
                                print(f"  → Anime perlu update (episodes: {total_existing_episodes}, last update: {current_time - last_scraped_time:.0f}s ago)")
                            else:
                                print(f"  → Anime sudah up-to-date, skip")
                            
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
                    
                    # Fungsi untuk mendapatkan daftar sub/dub yang tersedia
                    async def get_available_subdub_from_dropdown(watch_page):
                        """Mendapatkan daftar sub/dub yang tersedia"""
                        subdub_options = []
                        try:
                            dropdown_selectors = [
                                "//div[contains(@class, 'episode-list')]//div[contains(@class, 'v-select')]",
                                ".episode-list .v-select",
                                "//label[contains(text(), 'Sub/Dub')]/ancestor::div[contains(@class, 'v-select')]"
                            ]
                            
                            dropdown = None
                            for selector in dropdown_selectors:
                                if selector.startswith("//"):
                                    dropdown = await watch_page.query_selector(f"xpath={selector}")
                                else:
                                    dropdown = await watch_page.query_selector(selector)
                                if dropdown:
                                    break
                            
                            if not dropdown:
                                return []
                            
                            await dropdown.click()
                            await watch_page.wait_for_timeout(2000)
                            
                            option_selectors = [
                                "//div[contains(@class, 'v-menu__content')]//div[contains(@class, 'v-list-item__title')]",
                                ".v-menu__content .v-list-item .v-list-item__title"
                            ]
                            
                            for selector in option_selectors:
                                if selector.startswith("//"):
                                    option_elements = await watch_page.query_selector_all(f"xpath={selector}")
                                else:
                                    option_elements = await watch_page.query_selector_all(selector)
                                
                                if option_elements:
                                    for option in option_elements:
                                        option_text = await option.inner_text()
                                        if option_text and option_text.strip():
                                            subdub_options.append(option_text.strip())
                                    break
                            
                            await watch_page.keyboard.press("Escape")
                            await watch_page.wait_for_timeout(1000)
                            
                            return subdub_options
                            
                        except Exception as e:
                            print(f"Gagal membaca dropdown sub/dub: {e}")
                            return []

                    # Fungsi untuk mengganti sub/dub
                    async def change_subdub_from_dropdown(watch_page, target_subdub):
                        """Mengganti sub/dub"""
                        try:
                            dropdown_selectors = [
                                "//div[contains(@class, 'episode-list')]//div[contains(@class, 'v-select')]",
                                ".episode-list .v-select"
                            ]
                            
                            dropdown = None
                            for selector in dropdown_selectors:
                                if selector.startswith("//"):
                                    dropdown = await watch_page.query_selector(f"xpath={selector}")
                                else:
                                    dropdown = await watch_page.query_selector(selector)
                                if dropdown:
                                    break
                            
                            if not dropdown:
                                return False
                            
                            await dropdown.click()
                            await watch_page.wait_for_timeout(2000)
                            
                            option_selectors = [
                                f"//div[contains(@class, 'v-menu__content')]//div[contains(@class, 'v-list-item__title') and contains(text(), '{target_subdub}')]",
                                f".v-menu__content .v-list-item:has-text('{target_subdub}')"
                            ]
                            
                            target_option = None
                            for selector in option_selectors:
                                if selector.startswith("//"):
                                    target_option = await watch_page.query_selector(f"xpath={selector}")
                                else:
                                    target_option = await watch_page.query_selector(selector)
                                if target_option:
                                    break
                            
                            if target_option:
                                await target_option.click()
                                await watch_page.wait_for_timeout(4000)
                                return True
                            else:
                                await watch_page.keyboard.press("Escape")
                                return False
                                
                        except Exception as e:
                            print(f"Gagal mengganti sub/dub ke {target_subdub}: {e}")
                            return False

                    # Fungsi untuk mengecek iframe valid
                    async def is_iframe_valid(iframe_src):
                        """Mengecek apakah iframe valid"""
                        if not iframe_src or iframe_src in ["Iframe tidak ditemukan", "Iframe tidak tersedia"]:
                            return False
                        
                        valid_patterns = [
                            "krussdomi.com/cat-player/player",
                            "vidstream",
                            "type=hls",
                            "cat-player/player"
                        ]
                        
                        return any(pattern in iframe_src for pattern in valid_patterns)

                    # FUNGSI: Mencari iframe dengan mencoba semua sub/dub
                    async def find_valid_iframe_across_subdub(watch_page, episode_number):
                        """Mencari iframe valid dengan mencoba semua pilihan sub/dub"""
                        available_subdub = await get_available_subdub_from_dropdown(watch_page)
                        
                        if not available_subdub:
                            print("    → Tidak ada pilihan sub/dub tersedia")
                            return None, None
                        
                        print(f"    → Mencari iframe di {len(available_subdub)} pilihan sub/dub: {available_subdub}")
                        
                        # Simpan sub/dub awal untuk kembali nanti
                        original_subdub = available_subdub[0]
                        
                        for subdub_option in available_subdub:
                            try:
                                print(f"    → Mencoba sub/dub: {subdub_option}")
                                
                                # Ganti sub/dub
                                success = await change_subdub_from_dropdown(watch_page, subdub_option)
                                if not success:
                                    continue
                                
                                await watch_page.wait_for_timeout(3000)
                                
                                # Tunggu dan cek iframe
                                try:
                                    await watch_page.wait_for_selector("iframe.player:not([src=''])", timeout=5000)
                                except:
                                    print(f"      - Timeout menunggu iframe untuk {subdub_option}")
                                    continue
                                
                                # Dapatkan iframe
                                iframe_element = await watch_page.query_selector("iframe.player")
                                iframe_src = await iframe_element.get_attribute("src") if iframe_element else None
                                
                                if await is_iframe_valid(iframe_src):
                                    print(f"      ✓ Iframe valid ditemukan di {subdub_option}: {iframe_src[:50]}...")
                                    return iframe_src, subdub_option
                                else:
                                    print(f"      × Iframe tidak valid di {subdub_option}")
                                    
                            except Exception as e:
                                print(f"      ! Error saat mencoba {subdub_option}: {e}")
                                continue
                        
                        # Kembali ke sub/dub awal
                        await change_subdub_from_dropdown(watch_page, original_subdub)
                        return None, None

                    # FUNGSI: Untuk mendapatkan iframe dengan fallback yang lebih baik
                    async def get_episode_iframes_improved(watch_page, episode_number):
                        """Mendapatkan iframe dengan sistem fallback yang lebih robust"""
                        print(f"    Mencari iframe untuk episode {episode_number}...")
                        
                        # Coba dapatkan iframe dengan sub/dub saat ini terlebih dahulu
                        try:
                            await watch_page.wait_for_selector("iframe.player:not([src=''])", timeout=8000)
                            iframe_element = await watch_page.query_selector("iframe.player")
                            current_iframe = await iframe_element.get_attribute("src") if iframe_element else None
                            
                            if await is_iframe_valid(current_iframe):
                                print(f"    ✓ Iframe langsung ditemukan: {current_iframe[:50]}...")
                                return {
                                    "iframe": current_iframe,
                                    "subdub_used": "Current",
                                    "status": "success",
                                    "all_subdub": {"Current": current_iframe}
                                }
                        except:
                            print("    × Iframe tidak ditemukan dengan sub/dub saat ini")
                        
                        # Jika tidak valid, coba semua sub/dub yang tersedia
                        valid_iframe, valid_subdub = await find_valid_iframe_across_subdub(watch_page, episode_number)
                        
                        if valid_iframe:
                            return {
                                "iframe": valid_iframe,
                                "subdub_used": valid_subdub,
                                "status": "success_fallback",
                                "all_subdub": {valid_subdub: valid_iframe}
                            }
                        else:
                            print("    × Tidak ada iframe valid yang ditemukan di semua sub/dub")
                            return {
                                "iframe": "Iframe tidak ditemukan",
                                "subdub_used": "None",
                                "status": "error",
                                "all_subdub": {}
                            }

                    # **SISTEM CICIL YANG DIPERBAIKI - TANPA BATASAN 5 EPISODE**
                    episodes_data = []
                    try:
                        await watch_page.wait_for_selector(".episode-item", timeout=30000)
                        episode_items = await watch_page.query_selector_all(".episode-item")
                        total_episodes = len(episode_items)
                        print(f"Menemukan {total_episodes} episode")
                        
                        # Tentukan episode mana yang akan di-scrape
                        start_episode = 0
                        if existing_anime:
                            # Lanjutkan dari episode terakhir yang berhasil di-scrape
                            existing_episodes = existing_anime.get('episodes', [])
                            last_successful_episode = 0
                            
                            for i, ep in enumerate(existing_episodes):
                                if ep.get('status') in ['success', 'success_fallback', 'fallback_success']:
                                    last_successful_episode = i
                            
                            start_episode = last_successful_episode + 1
                            print(f"  → Lanjutkan dari episode {start_episode + 1} (terakhir berhasil: {last_successful_episode + 1})")
                            
                            # Gunakan episode yang sudah ada
                            episodes_data = existing_episodes
                        else:
                            # Mulai dari awal untuk anime baru
                            start_episode = 0
                            print(f"  → Mulai dari episode 1 (anime baru)")
                        
                        # **PERUBAHAN PENTING: Hapus batasan 5 episode, tapi gunakan sistem cicilan untuk anime panjang**
                        episodes_remaining = total_episodes - start_episode
                        
                        if episodes_remaining <= 0:
                            print("  → Semua episode sudah di-scrape, skip")
                        else:
                            # Tentukan batch size berdasarkan total episode
                            if total_episodes > 15:
                                batch_size = 10  # Cicilan 10 episode untuk anime panjang
                                print(f"  → Anime panjang ({total_episodes} episode), gunakan sistem cicilan {batch_size} episode per batch")
                            else:
                                batch_size = episodes_remaining  # Ambil semua untuk anime pendek
                                print(f"  → Anime pendek ({total_episodes} episode), ambil semua {episodes_remaining} episode sekaligus")
                            
                            # Hitung berapa batch yang perlu di-scrape
                            total_batches = (episodes_remaining + batch_size - 1) // batch_size
                            
                            for batch_num in range(total_batches):
                                batch_start = start_episode + (batch_num * batch_size)
                                batch_end = min(batch_start + batch_size, total_episodes)
                                episodes_in_batch = batch_end - batch_start
                                
                                print(f"  → Batch {batch_num + 1}/{total_batches}: Episode {batch_start + 1}-{batch_end} ({episodes_in_batch} episode)")
                                
                                # Scrape episode dalam batch ini
                                for ep_index in range(batch_start, batch_end):
                                    try:
                                        print(f"\n  --- Memproses Episode {ep_index + 1} ---")
                                        
                                        # Refresh daftar episode items setiap batch untuk menghindari stale elements
                                        if ep_index == batch_start:
                                            episode_items = await watch_page.query_selector_all(".episode-item")
                                        
                                        if ep_index >= len(episode_items):
                                            break
                                            
                                        ep_item = episode_items[ep_index]
                                        
                                        ep_badge = await ep_item.query_selector(".episode-badge .v-chip__content")
                                        ep_number = await ep_badge.inner_text() if ep_badge else f"EP {ep_index + 1}"
                                        
                                        print(f"  - Mengklik episode {ep_number}...")
                                        
                                        await ep_item.click()
                                        await watch_page.wait_for_timeout(3000)
                                        
                                        # Gunakan fungsi yang diperbaiki untuk mendapatkan iframe
                                        ep_iframe_info = await get_episode_iframes_improved(watch_page, ep_number)
                                        
                                        # **STRUKTUR EPISODE YANG LEBIH RAPI**
                                        episode_data = {
                                            "number": ep_number,
                                            "iframe": ep_iframe_info["iframe"],
                                            "subdub": ep_iframe_info["subdub_used"],
                                            "status": ep_iframe_info["status"],
                                            "all_qualities": ep_iframe_info.get("all_subdub", {})
                                        }
                                        
                                        # Tambahkan atau replace episode data
                                        if ep_index < len(episodes_data):
                                            episodes_data[ep_index] = episode_data
                                        else:
                                            episodes_data.append(episode_data)
                                        
                                        print(f"    Iframe: {ep_iframe_info['iframe']}")
                                        print(f"    Status: {ep_iframe_info['status']}")
                                        print(f"    Sub/Dub: {ep_iframe_info['subdub_used']}")
                                        
                                    except Exception as ep_e:
                                        print(f"Gagal memproses episode {ep_index + 1}: {type(ep_e).__name__}: {ep_e}")
                                        
                                        # Fallback: coba sekali lagi dengan sistem sub/dub
                                        try:
                                            print("    → Mencoba fallback dengan pencarian sub/dub...")
                                            fallback_iframe, fallback_subdub = await find_valid_iframe_across_subdub(watch_page, f"EP {ep_index + 1}")
                                            
                                            if fallback_iframe:
                                                episode_data = {
                                                    "number": f"EP {ep_index + 1}",
                                                    "iframe": fallback_iframe,
                                                    "subdub": fallback_subdub,
                                                    "status": "fallback_success",
                                                    "all_qualities": {fallback_subdub: fallback_iframe}
                                                }
                                                print(f"    ✓ Fallback berhasil: {fallback_iframe[:50]}...")
                                            else:
                                                episode_data = {
                                                    "number": f"EP {ep_index + 1}",
                                                    "iframe": "Gagal diambil",
                                                    "subdub": "None",
                                                    "status": "error",
                                                    "all_qualities": {}
                                                }
                                                print("    × Fallback gagal")
                                            
                                            if ep_index < len(episodes_data):
                                                episodes_data[ep_index] = episode_data
                                            else:
                                                episodes_data.append(episode_data)
                                        except Exception as fallback_e:
                                            print(f"    ! Fallback juga gagal: {fallback_e}")
                                            episode_data = {
                                                "number": f"EP {ep_index + 1}",
                                                "iframe": "Gagal diambil",
                                                "subdub": "None",
                                                "status": "error",
                                                "all_qualities": {}
                                            }
                                            if ep_index < len(episodes_data):
                                                episodes_data[ep_index] = episode_data
                                            else:
                                                episodes_data.append(episode_data)
                                        continue
                                
                                # Jika ini bukan batch terakhir, beri jeda sebelum batch berikutnya
                                if batch_num < total_batches - 1:
                                    print(f"\n  → Batch {batch_num + 1} selesai. Menunggu 2 detik sebelum batch berikutnya...")
                                    await asyncio.sleep(2)
                                    
                    except Exception as e:
                        print(f"Gagal scrape daftar episode: {e}")
                        if existing_anime:
                            episodes_data = existing_anime.get('episodes', [])
                            print("  → Menggunakan data episode existing karena gagal scrape")

                    # Dapatkan semua pilihan sub/dub yang tersedia
                    available_subdub = await get_available_subdub_from_dropdown(watch_page)
                    
                    # **STRUKTUR JSON YANG LEBIH RAPI**
                    anime_info = {
                        "title": title.strip(),
                        "synopsis": synopsis.strip(),
                        "genres": genres,
                        "metadata": metadata,
                        "poster": poster_url,
                        "url_detail": full_detail_url,  # Tambahkan URL detail untuk identifier
                        "total_episodes": total_episodes,
                        "episodes": episodes_data,
                        "available_subdub": available_subdub,
                        "last_updated": time.time()
                    }
                    
                    # Update atau tambah data baru
                    if existing_anime:
                        existing_anime.update(anime_info)
                        scraped_data.append(existing_anime)
                        
                        # Hitung statistik episode
                        success_count = sum(1 for ep in episodes_data if ep.get('status') in ['success', 'success_fallback', 'fallback_success'])
                        error_count = sum(1 for ep in episodes_data if ep.get('status') == 'error')
                        
                        print(f"✓ Data {title} diperbarui ({success_count}/{len(episodes_data)} berhasil, {error_count} error)")
                    else:
                        scraped_data.append(anime_info)
                        
                        # Hitung statistik episode
                        success_count = sum(1 for ep in episodes_data if ep.get('status') in ['success', 'success_fallback', 'fallback_success'])
                        error_count = sum(1 for ep in episodes_data if ep.get('status') == 'error')
                        
                        print(f"✓ Data {title} ditambahkan baru ({success_count}/{len(episodes_data)} berhasil, {error_count} error)")
                    
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
            updated_titles = [anime.get('title') for anime in scraped_data]
            for existing_anime in existing_data:
                if existing_anime.get('title') not in updated_titles:
                    scraped_data.append(existing_anime)

            print("\n" + "="*50)
            print(f"HASIL SCRAPING SELESAI. Total {len(scraped_data)} data berhasil diambil/diperbarui.")
            
            # Hitung progress episode
            total_scraped_episodes = sum(len(anime.get('episodes', [])) for anime in scraped_data)
            total_expected_episodes = sum(anime.get('total_episodes', 0) for anime in scraped_data)
            progress_percentage = (total_scraped_episodes / total_expected_episodes * 100) if total_expected_episodes > 0 else 0
            
            # Hitung statistik keberhasilan
            successful_episodes = 0
            for anime in scraped_data:
                for ep in anime.get('episodes', []):
                    if ep.get('status') in ['success', 'success_fallback', 'fallback_success']:
                        successful_episodes += 1
            
            success_rate = (successful_episodes / total_scraped_episodes * 100) if total_scraped_episodes > 0 else 0
            
            print(f"Progress Episode: {total_scraped_episodes}/{total_expected_episodes} ({progress_percentage:.1f}%)")
            print(f"Success Rate: {successful_episodes}/{total_scraped_episodes} ({success_rate:.1f}%)")
            print("="*50)
                
            # Simpan data dengan error handling
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
