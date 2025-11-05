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
                    
                    # **PERBAIKAN: Approach baru untuk deteksi dropdown**
                    available_subdub = []
                    current_subdub = None
                    optimal_subdub = None
                    available_pages = []
                    current_page = "01-05"
                    episodes_per_page = 5
                    total_episodes = 5
                    
                    try:
                        # **APPROACH 1: Cari semua dropdown di area episode list**
                        print("  → Mencari dropdown di area episode list...")
                        
                        # Tunggu episode list container
                        await watch_page.wait_for_selector(".episode-list", timeout=10000)
                        
                        # Cari semua dropdown di dalam episode list
                        all_dropdowns = await watch_page.query_selector_all(".episode-list .v-select")
                        print(f"  → Ditemukan {len(all_dropdowns)} dropdown di episode list")
                        
                        for i, dropdown in enumerate(all_dropdowns):
                            try:
                                # Dapatkan label dropdown
                                label_element = await dropdown.query_selector(".v-label")
                                label_text = await label_element.inner_text() if label_element else f"Dropdown {i+1}"
                                print(f"  → Dropdown {i+1}: {label_text}")
                                
                                # Dapatkan nilai saat ini
                                current_selection = await dropdown.query_selector(".v-select__selection.v-select__selection--comma")
                                current_value = await current_selection.inner_text() if current_selection else "Tidak diketahui"
                                print(f"  → Nilai saat ini: {current_value}")
                                
                                # Buka dropdown dengan delay
                                await asyncio.sleep(1)
                                await dropdown.click()
                                await asyncio.sleep(3)  # Delay lebih panjang untuk load opsi
                                
                                # Ambil opsi dari dropdown yang aktif
                                active_menu = await watch_page.query_selector(".v-menu__content.v-menu__content--active .v-list")
                                if active_menu:
                                    options = await active_menu.query_selector_all(".v-list-item .v-list-item__title")
                                    option_texts = []
                                    for option in options:
                                        text = await option.inner_text()
                                        if text and text.strip():
                                            option_texts.append(text.strip())
                                    
                                    print(f"  → Opsi ditemukan (raw): {option_texts}")
                                    
                                    # Klasifikasikan berdasarkan label
                                    if "Sub/Dub" in label_text:
                                        valid_keywords = ['Japanese', 'English', 'Español', 'SUB', 'DUB']
                                        filtered = [opt for opt in option_texts if any(kw in opt for kw in valid_keywords)]
                                        available_subdub = filtered
                                        current_subdub = current_value
                                        optimal_subdub = next((opt for opt in filtered if "Japanese (SUB)" in opt), filtered[0] if filtered else "Japanese (SUB)")
                                        print(f"  → Sub/Dub tersedia: {available_subdub}")
                                        print(f"  → Sub/Dub optimal: {optimal_subdub}")
                                    
                                    elif "Page" in label_text:
                                        page_pattern = re.compile(r'^\s*(Page\s*)?(\d+-\d+)\s*$', re.IGNORECASE)
                                        filtered = []
                                        for opt in option_texts:
                                            match = page_pattern.match(opt)
                                            if match:
                                                filtered.append(match.group(2))
                                        available_pages = filtered
                                        current_page = current_value.strip()
                                        if 'Page ' in current_page:
                                            current_page = current_page.split('Page ')[1]
                                        print(f"  → Pages tersedia: {filtered}")
                                        print(f"  → Page saat ini: {current_page}")
                                        
                                        if available_pages:
                                            last_page = available_pages[-1]
                                            try:
                                                start_ep, end_ep = map(int, last_page.split('-'))
                                                total_episodes = end_ep
                                                episodes_per_page = end_ep - start_ep + 1
                                                print(f"  → Total episodes: {total_episodes}")
                                            except:
                                                total_episodes = len(available_pages) * episodes_per_page
                                                print(f"  → Estimated total episodes: {total_episodes}")
                                
                                # Tutup dropdown
                                await watch_page.keyboard.press("Escape")
                                await asyncio.sleep(1)
                                
                            except Exception as e:
                                print(f"  → Error memproses dropdown {i+1}: {e}")
                                await watch_page.keyboard.press("Escape")
                                await asyncio.sleep(1)
                        
                        # **APPROACH 2: Jika masih kosong, coba approach alternatif**
                        if not available_subdub or not available_pages:
                            print("  → Mencoba approach alternatif...")
                            
                            episode_items = await watch_page.query_selector_all(".episode-item")
                            total_episodes = len(episode_items)
                            print(f"  → Fallback: {total_episodes} episode ditemukan")
                            
                            # Set default values
                            if not available_subdub:
                                available_subdub = [current_subdub] if current_subdub else ["Japanese (SUB)"]
                                optimal_subdub = optimal_subdub or "Japanese (SUB)"
                            
                            if not available_pages:
                                available_pages = [f"01-{total_episodes:02d}"] if total_episodes > 0 else ["01-05"]
                                current_page = available_pages[0]
                            
                    except Exception as e:
                        print(f"  → Error utama detect dropdown: {e}")
                        # Fallback values
                        episode_items = await watch_page.query_selector_all(".episode-item")
                        total_episodes = len(episode_items)
                        available_subdub = [current_subdub] if current_subdub else ["Japanese (SUB)"]
                        optimal_subdub = optimal_subdub or "Japanese (SUB)"
                        available_pages = [f"01-{total_episodes:02d}"] if total_episodes > 0 else ["01-05"]
                        current_page = available_pages[0]

                    # **PERBAIKAN UTAMA: LOGIKA UNTUK MENGAMBIL SEMUA EPISODE**
                    episodes_data = existing_anime.get('episodes', []) if existing_anime else []
                    total_scraped_in_this_run = 0
                    max_episodes_per_run = 50  # Batas 50 episode

                    # **LOGIKA MULTI-PAGE YANG DIPERBAIKI**
                    if not available_pages:
                        # Jika tidak ada pages, buat satu page berdasarkan episode yang terlihat
                        episode_items = await watch_page.query_selector_all(".episode-item")
                        total_episodes = len(episode_items)
                        available_pages = [f"01-{total_episodes:02d}"] if total_episodes > 0 else ["01-05"]
                        current_page = available_pages[0]

                    print(f"\n  🚀 Memulai scraping {len(available_pages)} pages...")
                    print(f"  → Total episodes yang akan di-scrape: {total_episodes}")

                    # **BUAT LIST SEMUA EPISODE YANG PERLU DI-SCRAPE**
                    all_episodes_to_scrape = []
                    
                    for page_index, target_page in enumerate(available_pages):
                        print(f"\n  📄 Memproses Page: {target_page}")
                        
                        # **Ganti page jika diperlukan**
                        if len(available_pages) > 1 and current_page != target_page:
                            print(f"  → Mengganti ke page: {target_page}")
                            try:
                                # Cari dropdown page
                                page_dropdown = None
                                all_dropdowns = await watch_page.query_selector_all(".episode-list .v-select")
                                for dropdown in all_dropdowns:
                                    label_element = await dropdown.query_selector(".v-label")
                                    label_text = await label_element.inner_text() if label_element else ""
                                    if "Page" in label_text:
                                        page_dropdown = dropdown
                                        break
                                
                                if page_dropdown:
                                    await asyncio.sleep(1)
                                    await page_dropdown.click()
                                    await asyncio.sleep(3)
                                    
                                    # Cari dan klik page yang diinginkan
                                    active_menu = await watch_page.query_selector(".v-menu__content.v-menu__content--active .v-list")
                                    if active_menu:
                                        page_option = None
                                        options = await active_menu.query_selector_all(".v-list-item .v-list-item__title")
                                        for option in options:
                                            option_text = await option.inner_text()
                                            if target_page in option_text:  # Lebih fleksibel
                                                page_option = option
                                                break
                                        
                                        if page_option:
                                            await page_option.click()
                                            await asyncio.sleep(4)  # Delay lebih panjang setelah switch
                                            current_page = target_page
                                            print(f"  ✓ Berhasil ganti ke page: {target_page}")
                                        else:
                                            print(f"  ! Page {target_page} tidak ditemukan, skip")
                                            continue
                                    else:
                                        print(f"  ! Dropdown menu tidak terbuka, skip")
                                        continue
                                else:
                                    print(f"  ! Page dropdown tidak ditemukan, skip")
                                    continue
                            except Exception as page_error:
                                print(f"  ! Gagal ganti page: {page_error}")
                                continue

                        # **Tunggu dan dapatkan episode items**
                        try:
                            await asyncio.sleep(2)  # Delay
                            await watch_page.wait_for_selector(".episode-item", timeout=15000)
                        except Exception as e:
                            print(f"  ! Timeout menunggu episode items: {e}")
                            continue

                        episode_items = await watch_page.query_selector_all(".episode-item")
                        episodes_in_current_page = len(episode_items)
                        
                        print(f"  → Found {episodes_in_current_page} episodes in page {current_page}")

                        # **Hitung range episode untuk page ini**
                        if '-' in target_page:
                            try:
                                start_ep, end_ep = map(int, target_page.split('-'))
                                page_start_episode = start_ep - 1
                                page_end_episode = end_ep
                            except:
                                page_start_episode = page_index * episodes_per_page
                                page_end_episode = page_start_episode + episodes_in_current_page
                        else:
                            page_start_episode = page_index * episodes_per_page
                            page_end_episode = page_start_episode + episodes_in_current_page
                        
                        print(f"  → Page covers episodes {page_start_episode + 1}-{page_end_episode}")

                        # **Tambah semua episode di page ini ke list yang perlu di-scrape**
                        for ep_index in range(episodes_in_current_page):
                            global_ep_index = page_start_episode + ep_index
                            
                            # Cek apakah episode ini perlu di-scrape
                            if global_ep_index >= len(episodes_data) or episodes_data[global_ep_index].get('status') in ['error', 'pending']:
                                all_episodes_to_scrape.append({
                                    'page_index': page_index,
                                    'local_ep_index': ep_index,
                                    'global_ep_index': global_ep_index,
                                    'target_page': target_page
                                })

                    print(f"\n  → Total episode yang perlu di-scrape: {len(all_episodes_to_scrape)}")

                    # **PROSES SEMUA EPISODE YANG PERLU DI-SCRAPE**
                    for ep_data in all_episodes_to_scrape:
                        page_index = ep_data['page_index']
                        local_ep_index = ep_data['local_ep_index']
                        global_ep_index = ep_data['global_ep_index']
                        target_page = ep_data['target_page']
                        
                        # Cek batas max episodes per run
                        if total_scraped_in_this_run >= max_episodes_per_run:
                            print(f"  → Batas {max_episodes_per_run} episode tercapai, stop scraping")
                            break

                        # **Navigasi ke page yang benar jika diperlukan**
                        current_episode_page = available_pages[page_index]
                        if current_page != current_episode_page:
                            print(f"  → Navigasi ke page: {current_episode_page}")
                            try:
                                # Sama seperti atas, reuse code jika perlu
                                page_dropdown = None
                                all_dropdowns = await watch_page.query_selector_all(".episode-list .v-select")
                                for dropdown in all_dropdowns:
                                    label_element = await dropdown.query_selector(".v-label")
                                    label_text = await label_element.inner_text() if label_element else ""
                                    if "Page" in label_text:
                                        page_dropdown = dropdown
                                        break
                                
                                if page_dropdown:
                                    await asyncio.sleep(1)
                                    await page_dropdown.click()
                                    await asyncio.sleep(3)
                                    
                                    active_menu = await watch_page.query_selector(".v-menu__content.v-menu__content--active .v-list")
                                    if active_menu:
                                        page_option = None
                                        options = await active_menu.query_selector_all(".v-list-item .v-list-item__title")
                                        for option in options:
                                            option_text = await option.inner_text()
                                            if current_episode_page in option_text:
                                                page_option = option
                                                break
                                        
                                        if page_option:
                                            await page_option.click()
                                            await asyncio.sleep(4)
                                            current_page = current_episode_page
                                            print(f"  ✓ Berhasil ganti ke page: {current_episode_page}")
                                        else:
                                            print(f"  ! Page {current_episode_page} tidak ditemukan, skip episode")
                                            continue
                                    else:
                                        print(f"  ! Dropdown menu tidak terbuka, skip episode")
                                        continue
                                else:
                                    print(f"  ! Page dropdown tidak ditemukan, skip episode")
                                    continue
                            except Exception as page_error:
                                print(f"  ! Gagal ganti page: {page_error}")
                                continue

                        try:
                            print(f"\n  --- Memproses Episode {global_ep_index + 1} (Page {current_episode_page}) ---")
                            
                            # Refresh episode items
                            await asyncio.sleep(2)  # Delay
                            episode_items = await watch_page.query_selector_all(".episode-item")
                            
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
                            for attempt in range(5):  # Retry lebih
                                try:
                                    await ep_item.scroll_into_view_if_needed()
                                    await asyncio.sleep(1)
                                    await ep_item.click()
                                    await asyncio.sleep(4)  # Delay lebih panjang setelah klik
                                    
                                    # Cek apakah berhasil navigasi ke episode
                                    current_url = watch_page.url
                                    if "/ep-" in current_url:
                                        clicked = True
                                        break
                                except Exception as click_error:
                                    print(f"    ! Click attempt {attempt+1} failed: {click_error}")
                                    if attempt < 4:
                                        await asyncio.sleep(2)
                            
                            if not clicked:
                                print(f"    × Gagal mengklik episode setelah 5 attempts")
                                continue

                            # **Cari iframe dengan auto-switch sub/dub jika gagal**
                            iframe_src = None
                            status = "error"
                            subdub_attempts = [current_subdub] + [opt for opt in available_subdub if opt != current_subdub]  # Prioritas current, lalu lain
                            for subdub in subdub_attempts:
                                if subdub != current_subdub:
                                    print(f"    → Iframe gagal di {current_subdub}, coba switch ke {subdub}")
                                    try:
                                        # Cari dropdown sub/dub
                                        subdub_dropdown = None
                                        all_dropdowns = await watch_page.query_selector_all(".episode-list .v-select")
                                        for dropdown in all_dropdowns:
                                            label_element = await dropdown.query_selector(".v-label")
                                            label_text = await label_element.inner_text() if label_element else ""
                                            if "Sub/Dub" in label_text:
                                                subdub_dropdown = dropdown
                                                break
                                        
                                        if subdub_dropdown:
                                            await asyncio.sleep(1)
                                            await subdub_dropdown.click()
                                            await asyncio.sleep(3)
                                            
                                            active_menu = await watch_page.query_selector(".v-menu__content.v-menu__content--active .v-list")
                                            if active_menu:
                                                subdub_option = None
                                                options = await active_menu.query_selector_all(".v-list-item .v-list-item__title")
                                                for option in options:
                                                    option_text = await option.inner_text()
                                                    if subdub in option_text:
                                                        subdub_option = option
                                                        break
                                                
                                                if subdub_option:
                                                    await subdub_option.click()
                                                    await asyncio.sleep(7)  # Delay lebih panjang setelah switch (handle URL change)
                                                    current_subdub = subdub
                                                    optimal_subdub = subdub  # Update optimal
                                                    print(f"    ✓ Berhasil switch ke {subdub}")
                                                else:
                                                    print(f"    ! Opsi {subdub} tidak ditemukan")
                                                    continue
                                            else:
                                                print(f"    ! Dropdown menu tidak terbuka")
                                                continue
                                        else:
                                            print(f"    ! Sub/Dub dropdown tidak ditemukan")
                                            continue
                                    except Exception as switch_error:
                                        print(f"    ! Gagal switch sub/dub: {switch_error}")
                                        continue

                                # Perbaikan: Setelah switch, refresh episode items dan klik ulang episode berdasarkan ep_number (handle URL change)
                                await asyncio.sleep(3)  # Delay setelah switch
                                episode_items = await watch_page.query_selector_all(".episode-item")
                                found_ep_item = None
                                for item in episode_items:
                                    badge = await item.query_selector(".episode-badge .v-chip__content")
                                    if badge and await badge.inner_text() == ep_number:
                                        found_ep_item = item
                                        break
                                
                                if found_ep_item:
                                    print(f"    → Re-click episode {ep_number} setelah switch (handle URL change)")
                                    await found_ep_item.scroll_into_view_if_needed()
                                    await asyncio.sleep(1)
                                    await found_ep_item.click()
                                    await asyncio.sleep(5)  # Delay load iframe baru
                                else:
                                    print(f"    ! Episode {ep_number} tidak ditemukan setelah switch, skip")
                                    continue

                                # Coba ambil iframe
                                for iframe_attempt in range(5):
                                    try:
                                        await asyncio.sleep(2)  # Delay per attempt
                                        iframe_element = await watch_page.query_selector("iframe.player:not([src=''])")
                                        if iframe_element:
                                            iframe_src = await iframe_element.get_attribute("src")
                                            if iframe_src and iframe_src != "about:blank":
                                                status = "success"
                                                break
                                    except Exception as iframe_err:
                                        print(f"    ! Iframe attempt {iframe_attempt+1}: {iframe_err}")
                                
                                if status == "success":
                                    break  # Keluar loop subdub jika sukses

                            if status != "success":
                                print(f"    × Gagal ambil iframe setelah coba semua sub/dub")

                            # Simpan data episode
                            episode_data = {
                                "number": ep_number,
                                "iframe": iframe_src or "Gagal diambil",
                                "subdub": current_subdub or "None",
                                "status": status,
                                "all_qualities": {"Current": iframe_src} if iframe_src else {}
                            }
                            
                            # Update atau tambah episode data
                            if global_ep_index < len(episodes_data):
                                episodes_data[global_ep_index] = episode_data
                            else:
                                episodes_data.append(episode_data)
                            
                            total_scraped_in_this_run += 1
                            if status == "success":
                                print(f"    ✓ Episode {ep_number} berhasil di-scrape (iframe OK)")
                            else:
                                print(f"    × Episode {ep_number} gagal (iframe not found)")
                            
                        except Exception as ep_e:
                            print(f"    × Gagal memproses episode {global_ep_index + 1}: {type(ep_e).__name__}: {ep_e}")
                            
                            episode_data = {
                                "number": f"EP {global_ep_index + 1}",
                                "iframe": "Gagal diambil",
                                "subdub": current_subdub or "None",
                                "status": "error",
                                "all_qualities": {}
                            }
                            
                            if global_ep_index < len(episodes_data):
                                episodes_data[global_ep_index] = episode_data
                            else:
                                episodes_data.append(episode_data)
                            
                            total_scraped_in_this_run += 1
                            continue

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
                    print(f"  → Total pages: {len(available_pages)}")
                    
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
