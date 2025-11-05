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

            # ============================================================
            # FUNGSI DARI SCRIPT LAMA UNTUK HANDLE SUB/DUB
            # ============================================================
            
            async def get_available_subdub_from_dropdown(watch_page):
                """Mendapatkan daftar sub/dub yang tersedia dengan MEMBACA DROPDOWN YANG BENAR"""
                subdub_options = []
                try:
                    # Cari dropdown sub/dub yang tepat - di episode list section
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
                    await asyncio.sleep(2)
                    
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
                                    if any(keyword in option_text.lower() for keyword in ['japanese', 'english', 'chinese', 'español', 'sub', 'dub']):
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
                    
                    # === PERUBAHAN PENTING: PRIORITAS CHINESE ===
                    chinese_options = [subdub for subdub in subdub_options if 'chinese' in subdub.lower()]
                    if chinese_options:
                        print(f"  🎯 CHINESE DETECTED - Filter hanya Chinese: {chinese_options}")
                        subdub_options = chinese_options
                    # === END PERUBAHAN ===
                    
                    # Tutup dropdown
                    await watch_page.keyboard.press("Escape")
                    await asyncio.sleep(1)
                    
                    print(f"Sub/Dub tersedia dari dropdown: {subdub_options}")
                    return subdub_options
                    
                except Exception as e:
                    print(f"Gagal membaca dropdown sub/dub: {e}")
                    return []

            async def change_subdub_from_dropdown(watch_page, target_subdub):
                """Mengganti sub/dub dengan MEMILIH dari dropdown yang benar"""
                try:
                    # Cari dropdown yang tepat
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
                    await asyncio.sleep(2)
                    
                    # Cari dan klik opsi yang diinginkan
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
                        await asyncio.sleep(4)  # Tunggu loading lebih lama
                        print(f"✓ Berhasil ganti ke: {target_subdub}")
                        return True
                    else:
                        print(f"✗ Opsi {target_subdub} tidak ditemukan dalam dropdown")
                        await watch_page.keyboard.press("Escape")
                        return False
                        
                except Exception as e:
                    print(f"Gagal mengganti sub/dub ke {target_subdub}: {e}")
                    return False

            async def is_iframe_valid(iframe_src):
                """Mengecek apakah iframe valid (tidak kosong dan tidak error)"""
                if not iframe_src or iframe_src in ["Iframe tidak ditemukan", "Iframe tidak tersedia"]:
                    return False
                
                # Cek pattern iframe yang valid
                valid_patterns = [
                    "krussdomi.com/cat-player/player",
                    "vidstream",
                    "type=hls",
                    "cat-player/player"
                ]
                
                return any(pattern in iframe_src for pattern in valid_patterns)

            async def get_all_subdub_iframes(watch_page, episode_number):
                """Mendapatkan semua iframe untuk semua sub/dub yang tersedia"""
                # Dapatkan daftar sub/dub yang tersedia
                available_subdub = await get_available_subdub_from_dropdown(watch_page)
                
                # === PERUBAHAN PENTING: PRIORITAS CHINESE ===
                chinese_options = [subdub for subdub in available_subdub if 'chinese' in subdub.lower()]
                if chinese_options:
                    print(f"  🎯 DETECTED CHINESE CONTENT - Hanya ambil Chinese: {chinese_options}")
                    available_subdub = chinese_options  # Hanya proses Chinese saja
                # === END PERUBAHAN ===
                
                if not available_subdub:
                    print("  Tidak ada pilihan sub/dub, menggunakan iframe default")
                    iframe_element = await watch_page.query_selector("iframe.player")
                    current_iframe = await iframe_element.get_attribute("src") if iframe_element else "Iframe tidak ditemukan"
                    return {
                        "iframe_url": current_iframe,
                        "subdub_used": "Default",
                        "status": "success" if await is_iframe_valid(current_iframe) else "error",
                        "all_subdub_iframes": {available_subdub[0] if available_subdub else "Default": current_iframe}
                    }
                
                print(f"  Mengambil iframe untuk {len(available_subdub)} sub/dub: {available_subdub}")
                
                all_iframes = {}
                current_subdub = available_subdub[0]
                
                # Simpan iframe original terlebih dahulu
                iframe_element = await watch_page.query_selector("iframe.player")
                original_iframe = await iframe_element.get_attribute("src") if iframe_element else "Iframe tidak ditemukan"
                all_iframes[current_subdub] = original_iframe
                
                # Coba setiap sub/dub yang tersedia (kecuali yang pertama)
                for i, subdub in enumerate(available_subdub):
                    # Skip yang pertama karena itu yang sedang aktif
                    if i == 0:
                        continue
                        
                    print(f"  Mengambil iframe untuk: {subdub}")
                    
                    # Ganti sub/dub
                    success = await change_subdub_from_dropdown(watch_page, subdub)
                    if not success:
                        print(f"    Gagal mengganti ke {subdub}, lanjut...")
                        continue
                    
                    # Tunggu iframe loading
                    await asyncio.sleep(4)
                    
                    # Scrape iframe
                    iframe_element = await watch_page.query_selector("iframe.player")
                    iframe_src = await iframe_element.get_attribute("src") if iframe_element else None
                    
                    # Cek jika iframe valid
                    if await is_iframe_valid(iframe_src):
                        print(f"    ✓ Iframe valid ditemukan untuk {subdub}")
                        all_iframes[subdub] = iframe_src
                    else:
                        print(f"    ✗ Iframe tidak valid untuk {subdub}")
                        all_iframes[subdub] = "Iframe tidak valid"
                
                # Generate semua URL alternatif berdasarkan iframe yang berhasil
                all_subdub_urls = {}
                for subdub_name, iframe_url in all_iframes.items():
                    if await is_iframe_valid(iframe_url):
                        all_subdub_urls[subdub_name] = iframe_url
                        
                        # Hanya generate versi lain jika bukan Chinese content
                        if "ln=" in iframe_url and not any('chinese' in subdub_name.lower() for subdub_name in all_iframes.keys()):
                            base_iframe = iframe_url
                            # Generate Japanese version
                            jp_url = base_iframe.replace("ln=en-US", "ln=ja-JP").replace("ln=es-ES", "ln=ja-JP")
                            if "Japanese" not in all_subdub_urls and "Japanese" in available_subdub:
                                all_subdub_urls["Japanese (SUB)"] = jp_url
                            
                            # Generate English version  
                            en_url = base_iframe.replace("ln=ja-JP", "ln=en-US").replace("ln=es-ES", "ln=en-US")
                            if "English" not in all_subdub_urls and "English" in available_subdub:
                                all_subdub_urls["English (DUB)"] = en_url
                            
                            # Generate Spanish version
                            es_url = base_iframe.replace("ln=ja-JP", "ln=es-ES").replace("ln=en-US", "ln=es-ES")
                            if "Español" not in all_subdub_urls and any("Español" in s for s in available_subdub):
                                all_subdub_urls["Español (España)"] = es_url
                
                # Kembali ke subdub original
                if len(available_subdub) > 1:
                    await change_subdub_from_dropdown(watch_page, available_subdub[0])
                
                # Gunakan iframe yang paling valid sebagai primary
                primary_iframe = original_iframe
                primary_subdub = current_subdub
                status = "error"
                
                for subdub, iframe_url in all_iframes.items():
                    if await is_iframe_valid(iframe_url):
                        primary_iframe = iframe_url
                        primary_subdub = subdub
                        status = "success"
                        break
                
                return {
                    "iframe_url": primary_iframe,
                    "subdub_used": primary_subdub,
                    "status": status,
                    "all_subdub_iframes": all_subdub_urls
                }

            # ============================================================
            # FUNGSI BARU YANG LEBIH PINTAR UNTUK DETEKSI PAGES
            # ============================================================
            
            async def detect_pages_and_episodes(watch_page):
                """Mendeteksi pages dan total episodes dengan cara yang lebih akurat"""
                print("  → Mendeteksi pages dan episodes...")
                
                try:
                    # Tunggu episode list muncul
                    await asyncio.sleep(3)
                    await watch_page.wait_for_selector(".episode-list", timeout=15000)
                    
                    # **APPROACH 1: Cek apakah ada page dropdown**
                    has_page_dropdown = False
                    available_pages = []
                    
                    try:
                        page_dropdown = None
                        all_dropdowns = await watch_page.query_selector_all(".episode-list .v-select")
                        for dropdown in all_dropdowns:
                            label_element = await dropdown.query_selector(".v-label")
                            label_text = await label_element.inner_text() if label_element else ""
                            if "Page" in label_text:
                                page_dropdown = dropdown
                                break
                        
                        if page_dropdown:
                            has_page_dropdown = True
                            print("  → Page dropdown ditemukan, membaca opsi...")
                            
                            await asyncio.sleep(1)
                            await page_dropdown.click()
                            await asyncio.sleep(3)
                            
                            active_menu = await watch_page.query_selector(".v-menu__content.v-menu__content--active .v-list")
                            if active_menu:
                                options = await active_menu.query_selector_all(".v-list-item .v-list-item__title")
                                option_texts = []
                                for option in options:
                                    text = await option.inner_text()
                                    if text and text.strip():
                                        option_texts.append(text.strip())
                                
                                print(f"  → Opsi page ditemukan: {option_texts}")
                                
                                # Filter hanya pages yang valid
                                page_pattern = re.compile(r'^\s*(Page\s*)?(\d+-\d+)\s*$', re.IGNORECASE)
                                for opt in option_texts:
                                    match = page_pattern.match(opt)
                                    if match:
                                        page_range = match.group(2)
                                        available_pages.append(page_range)
                                
                                # Dapatkan current page
                                current_selection = await page_dropdown.query_selector(".v-select__selection.v-select__selection--comma")
                                current_page_text = await current_selection.inner_text() if current_selection else ""
                                
                                print(f"  → Available pages: {available_pages}")
                                print(f"  → Current page: {current_page_text}")
                            
                            await watch_page.keyboard.press("Escape")
                            await asyncio.sleep(1)
                            
                    except Exception as page_error:
                        print(f"  → Error membaca page dropdown: {page_error}")
                        has_page_dropdown = False
                    
                    # **APPROACH 2: Hitung episode langsung**
                    episode_items = await watch_page.query_selector_all(".episode-item")
                    direct_episode_count = len(episode_items)
                    print(f"  → Direct episode count: {direct_episode_count}")
                    
                    # **LOGIKA PENTING: Tentukan apakah benar-benar ada multiple pages**
                    if has_page_dropdown and available_pages:
                        # Ada page dropdown DAN available pages
                        if len(available_pages) > 1:
                            # BENAR-BENAR ada multiple pages
                            print("  → Multiple pages terdeteksi")
                            last_page = available_pages[-1]
                            try:
                                start_ep, end_ep = map(int, last_page.split('-'))
                                total_episodes = end_ep
                                episodes_per_page = end_ep - start_ep + 1
                                print(f"  → Total episodes dari last page: {total_episodes}")
                            except:
                                # Fallback: gunakan direct count
                                total_episodes = direct_episode_count
                                episodes_per_page = 5
                                print(f"  → Fallback ke direct count: {total_episodes}")
                        else:
                            # Hanya ada 1 page di dropdown, gunakan direct count
                            print("  → Hanya 1 page di dropdown, gunakan direct count")
                            total_episodes = direct_episode_count
                            available_pages = [f"01-{total_episodes:02d}"] if total_episodes > 0 else ["01-05"]
                            episodes_per_page = total_episodes
                    else:
                        # Tidak ada page dropdown, langsung gunakan direct count
                        print("  → Tidak ada page dropdown, gunakan direct count")
                        total_episodes = direct_episode_count
                        available_pages = [f"01-{total_episodes:02d}"] if total_episodes > 0 else ["01-05"]
                        episodes_per_page = total_episodes
                    
                    print(f"  → Final - Pages: {available_pages}, Total episodes: {total_episodes}")
                    
                    return {
                        "available_pages": available_pages,
                        "total_episodes": total_episodes,
                        "episodes_per_page": episodes_per_page,
                        "has_multiple_pages": len(available_pages) > 1
                    }
                    
                except Exception as e:
                    print(f"  → Error dalam detect_pages_and_episodes: {e}")
                    # Fallback ke direct count
                    episode_items = await watch_page.query_selector_all(".episode-item")
                    total_episodes = len(episode_items)
                    available_pages = [f"01-{total_episodes:02d}"] if total_episodes > 0 else ["01-05"]
                    
                    return {
                        "available_pages": available_pages,
                        "total_episodes": total_episodes,
                        "episodes_per_page": 5,
                        "has_multiple_pages": False
                    }

            # ============================================================
            # FUNGSI UNTUK NAVIGASI KE PAGE TERTENTU
            # ============================================================
            
            async def navigate_to_page(watch_page, target_page):
                """Navigasi ke page tertentu"""
                try:
                    print(f"  → Navigasi ke page: {target_page}")
                    
                    # Cari dropdown page
                    page_dropdown = None
                    all_dropdowns = await watch_page.query_selector_all(".episode-list .v-select")
                    for dropdown in all_dropdowns:
                        label_element = await dropdown.query_selector(".v-label")
                        label_text = await label_element.inner_text() if label_element else ""
                        if "Page" in label_text:
                            page_dropdown = dropdown
                            break
                    
                    if not page_dropdown:
                        print("  ! Page dropdown tidak ditemukan")
                        return False
                    
                    # Buka dropdown
                    await asyncio.sleep(1)
                    await page_dropdown.click()
                    await asyncio.sleep(3)
                    
                    # Cari dan klik page yang diinginkan
                    active_menu = await watch_page.query_selector(".v-menu__content.v-menu__content--active .v-list")
                    if not active_menu:
                        print("  ! Dropdown menu tidak terbuka")
                        await watch_page.keyboard.press("Escape")
                        return False
                    
                    page_option = None
                    options = await active_menu.query_selector_all(".v-list-item .v-list-item__title")
                    for option in options:
                        option_text = await option.inner_text()
                        if target_page in option_text:
                            page_option = option
                            break
                    
                    if page_option:
                        await page_option.click()
                        await asyncio.sleep(4)  # Tunggu loading
                        print(f"  ✓ Berhasil ganti ke page: {target_page}")
                        return True
                    else:
                        print(f"  ! Page {target_page} tidak ditemukan")
                        await watch_page.keyboard.press("Escape")
                        return False
                        
                except Exception as e:
                    print(f"  ! Gagal navigasi ke page {target_page}: {e}")
                    return False

            # ============================================================
            # FUNGSI UNTUK MENDAPATKAN EPISODE ITEMS DENGAN REFRESH
            # ============================================================
            
            async def get_fresh_episode_items(watch_page):
                """Mendapatkan episode items yang fresh (tidak stale)"""
                try:
                    await asyncio.sleep(2)
                    await watch_page.wait_for_selector(".episode-item", timeout=10000)
                    episode_items = await watch_page.query_selector_all(".episode-item")
                    print(f"  → Refreshed episode items: {len(episode_items)} episodes")
                    return episode_items
                except Exception as e:
                    print(f"  ! Gagal mendapatkan fresh episode items: {e}")
                    return []

            # ============================================================
            # FUNGSI UNTUK SCRAPE EPISODE DENGAN MULTIPLE PAGES SUPPORT
            # ============================================================
            
            async def scrape_episodes_with_pages(watch_page, page_info, existing_episodes=[]):
                """Scrape episodes dengan support multiple pages dan resume capability"""
                available_pages = page_info["available_pages"]
                total_episodes = page_info["total_episodes"]
                episodes_per_page = page_info["episodes_per_page"]
                has_multiple_pages = page_info["has_multiple_pages"]
                
                episodes_data = existing_episodes.copy()
                total_scraped = 0
                max_episodes_per_run = 20  # Batas episode per run
                
                print(f"  → Memulai scraping {total_episodes} episode di {len(available_pages)} pages...")
                
                # **TENTUKAN PAGE YANG PERLU DI-SCRAPE**
                pages_to_scrape = []
                
                if not has_multiple_pages or len(available_pages) == 1:
                    # Single page, langsung scrape
                    pages_to_scrape = available_pages
                else:
                    # Multiple pages, cari page yang belum selesai
                    for page in available_pages:
                        # Hitung range episode di page ini
                        start_ep, end_ep = map(int, page.split('-'))
                        page_start_index = start_ep - 1
                        page_end_index = end_ep
                        
                        # Cek apakah semua episode di page ini sudah sukses
                        all_episodes_success = True
                        for ep_index in range(page_start_index, page_end_index):
                            if (ep_index >= len(episodes_data) or 
                                episodes_data[ep_index].get('status') != 'success'):
                                all_episodes_success = False
                                break
                        
                        if not all_episodes_success:
                            pages_to_scrape.append(page)
                            print(f"  → Page {page} perlu di-scrape")
                        else:
                            print(f"  → Page {page} sudah selesai, skip")
                
                print(f"  → Total pages yang perlu di-scrape: {len(pages_to_scrape)}")
                
                # **PROSES SETIAP PAGE YANG PERLU DI-SCRAPE**
                for page_index, target_page in enumerate(pages_to_scrape):
                    if total_scraped >= max_episodes_per_run:
                        print(f"  → Batas {max_episodes_per_run} episode tercapai, stop scraping")
                        break
                    
                    print(f"\n  📄 Memproses Page: {target_page}")
                    
                    # **Navigasi ke page target jika diperlukan**
                    if has_multiple_pages and page_index > 0:
                        success = await navigate_to_page(watch_page, target_page)
                        if not success:
                            print(f"  ! Gagal navigasi ke page {target_page}, skip page ini")
                            continue
                    
                    # **PERBAIKAN PENTING: Dapatkan FRESH episode items setiap page**
                    episode_items = await get_fresh_episode_items(watch_page)
                    if not episode_items:
                        print(f"  ! Tidak ada episode items di page {target_page}, skip")
                        continue
                    
                    episodes_in_current_page = len(episode_items)
                    print(f"  → Found {episodes_in_current_page} episodes in page {target_page}")
                    
                    # **Tentukan range episode di page ini**
                    if '-' in target_page:
                        try:
                            start_ep, end_ep = map(int, target_page.split('-'))
                            page_start_index = start_ep - 1
                            page_end_index = end_ep
                        except:
                            page_start_index = page_index * episodes_per_page
                            page_end_index = page_start_index + episodes_in_current_page
                    else:
                        page_start_index = page_index * episodes_per_page
                        page_end_index = page_start_index + episodes_in_current_page
                    
                    print(f"  → Page covers episodes {page_start_index + 1}-{page_end_index}")
                    
                    # **PROSES SETIAP EPISODE DI PAGE INI**
                    for local_ep_index in range(episodes_in_current_page):
                        global_ep_index = page_start_index + local_ep_index
                        
                        # Cek batas max episodes per run
                        if total_scraped >= max_episodes_per_run:
                            print(f"  → Batas {max_episodes_per_run} episode tercapai, stop scraping")
                            break
                        
                        # Cek apakah episode ini perlu di-scrape
                        if (global_ep_index < len(episodes_data) and 
                            episodes_data[global_ep_index].get('status') == 'success'):
                            # Episode sudah sukses, skip
                            continue
                        
                        try:
                            print(f"\n  --- Memproses Episode {global_ep_index + 1} (Page {target_page}) ---")
                            
                            # **PERBAIKAN PENTING: Dapatkan FRESH episode items setiap episode**
                            episode_items = await get_fresh_episode_items(watch_page)
                            if local_ep_index >= len(episode_items):
                                print(f"    × Episode tidak ditemukan di page ini")
                                continue
                            
                            ep_item = episode_items[local_ep_index]
                            
                            if not ep_item:
                                print(f"    × Gagal menemukan episode")
                                continue
                                
                            # Dapatkan nomor episode
                            ep_badge = await ep_item.query_selector(".episode-badge .v-chip__content")
                            ep_number = await ep_badge.inner_text() if ep_badge else f"EP {global_ep_index + 1}"
                            
                            print(f"  - Mengklik episode {ep_number}...")
                            
                            # **Klik episode**
                            clicked = False
                            for attempt in range(3):
                                try:
                                    await ep_item.scroll_into_view_if_needed()
                                    await asyncio.sleep(1)
                                    await ep_item.click()
                                    await asyncio.sleep(3)
                                    
                                    # Cek apakah berhasil navigasi ke episode
                                    current_url = watch_page.url
                                    if "/ep-" in current_url:
                                        clicked = True
                                        break
                                except Exception as click_error:
                                    print(f"    ! Click attempt {attempt+1} failed: {click_error}")
                                    if attempt < 2:
                                        await asyncio.sleep(2)
                            
                            if not clicked:
                                print(f"    × Gagal mengklik episode {ep_number}")
                                # Tetap simpan data error
                                episode_data = {
                                    "number": ep_number,
                                    "iframe": "Gagal diambil",
                                    "subdub": "None",
                                    "status": "error",
                                    "all_qualities": {}
                                }
                                
                                if global_ep_index < len(episodes_data):
                                    episodes_data[global_ep_index] = episode_data
                                else:
                                    episodes_data.append(episode_data)
                                
                                total_scraped += 1
                                continue

                            # **Ambil iframe dengan semua sub/dub options**
                            print(f"    → Mengambil iframe dengan semua sub/dub options...")
                            iframe_info = await get_all_subdub_iframes(watch_page, ep_number)
                            
                            episode_data = {
                                "number": ep_number,
                                "iframe": iframe_info["iframe_url"],
                                "subdub": iframe_info["subdub_used"],
                                "status": iframe_info["status"],
                                "all_qualities": iframe_info.get("all_subdub_iframes", {})
                            }
                            
                            # Update atau tambah episode data
                            if global_ep_index < len(episodes_data):
                                episodes_data[global_ep_index] = episode_data
                            else:
                                episodes_data.append(episode_data)
                            
                            total_scraped += 1
                            
                            if iframe_info["status"] == "success":
                                print(f"    ✓ Episode {ep_number} berhasil di-scrape")
                                print(f"    → Sub/Dub: {iframe_info['subdub_used']}")
                                print(f"    → All options: {list(iframe_info.get('all_subdub_iframes', {}).keys())}")
                            else:
                                print(f"    × Episode {ep_number} gagal (iframe not found)")
                                
                        except Exception as ep_e:
                            print(f"    × Gagal memproses episode {global_ep_index + 1}: {type(ep_e).__name__}: {ep_e}")
                            
                            episode_data = {
                                "number": f"EP {global_ep_index + 1}",
                                "iframe": "Gagal diambil",
                                "subdub": "None",
                                "status": "error",
                                "all_qualities": {}
                            }
                            
                            if global_ep_index < len(episodes_data):
                                episodes_data[global_ep_index] = episode_data
                            else:
                                episodes_data.append(episode_data)
                            
                            total_scraped += 1
                            continue
                
                return episodes_data, total_scraped

            # ============================================================
            # END FUNGSI BARU
            # ============================================================

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
                    await asyncio.sleep(2)
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
                        await asyncio.sleep(1)
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
                    await asyncio.sleep(3)
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
                    await asyncio.sleep(3)
                    await watch_page.wait_for_selector(".player-container", timeout=30000)
                    
                    # **PERBAIKAN: Gunakan fungsi baru untuk deteksi pages dan episodes**
                    page_info = await detect_pages_and_episodes(watch_page)
                    
                    available_pages = page_info["available_pages"]
                    total_episodes = page_info["total_episodes"]
                    episodes_per_page = page_info["episodes_per_page"]
                    has_multiple_pages = page_info["has_multiple_pages"]
                    
                    # Deteksi sub/dub
                    available_subdub = await get_available_subdub_from_dropdown(watch_page)
                    current_subdub = available_subdub[0] if available_subdub else "Japanese (SUB)"
                    optimal_subdub = current_subdub

                    # **PERBAIKAN UTAMA: Gunakan fungsi scrape dengan multiple pages support**
                    existing_episodes = existing_anime.get('episodes', []) if existing_anime else []
                    
                    if not existing_anime or anime_needs_update:
                        print(f"  → Memulai scraping {total_episodes} episode...")
                        episodes_data, total_scraped = await scrape_episodes_with_pages(
                            watch_page, page_info, existing_episodes
                        )
                    else:
                        episodes_data = existing_episodes
                        total_scraped = 0
                        print("  → Anime sudah up-to-date, skip scraping episodes")

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
                        "available_pages": available_pages,
                        "episodes_per_page": episodes_per_page,
                        "has_multiple_pages": has_multiple_pages,
                        "last_updated": time.time()
                    }
                    
                    # Update atau tambah data baru
                    if existing_anime:
                        existing_anime.update(anime_info)
                        scraped_data.append(existing_anime)
                    else:
                        scraped_data.append(anime_info)
                    
                    success_count = sum(1 for ep in episodes_data if ep.get('status') in ['success'])
                    current_episode_count = len([ep for ep in episodes_data if ep.get('status') != 'pending'])
                    
                    print(f"✓ Data {title} {'diperbarui' if existing_anime else 'ditambahkan'} ({success_count}/{current_episode_count} berhasil, {current_episode_count - success_count} error)")
                    print(f"  → Progress: {current_episode_count}/{total_episodes} episode ({current_episode_count/total_episodes*100:.1f}%)")
                    print(f"  → Optimal sub/dub: {optimal_subdub}")
                    print(f"  → Multiple pages: {has_multiple_pages}")
                    print(f"  → Pages: {available_pages}")
                    
                except Exception as e:
                    print(f"!!! Gagal memproses item #{index + 1}: {type(e).__name__}: {e}")
                    if existing_anime:
                        scraped_data.append(existing_anime)
                        print(f"  → Tetap menyimpan data existing untuk {existing_anime.get('title')}")
                
                finally:
                    # **PERBAIKAN: Pastikan page ditutup dengan benar**
                    try:
                        if watch_page and not watch_page.is_closed():
                            await watch_page.close()
                    except:
                        pass
                    
                    try:
                        if detail_page and not detail_page.is_closed():
                            await detail_page.close()
                    except:
                        pass

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
