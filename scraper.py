import asyncio
from playwright.async_api import async_playwright
import json
from urllib.parse import urljoin
import os
import time
import re

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
                    # Reset variabel page setiap item baru
                    detail_page = None
                    watch_page = None

                    # Ambil URL Poster dengan delay lebih panjang
                    await item.scroll_into_view_if_needed()
                    await asyncio.sleep(2)  # Delay untuk pastiin load
                    poster_url = "Tidak tersedia"
                    for attempt in range(5):  # Retry lebih banyak
                        poster_div = await item.query_selector(".v-image__image--cover")
                        if poster_div:
                            poster_style = await poster_div.get_attribute("style")
                            if poster_style and 'url("' in poster_style:
                                parts = poster_style.split('url("')
                                if len(parts) > 1:
                                    poster_url_path = parts[1].split('")')[0]
                                    poster_url = urljoin(base_url, poster_url_path)
                                    break
                        await asyncio.sleep(1)  # Delay antar retry
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
                            
                            total_existing_episodes = len([ep for ep in anime.get('episodes', []) if ep.get('status') in ['success', 'pending']])
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
                    await asyncio.sleep(3)  # Delay load penuh
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
                    await asyncio.sleep(3)  # Delay load
                    await watch_page.wait_for_selector(".player-container", timeout=30000)
                    
                    # **Logic dari Script Lama lu: Get Available Sub/Dub**
                    async def get_available_subdub_from_dropdown(watch_page):
                        subdub_options = []
                        try:
                            dropdown_selectors = [
                                "//div[contains(@class, 'episode-list')]//div[contains(@class, 'v-select')]",
                                "//div[contains(@class, 'v-card__title')]//div[contains(@class, 'v-select')]",
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
                                    print(f"Dropdown ditemukan dengan selector: {selector}")
                                    break
                            
                            if not dropdown:
                                print("Dropdown Sub/Dub tidak ditemukan di episode list")
                                return []
                            
                            # Klik dropdown untuk membuka opsi
                            await dropdown.click()
                            await watch_page.wait_for_timeout(2000)
                            
                            # Baca opsi-opsi yang tersedia dari menu dropdown yang terbuka
                            option_selectors = [
                                "//div[contains(@class, 'v-menu__content')]//div[contains(@class, 'v-list-item__title')]",
                                ".v-menu__content .v-list-item .v-list-item__title",
                                "//div[contains(@class, 'v-list-item__title')]"
                            ]
                            
                            for selector in option_selectors:
                                if selector.startswith("//"):
                                    option_elements = await watch_page.query_selector_all(f"xpath={selector}")
                                else:
                                    option_elements = await watch_page.query_selector_all(selector)
                                
                                if option_elements:
                                    print(f"Found {len(option_elements)} options with selector: {selector}")
                                    for option in option_elements:
                                        option_text = await option.inner_text()
                                        if option_text and option_text.strip():
                                            # Filter hanya opsi yang berhubungan dengan bahasa/sub/dub
                                            if any(keyword in option_text.lower() for keyword in ['japanese', 'english', 'chinese', 'mandarin', 'español', 'sub', 'dub']):
                                                subdub_options.append(option_text.strip())
                                    
                                    if subdub_options:
                                        break
                            
                            # Jika tidak ada opsi yang ditemukan, coba cara lain
                            if not subdub_options:
                                # Coba baca dari elemen yang sedang aktif
                                active_option = await watch_page.query_selector("//div[contains(@class, 'v-select__selections')]//div[contains(@class, 'v-select__selection')]")
                                if active_option:
                                    active_text = await active_option.inner_text()
                                    if active_text and active_text.strip():
                                        subdub_options = [active_text.strip()]
                                        print(f"Hanya menemukan 1 opsi: {active_text}")
                            
                            # Prioritas Chinese kalau detect
                            chinese_options = [subdub for subdub in subdub_options if 'chinese' in subdub.lower() or 'mandarin' in subdub.lower()]
                            if chinese_options:
                                print(f"  🎯 CHINESE DETECTED - Prioritas Chinese: {chinese_options}")
                                subdub_options = chinese_options
                            
                            # Tutup dropdown
                            await watch_page.keyboard.press("Escape")
                            await watch_page.wait_for_timeout(1000)
                            
                            print(f"Sub/Dub tersedia dari dropdown: {subdub_options}")
                            return subdub_options
                            
                        except Exception as e:
                            print(f"Gagal membaca dropdown sub/dub: {e}")
                            return []

                    # **Logic dari Script Lama lu: Change Sub/Dub**
                    async def change_subdub_from_dropdown(watch_page, target_subdub):
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
                                print("Dropdown tidak ditemukan untuk mengganti sub/dub")
                                return False
                            
                            # Buka dropdown
                            await dropdown.click()
                            await watch_page.wait_for_timeout(2000)
                            
                            # Cari dan klik opsi yang diinginkan
                            option_selectors = [
                                f"//div[contains(@class, 'v-menu__content')]//div[contains(@class, 'v-list-item__title') and contains(text(), '{target_subdub}')]",
                                f".v-menu__content .v-list-item:has-text('{target_subdub}')]"
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
                                await watch_page.wait_for_timeout(4000)  # Tunggu loading lebih lama
                                print(f"✓ Berhasil ganti ke: {target_subdub}")
                                return True
                            else:
                                print(f"✗ Opsi {target_subdub} tidak ditemukan dalam dropdown")
                                await watch_page.keyboard.press("Escape")
                                return False
                                
                        except Exception as e:
                            print(f"Gagal mengganti sub/dub ke {target_subdub}: {e}")
                            return False

                    # **Logic dari Script Lama lu: Is Iframe Valid**
                    async def is_iframe_valid(iframe_src):
                        if not iframe_src or iframe_src in ["Iframe tidak ditemukan", "Iframe tidak tersedia"]:
                            return False
                        
                        valid_patterns = [
                            "krussdomi.com/cat-player/player",
                            "vidstream",
                            "type=hls",
                            "cat-player/player"
                        ]
                        
                        return any(pattern in iframe_src for pattern in valid_patterns)

                    # **Logic dari Script Lama lu: Get All Sub/Dub Iframes**
                    async def get_all_subdub_iframes(watch_page, episode_number):
                        available_subdub = await get_available_subdub_from_dropdown(watch_page)
                        
                        chinese_options = [subdub for subdub in available_subdub if 'chinese' in subdub.lower() or 'mandarin' in subdub.lower()]
                        if chinese_options:
                            print(f"  🎯 DETECTED CHINESE CONTENT - Prioritas Chinese: {chinese_options}")
                            available_subdub = chinese_options  # Prioritas Chinese untuk donghua
                        
                        if not available_subdub:
                            print("  Tidak ada pilihan sub/dub, menggunakan iframe default")
                            iframe_element = await watch_page.query_selector("iframe.player")
                            current_iframe = await iframe_element.get_attribute("src") if iframe_element else "Iframe tidak ditemukan"
                            return {
                                "iframe_url": current_iframe,
                                "subdub_used": "Default",
                                "status": "success" if await is_iframe_valid(current_iframe) else "error",
                                "all_subdub_iframes": {"Default": current_iframe}
                            }
                        
                        print(f"  Mengambil iframe untuk {len(available_subdub)} sub/dub: {available_subdub}")
                        
                        all_iframes = {}
                        current_subdub = available_subdub[0]
                        
                        # Simpan iframe original
                        iframe_element = await watch_page.query_selector("iframe.player")
                        original_iframe = await iframe_element.get_attribute("src") if iframe_element else "Iframe tidak ditemukan"
                        all_iframes[current_subdub] = original_iframe
                        
                        # Coba setiap sub/dub lain
                        for subdub in available_subdub[1:]:
                            print(f"  Mengambil iframe untuk: {subdub}")
                            
                            success = await change_subdub_from_dropdown(watch_page, subdub)
                            if not success:
                                all_iframes[subdub] = "Gagal switch"
                                continue
                            
                            # Re-click episode kalau perlu (handle URL change)
                            episode_items = await watch_page.query_selector_all(".episode-item")
                            found_ep_item = None
                            for item in episode_items:
                                badge = await item.query_selector(".episode-badge .v-chip__content")
                                if badge and await badge.inner_text() == episode_number:
                                    found_ep_item = item
                                    break
                                
                            if found_ep_item:
                                print(f"    → Re-click episode {episode_number} setelah switch (handle URL change)")
                                await found_ep_item.scroll_into_view_if_needed()
                                await asyncio.sleep(1)
                                await found_ep_item.click()
                                await asyncio.sleep(5)  # Delay load iframe baru
                            else:
                                print(f"    ! Episode {episode_number} tidak ditemukan setelah switch, skip")
                                all_iframes[subdub] = "Gagal re-click"
                                continue
                            
                            # Ambil iframe
                            iframe_element = await watch_page.query_selector("iframe.player")
                            iframe_src = await iframe_element.get_attribute("src") if iframe_element else "Iframe tidak ditemukan"
                            all_iframes[subdub] = iframe_src
                        
                        # Kembali ke sub original
                        if len(available_subdub) > 1:
                            await change_subdub_from_dropdown(watch_page, available_subdub[0])
                        
                        # Pilih primary iframe yang valid
                        primary_iframe = original_iframe
                        primary_subdub = current_subdub
                        for subdub, iframe_url in all_iframes.items():
                            if await is_iframe_valid(iframe_url):
                                primary_iframe = iframe_url
                                primary_subdub = subdub
                                break
                        
                        return {
                            "iframe_url": primary_iframe,
                            "subdub_used": primary_subdub,
                            "status": "success" if await is_iframe_valid(primary_iframe) else "error",
                            "all_subdub_iframes": all_iframes
                        }

                    # **PERBAIKAN: Approach baru untuk deteksi dropdown**
                    available_subdub = await get_available_subdub_from_dropdown(watch_page)
                    current_subdub = available_subdub[0] if available_subdub else "Tidak diketahui"
                    optimal_subdub = available_subdub[0] if available_subdub else "Tidak diketahui"  # No asumsi Japanese
                    available_pages = []
                    current_page = "01-05"
                    episodes_per_page = 5
                    total_episodes = 5
                    
                    try:
                        # ... (kode deteksi dropdown page sama seperti sebelumnya, skip untuk breviti)
                    except Exception as e:
                        print(f"  → Error utama detect dropdown: {e}")
                        # Fallback...
                    
                    # ... (kode multi-page dan proses episode sama seperti sebelumnya, tapi integrasi get_all_subdub_iframes per episode)

                    for ep_data in all_episodes_to_scrape:
                        # ... (navigasi page)
                        try:
                            # ... (get ep_item, ep_number)
                            
                            # Klik episode
                            # ... (kode klik)
                            
                            # Ambil all iframes
                            ep_iframe_info = await get_all_subdub_iframes(watch_page, ep_number)
                            iframe_src = ep_iframe_info["iframe_url"]
                            status = ep_iframe_info["status"]
                            
                            episode_data = {
                                "number": ep_number,
                                "iframe": iframe_src,
                                "subdub": ep_iframe_info["subdub_used"],
                                "status": status,
                                "all_qualities": ep_iframe_info["all_subdub_iframes"]
                            }
                            
                            # ... (save episode_data)
                            
                        except Exception as ep_e:
                            # ... (handle error)
                    
                    # ... (final anime_info, save json)
                    
                except Exception as e:
                    # ... (handle error)

            # ... (gabung data, save json)
            
        except Exception as e:
            # ... (fatal error)

if __name__ == "__main__":
    asyncio.run(scrape_kickass_anime())
