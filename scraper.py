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
            # FUNGSI DARI SCRIPT LAMA UNTUK HANDLE SUB/DUB (TIDAK DIUBAH)
            # ============================================================
            
            async def get_available_subdub_from_dropdown(watch_page):
                """Mendapatkan daftar sub/dub yang tersedia dengan MEMBACA DROPDOWN YANG BENAR"""
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
                            label_el = await dropdown.query_selector(".v-label")
                            label_text = await label_el.inner_text() if label_el else ""
                            if "Sub/Dub" in label_text:
                                print(f"Dropdown Sub/Dub ditemukan dengan selector: {selector}")
                                break
                    
                    if not dropdown:
                        print("Dropdown Sub/Dub tidak ditemukan di episode list")
                        return []
                    
                    await dropdown.click()
                    await asyncio.sleep(2)
                    
                    option_selectors = [
                        "//div[contains(@class, 'v-menu__content--active')]//div[contains(@class, 'v-list-item__title')]",
                        ".v-menu__content--active .v-list-item .v-list-item__title"
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
                                    if any(keyword in option_text.lower() for keyword in ['japanese', 'english', 'chinese', 'español', 'sub', 'dub']):
                                        subdub_options.append(option_text.strip())
                            if subdub_options:
                                break
                    
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
                    dropdown_selectors = [
                        "//div[contains(@class, 'episode-list')]//div[contains(@class, 'v-select')]",
                    ]
                    
                    dropdown = None
                    for selector in dropdown_selectors:
                        temp_dropdown = await watch_page.query_selector(f"xpath={selector}")
                        if temp_dropdown:
                            label_el = await temp_dropdown.query_selector(".v-label")
                            if label_el and "Sub/Dub" in await label_el.inner_text():
                                dropdown = temp_dropdown
                                break
                    
                    if not dropdown:
                        print("Dropdown tidak ditemukan untuk mengganti sub/dub")
                        return False
                    
                    await dropdown.click()
                    await asyncio.sleep(2)
                    
                    target_option = await watch_page.query_selector(f"//div[contains(@class, 'v-menu__content--active')]//div[contains(@class, 'v-list-item__title') and contains(text(), '{target_subdub}')]")
                    
                    if target_option:
                        await target_option.click()
                        await asyncio.sleep(4)
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
                if not iframe_src or iframe_src in ["Iframe tidak ditemukan", "Iframe tidak tersedia", "Iframe tidak valid"]:
                    return False
                valid_patterns = ["krussdomi.com/cat-player/player", "vidstream", "type=hls", "cat-player/player"]
                return any(pattern in iframe_src for pattern in valid_patterns)

            async def get_all_subdub_iframes(watch_page, episode_number):
                available_subdub = await get_available_subdub_from_dropdown(watch_page)
                
                if not available_subdub:
                    print("  Tidak ada pilihan sub/dub, menggunakan iframe default")
                    iframe_element = await watch_page.query_selector("iframe.player")
                    current_iframe = await iframe_element.get_attribute("src") if iframe_element else "Iframe tidak ditemukan"
                    return {
                        "iframe_url": current_iframe, "subdub_used": "Default",
                        "status": "success" if await is_iframe_valid(current_iframe) else "error",
                        "all_subdub_iframes": {"Default": current_iframe}
                    }
                
                print(f"  Mengambil iframe untuk {len(available_subdub)} sub/dub: {available_subdub}")
                
                all_iframes = {}
                original_subdub = available_subdub[0]
                
                iframe_element = await watch_page.query_selector("iframe.player")
                original_iframe = await iframe_element.get_attribute("src") if iframe_element else "Iframe tidak ditemukan"
                all_iframes[original_subdub] = original_iframe
                
                for subdub in available_subdub:
                    if subdub == original_subdub:
                        continue
                    print(f"  Mengambil iframe untuk: {subdub}")
                    if await change_subdub_from_dropdown(watch_page, subdub):
                        await asyncio.sleep(4)
                        iframe_element = await watch_page.query_selector("iframe.player")
                        iframe_src = await iframe_element.get_attribute("src") if iframe_element else "Iframe tidak ditemukan"
                        all_iframes[subdub] = iframe_src if await is_iframe_valid(iframe_src) else "Iframe tidak valid"
                
                if len(available_subdub) > 1:
                    await change_subdub_from_dropdown(watch_page, original_subdub)
                
                primary_iframe, primary_subdub, status = original_iframe, original_subdub, "error"
                for subdub, iframe_url in all_iframes.items():
                    if await is_iframe_valid(iframe_url):
                        primary_iframe, primary_subdub, status = iframe_url, subdub, "success"
                        break
                
                return {
                    "iframe_url": primary_iframe, "subdub_used": primary_subdub,
                    "status": status, "all_subdub_iframes": all_iframes
                }
            
            # --- PERBAIKAN ---
            # ============================================================
            # FUNGSI DETEKSI PAGES YANG LEBIH AKURAT
            # ============================================================
            async def detect_pages_and_episodes(watch_page):
                """Mendeteksi pages dan total episodes dengan cara yang lebih akurat"""
                print("  → Mendeteksi pages dan episodes...")
                
                try:
                    await asyncio.sleep(3)
                    await watch_page.wait_for_selector(".episode-list", timeout=15000)
                    
                    has_page_dropdown = False
                    available_pages = []
                    page_dropdown = None

                    try:
                        all_dropdowns = await watch_page.query_selector_all(".episode-list .v-select")
                        for dropdown in all_dropdowns:
                            label_element = await dropdown.query_selector(".v-label")
                            if label_element:
                                label_text = await label_element.inner_text()
                                if "Page" in label_text:
                                    page_dropdown = dropdown
                                    print("  → Dropdown 'Page' yang benar ditemukan.")
                                    break
                        
                        if page_dropdown:
                            has_page_dropdown = True
                            print("  → Membaca opsi dari dropdown 'Page'...")
                            
                            await asyncio.sleep(1)
                            await page_dropdown.click()
                            await asyncio.sleep(3)
                            
                            active_menu = await watch_page.query_selector(".v-menu__content--active .v-list")
                            if active_menu:
                                options = await active_menu.query_selector_all(".v-list-item .v-list-item__title")
                                option_texts = [await option.inner_text() for option in options if await option.inner_text()]
                                
                                print(f"  → Opsi mentah ditemukan: {option_texts}")
                                
                                page_pattern = re.compile(r'^\s*(\d+-\d+)\s*$')
                                for opt in option_texts:
                                    match = page_pattern.match(opt.strip())
                                    if match:
                                        available_pages.append(match.group(1))
                                
                                print(f"  → Halaman yang tersedia (setelah filter): {available_pages}")
                            
                            await watch_page.keyboard.press("Escape")
                            await asyncio.sleep(1)
                        else:
                             print("  → Dropdown spesifik untuk 'Page' tidak ditemukan.")

                    except Exception as page_error:
                        print(f"  → Error saat membaca page dropdown: {page_error}")
                        has_page_dropdown = False

                    episode_items = await watch_page.query_selector_all(".episode-item")
                    direct_episode_count = len(episode_items)
                    print(f"  → Jumlah episode di halaman saat ini: {direct_episode_count}")
                    
                    total_episodes = 0
                    
                    if has_page_dropdown and available_pages:
                        if len(available_pages) > 1:
                            print("  → Multiple pages terdeteksi dari dropdown.")
                            try:
                                last_page = available_pages[-1]
                                _, end_ep_str = last_page.split('-')
                                total_episodes = int(end_ep_str)
                                print(f"  → Total episode dihitung dari halaman terakhir: {total_episodes}")
                            except Exception as e:
                                print(f"  → Gagal parse halaman terakhir, fallback. Error: {e}")
                        else:
                            total_episodes = direct_episode_count
                    else:
                        print("  → Tidak ada multiple pages, gunakan direct count.")
                        total_episodes = direct_episode_count
                        if total_episodes > 0 and not available_pages:
                            available_pages = [f"01-{total_episodes:02d}"]

                    if total_episodes == 0 and direct_episode_count > 0:
                        total_episodes = direct_episode_count

                    print(f"  → Final - Pages: {available_pages}, Total episodes: {total_episodes}")
                    
                    return {
                        "available_pages": available_pages,
                        "total_episodes": total_episodes,
                        "has_multiple_pages": len(available_pages) > 1
                    }
                    
                except Exception as e:
                    print(f"  → Error fatal dalam detect_pages_and_episodes: {e}")
                    return { "available_pages": [], "total_episodes": 0, "has_multiple_pages": False }


            # ============================================================
            # FUNGSI NAVIGASI PAGE (TIDAK DIUBAH)
            # ============================================================
            async def navigate_to_page(watch_page, target_page):
                try:
                    print(f"  → Navigasi ke page: {target_page}")
                    
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
                    
                    await asyncio.sleep(1)
                    await page_dropdown.click()
                    await asyncio.sleep(3)
                    
                    active_menu = await watch_page.query_selector(".v-menu__content--active .v-list")
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
                        await asyncio.sleep(4)
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
            # FUNGSI GET EPISODE ITEMS (TIDAK DIUBAH)
            # ============================================================
            async def get_fresh_episode_items(watch_page):
                try:
                    await asyncio.sleep(2)
                    await watch_page.wait_for_selector(".episode-item", timeout=10000)
                    episode_items = await watch_page.query_selector_all(".episode-item")
                    print(f"  → Refreshed episode items: {len(episode_items)} episodes")
                    return episode_items
                except Exception as e:
                    print(f"  ! Gagal mendapatkan fresh episode items: {e}")
                    return []

            # --- PERBAIKAN ---
            # ============================================================
            # FUNGSI SCRAPE EPISODE DENGAN TIMING YANG TEPAT
            # ============================================================
            async def scrape_episodes_with_pages(watch_page, page_info, existing_episodes=[]):
                available_pages = page_info["available_pages"]
                total_episodes = page_info["total_episodes"]
                has_multiple_pages = page_info["has_multiple_pages"]
                
                episodes_data = existing_episodes.copy()
                total_scraped = 0
                max_episodes_per_run = 20
                
                print(f"  → Memulai scraping {total_episodes} episode di {len(available_pages)} pages...")
                
                pages_to_scrape = available_pages if available_pages else ["01-100"] # Fallback
                
                if has_multiple_pages:
                    # Logika untuk resume bisa ditambahkan di sini jika perlu
                    print(f"  → Pages yang akan di-scrape: {pages_to_scrape}")

                for page_index, target_page in enumerate(pages_to_scrape):
                    if total_scraped >= max_episodes_per_run:
                        break
                    
                    print(f"\n  📄 Memproses Page: {target_page}")
                    
                    if has_multiple_pages and page_index > 0:
                        if not await navigate_to_page(watch_page, target_page):
                            continue
                    
                    episode_items = await get_fresh_episode_items(watch_page)
                    if not episode_items:
                        continue
                    
                    episodes_in_current_page = len(episode_items)
                    print(f"  → Found {episodes_in_current_page} episodes in page {target_page}")
                    
                    try:
                        start_ep, _ = map(int, target_page.split('-'))
                        page_start_index = start_ep - 1
                    except:
                        page_start_index = 0

                    for local_ep_index in range(episodes_in_current_page):
                        global_ep_index = page_start_index + local_ep_index
                        
                        if total_scraped >= max_episodes_per_run:
                            break
                        
                        if (global_ep_index < len(episodes_data) and episodes_data[global_ep_index].get('status') == 'success'):
                            continue
                        
                        try:
                            print(f"\n  --- Memproses Episode {global_ep_index + 1} (Page {target_page}) ---")
                            
                            episode_items = await get_fresh_episode_items(watch_page)
                            if local_ep_index >= len(episode_items):
                                continue
                            
                            ep_item = episode_items[local_ep_index]
                            ep_badge = await ep_item.query_selector(".episode-badge .v-chip__content")
                            ep_number = await ep_badge.inner_text() if ep_badge else f"EP {global_ep_index + 1}"
                            
                            print(f"  - Mengklik episode {ep_number}...")
                            await ep_item.scroll_into_view_if_needed()
                            await asyncio.sleep(1)
                            await ep_item.click()
                            
                            # --- PERBAIKAN UTAMA: MENUNGGU IFRAME ---
                            try:
                                print("    → Menunggu iframe player utama untuk dimuat...")
                                await watch_page.wait_for_selector("iframe.player[src*='krussdomi']", timeout=15000)
                                print("    ✓ Iframe player utama berhasil dimuat.")
                                await asyncio.sleep(2) # Beri jeda tambahan
                            except Exception as wait_e:
                                print(f"    × Gagal menunggu iframe player utama setelah diklik: {wait_e}")
                                episode_data = {"number": ep_number, "iframe": "Gagal diambil (timeout)", "status": "error"}
                                if global_ep_index < len(episodes_data): episodes_data[global_ep_index] = episode_data
                                else: episodes_data.append(episode_data)
                                total_scraped += 1
                                continue
                            # --- AKHIR PERBAIKAN ---

                            print(f"    → Mengambil iframe dengan semua sub/dub options...")
                            iframe_info = await get_all_subdub_iframes(watch_page, ep_number)
                            
                            episode_data = {
                                "number": ep_number, "iframe": iframe_info["iframe_url"],
                                "subdub": iframe_info["subdub_used"], "status": iframe_info["status"],
                                "all_qualities": iframe_info.get("all_subdub_iframes", {})
                            }
                            
                            if global_ep_index < len(episodes_data): episodes_data[global_ep_index] = episode_data
                            else: episodes_data.append(episode_data)
                            
                            total_scraped += 1
                            
                            if iframe_info["status"] == "success":
                                print(f"    ✓ Episode {ep_number} berhasil di-scrape")
                            else:
                                print(f"    × Episode {ep_number} gagal (iframe not found)")
                                
                        except Exception as ep_e:
                            print(f"    × Gagal memproses episode {global_ep_index + 1}: {type(ep_e).__name__}: {ep_e}")
                            episode_data = {"number": f"EP {global_ep_index + 1}", "iframe": "Gagal diambil", "status": "error"}
                            if global_ep_index < len(episodes_data): episodes_data[global_ep_index] = episode_data
                            else: episodes_data.append(episode_data)
                            total_scraped += 1
                            continue
                
                return episodes_data, total_scraped
            
            # ============================================================
            # LOOP UTAMA (TIDAK DIUBAH SECARA SIGNIFIKAN)
            # ============================================================
            for index, item in enumerate(anime_items[:36]):
                print(f"\n--- Memproses Item #{index + 1} ---")
                detail_page = None
                watch_page = None
                
                try:
                    await item.scroll_into_view_if_needed()
                    await asyncio.sleep(2)
                    poster_url = "Tidak tersedia"
                    poster_div = await item.query_selector(".v-image__image--cover")
                    if poster_div:
                        poster_style = await poster_div.get_attribute("style")
                        if poster_style and 'url("' in poster_style:
                            poster_url_path = poster_style.split('url("')[1].split('")')[0]
                            poster_url = urljoin(base_url, poster_url_path)
                    print(f"URL Poster: {poster_url}")

                    detail_link_element = await item.query_selector("h2.show-title a")
                    if not detail_link_element: continue
                    
                    full_detail_url = urljoin(base_url, await detail_link_element.get_attribute("href"))
                    
                    existing_anime = next((anime for anime in existing_data if anime.get('url_detail') == full_detail_url), None)
                    anime_needs_update = False
                    if existing_anime:
                        total_existing_episodes = len([ep for ep in existing_anime.get('episodes', []) if ep.get('status') == 'success'])
                        total_expected_episodes = existing_anime.get('total_episodes', 0)
                        if total_existing_episodes < total_expected_episodes or any(ep.get('status') == 'error' for ep in existing_anime.get('episodes', [])):
                            anime_needs_update = True
                            print(f"  → Anime perlu update: {existing_anime.get('title')}")
                        else:
                            print(f"  → Anime sudah up-to-date: {existing_anime.get('title')}, skip")
                            scraped_data.append(existing_anime)
                            continue
                    
                    detail_page = await context.new_page()
                    await detail_page.goto(full_detail_url, timeout=90000)
                    await detail_page.wait_for_selector(".anime-info-card", timeout=30000)
                    
                    title = await (await detail_page.query_selector(".anime-info-card .v-card__title span")).inner_text()
                    synopsis_card_title = await detail_page.query_selector("div.v-card__title:has-text('Synopsis')")
                    synopsis = await (await (await synopsis_card_title.query_selector("xpath=..")).query_selector(".text-caption")).inner_text() if synopsis_card_title else "N/A"
                    genre_elements = await detail_page.query_selector_all(".anime-info-card .v-chip--outlined .v-chip__content")
                    all_tags = [await el.inner_text() for el in genre_elements]
                    irrelevant_tags = ['TV', 'PG-13', 'Airing', '2025', '2024', '23 min', '24 min', 'SUB', 'DUB', 'ONA']
                    genres = [tag for tag in all_tags if tag not in irrelevant_tags and not tag.startswith('EP')]
                    metadata_container = await detail_page.query_selector(".anime-info-card .d-flex.mb-3")
                    metadata = [await el.inner_text() for el in await metadata_container.query_selector_all(".text-subtitle-2")] if metadata_container else []

                    watch_button = await detail_page.query_selector('a.v-btn[href*="/ep-"]')
                    first_episode_url = urljoin(base_url, await watch_button.get_attribute("href")) if watch_button else None
                    if not first_episode_url: continue
                    print(f"URL Episode Pertama: {first_episode_url}")
                    
                    watch_page = await context.new_page()
                    await watch_page.goto(first_episode_url, timeout=90000)
                    await watch_page.wait_for_selector(".player-container", timeout=30000)
                    
                    page_info = await detect_pages_and_episodes(watch_page)
                    
                    available_subdub = await get_available_subdub_from_dropdown(watch_page)
                    
                    existing_episodes = existing_anime.get('episodes', []) if existing_anime else []
                    episodes_data, total_scraped = await scrape_episodes_with_pages(
                        watch_page, page_info, existing_episodes
                    )

                    anime_info = {
                        "title": title.strip(), "synopsis": synopsis.strip(), "genres": genres,
                        "metadata": metadata, "poster": poster_url, "url_detail": full_detail_url,
                        "total_episodes": page_info["total_episodes"], "episodes": episodes_data,
                        "available_subdub": available_subdub, "optimal_subdub": available_subdub[0] if available_subdub else "N/A",
                        "available_pages": page_info["available_pages"], "has_multiple_pages": page_info["has_multiple_pages"],
                        "last_updated": time.time()
                    }
                    
                    if existing_anime:
                        existing_anime.update(anime_info)
                        # Ensure it's the same object for scraped_data
                        found = False
                        for i, an in enumerate(scraped_data):
                            if an.get('url_detail') == full_detail_url:
                                scraped_data[i] = existing_anime
                                found = True
                                break
                        if not found: scraped_data.append(existing_anime)
                    else:
                        scraped_data.append(anime_info)
                    
                    success_count = sum(1 for ep in episodes_data if ep.get('status') == 'success')
                    print(f"✓ Data {title} {'diperbarui' if existing_anime else 'ditambahkan'} ({success_count}/{len(episodes_data)} berhasil)")
                    
                except Exception as e:
                    print(f"!!! Gagal memproses item #{index + 1}: {type(e).__name__}: {e}")
                finally:
                    if watch_page and not watch_page.is_closed(): await watch_page.close()
                    if detail_page and not detail_page.is_closed(): await detail_page.close()

            updated_urls = [anime.get('url_detail') for anime in scraped_data]
            for existing_anime in existing_data:
                if existing_anime.get('url_detail') not in updated_urls:
                    scraped_data.append(existing_anime)

            print("\n" + "="*50 + "\nHASIL SCRAPING SELESAI\n" + "="*50)
            
            with open('anime_data.json', 'w', encoding='utf-8') as f:
                json.dump(scraped_data, f, ensure_ascii=False, indent=4)
            print("\nData berhasil disimpan ke anime_data.json")

        except Exception as e:
            print(f"Terjadi kesalahan fatal: {type(e).__name__}: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_kickass_anime())
