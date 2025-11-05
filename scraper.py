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
        browser = await p.chromium.launch(headless=False)  # Ubah ke False untuk debugging
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

                    # **PERBAIKAN: Ambil URL Poster dengan cara yang lebih reliable**
                    await item.scroll_into_view_if_needed()
                    poster_url = "Tidak tersedia"
                    
                    # Coba multiple approaches untuk ambil poster
                    poster_attempts = [
                        # Approach 1: Dari style background image
                        lambda: item.query_selector(".v-image__image--cover"),
                        # Approach 2: Dari parent container
                        lambda: item.query_selector(".v-image"),
                        # Approach 3: Dari image element langsung
                        lambda: item.query_selector("img")
                    ]
                    
                    for attempt_num, attempt_func in enumerate(poster_attempts):
                        try:
                            poster_element = await attempt_func()
                            if poster_element:
                                poster_style = await poster_element.get_attribute("style")
                                if poster_style and 'url("' in poster_style:
                                    parts = poster_style.split('url("')
                                    if len(parts) > 1:
                                        poster_url_path = parts[1].split('")')[0]
                                        poster_url = urljoin(base_url, poster_url_path)
                                        print(f"  → URL Poster ditemukan (approach {attempt_num + 1})")
                                        break
                                # Coba dari src attribute jika img element
                                src = await poster_element.get_attribute("src")
                                if src and not src.startswith('data:'):
                                    poster_url = urljoin(base_url, src)
                                    print(f"  → URL Poster ditemukan (approach {attempt_num + 1} - src)")
                                    break
                        except Exception as e:
                            continue
                    
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
                    
                    # **PERBAIKAN: Deteksi dropdown dengan cara yang lebih reliable**
                    print("  → Mencari dropdown di area episode list...")
                    
                    # Tunggu episode list container
                    await watch_page.wait_for_selector(".episode-list", timeout=10000)
                    
                    # **PERBAIKAN: Ambil semua pages dengan cara manual jika dropdown gagal**
                    available_pages = []
                    current_page = "01-100"
                    total_episodes = 100
                    episodes_per_page = 100
                    
                    try:
                        # Coba dapatkan pages dari dropdown
                        page_dropdown = await watch_page.query_selector(".v-select:has(.v-label:has-text('Page'))")
                        if page_dropdown:
                            await page_dropdown.click()
                            await asyncio.sleep(1)
                            
                            active_menu = await watch_page.query_selector(".v-menu__content.v-menu__content--active .v-list")
                            if active_menu:
                                page_options = await active_menu.query_selector_all(".v-list-item .v-list-item__title")
                                for option in page_options:
                                    page_text = await option.inner_text()
                                    if page_text and re.match(r'^\d+-\d+$', page_text):
                                        available_pages.append(page_text)
                                
                                # Urutkan pages
                                def get_first_number(page_str):
                                    match = re.match(r'(\d+)-\d+', page_str)
                                    return int(match.group(1)) if match else 0
                                
                                available_pages.sort(key=get_first_number)
                                
                                if available_pages:
                                    last_page = available_pages[-1]
                                    try:
                                        start_ep, end_ep = last_page.split('-')
                                        total_episodes = int(end_ep)
                                        print(f"  → Total episodes dari dropdown: {total_episodes}")
                                    except:
                                        total_episodes = len(available_pages) * episodes_per_page
                                
                                await watch_page.keyboard.press("Escape")
                                await asyncio.sleep(0.5)
                    except Exception as e:
                        print(f"  → Error ambil pages dari dropdown: {e}")
                    
                    # **FALLBACK: Jika tidak ada pages dari dropdown, buat manual**
                    if not available_pages:
                        print("  → Buat pages manual berdasarkan total episodes...")
                        # Untuk anime seperti One Piece, asumsikan ada banyak episodes
                        if "one-piece" in full_detail_url.lower():
                            total_episodes = 1100  # Approximate untuk One Piece
                            episodes_per_page = 100
                        else:
                            # Untuk anime lain, coba hitung dari episode items yang terlihat
                            episode_items = await watch_page.query_selector_all(".episode-item")
                            total_episodes = len(episode_items)
                            episodes_per_page = total_episodes
                        
                        # Generate pages
                        for i in range(0, total_episodes, episodes_per_page):
                            start = i + 1
                            end = min(i + episodes_per_page, total_episodes)
                            page_str = f"{start:02d}-{end:02d}"
                            available_pages.append(page_str)
                        
                        print(f"  → Generated {len(available_pages)} pages")
                    
                    # **PERBAIKAN: Deteksi sub/dub**
                    available_subdub = ["Japanese (SUB)", "English (DUB)"]
                    optimal_subdub = "Japanese (SUB)"
                    
                    try:
                        subdub_dropdown = await watch_page.query_selector(".v-select:has(.v-label:has-text('Sub/Dub'))")
                        if subdub_dropdown:
                            current_selection = await subdub_dropdown.query_selector(".v-select__selection.v-select__selection--comma")
                            if current_selection:
                                optimal_subdub = await current_selection.inner_text()
                    except Exception as e:
                        print(f"  → Error detect sub/dub: {e}")
                    
                    print(f"  → Available pages: {available_pages}")
                    print(f"  → Total episodes: {total_episodes}")
                    print(f"  → Optimal sub/dub: {optimal_subdub}")

                    # **PERBAIKAN: Sistem scraping episode dengan retry mechanism**
                    episodes_data = existing_anime.get('episodes', []) if existing_anime else []
                    total_scraped_in_this_run = 0
                    max_episodes_per_run = 200  # Tingkatkan batas untuk anime panjang
                    
                    # **Fungsi untuk scrape episode dengan retry**
                    async def scrape_episode_with_retry(watch_page, ep_item, ep_number, global_ep_index, max_retries=3):
                        for retry in range(max_retries):
                            try:
                                print(f"  - Mengklik episode {ep_number} (attempt {retry + 1})...")
                                
                                await ep_item.scroll_into_view_if_needed()
                                await asyncio.sleep(0.5)
                                await ep_item.click()
                                await asyncio.sleep(3)
                                
                                # Cek apakah berhasil navigasi ke episode
                                current_url = watch_page.url
                                if "/ep-" not in current_url:
                                    raise Exception("Navigation failed")
                                
                                # **PERBAIKAN: Cari iframe dengan multiple approaches**
                                iframe_src = None
                                status = "error"
                                error_msg = "Unknown error"
                                
                                # Approach 1: Cari iframe utama
                                iframe_element = await watch_page.query_selector("iframe.player:not([src='']):not([src='about:blank'])")
                                if iframe_element:
                                    iframe_src = await iframe_element.get_attribute("src")
                                    if iframe_src and iframe_src != "about:blank":
                                        status = "success"
                                        error_msg = None
                                
                                # Approach 2: Jika iframe tidak ditemukan, coba ganti sub/dub
                                if not iframe_src and retry < max_retries - 1:
                                    print(f"    → Iframe tidak ditemukan, coba ganti sub/dub...")
                                    try:
                                        subdub_dropdown = await watch_page.query_selector(".v-select:has(.v-label:has-text('Sub/Dub'))")
                                        if subdub_dropdown:
                                            await subdub_dropdown.click()
                                            await asyncio.sleep(1)
                                            
                                            active_menu = await watch_page.query_selector(".v-menu__content.v-menu__content--active .v-list")
                                            if active_menu:
                                                # Coba semua opsi sub/dub yang tersedia
                                                subdub_options = await active_menu.query_selector_all(".v-list-item .v-list-item__title")
                                                for option in subdub_options:
                                                    option_text = await option.inner_text()
                                                    if option_text and option_text != optimal_subdub:
                                                        await option.click()
                                                        await asyncio.sleep(3)
                                                        print(f"    → Coba sub/dub: {option_text}")
                                                        break
                                                
                                                await watch_page.keyboard.press("Escape")
                                                await asyncio.sleep(0.5)
                                    except Exception as subdub_error:
                                        print(f"    → Error ganti sub/dub: {subdub_error}")
                                
                                # Approach 3: Cek apakah ada error message
                                if not iframe_src:
                                    error_element = await watch_page.query_selector(".error-message, .alert, .v-alert")
                                    if error_element:
                                        error_msg = await error_element.inner_text()
                                
                                return {
                                    "iframe_src": iframe_src,
                                    "status": status,
                                    "error_msg": error_msg,
                                    "success": status == "success"
                                }
                                
                            except Exception as e:
                                error_msg = f"{type(e).__name__}: {str(e)}"
                                if retry < max_retries - 1:
                                    print(f"    → Retry karena error: {error_msg}")
                                    await asyncio.sleep(2)
                                else:
                                    return {
                                        "iframe_src": None,
                                        "status": "error",
                                        "error_msg": error_msg,
                                        "success": False
                                    }
                        
                        return {
                            "iframe_src": None,
                            "status": "error", 
                            "error_msg": "Max retries exceeded",
                            "success": False
                        }

                    # **PROSES SEMUA PAGES DAN EPISODES**
                    print(f"\n  🚀 Memulai scraping {len(available_pages)} pages...")
                    print(f"  → Total episodes: {total_episodes}")

                    for page_index, target_page in enumerate(available_pages):
                        if total_scraped_in_this_run >= max_episodes_per_run:
                            print(f"  → Batas {max_episodes_per_run} episode tercapai")
                            break
                            
                        print(f"\n  📄 Memproses Page: {target_page}")
                        
                        # Navigasi ke page jika diperlukan
                        if page_index > 0:
                            print(f"  → Mengganti ke page: {target_page}")
                            try:
                                page_dropdown = await watch_page.query_selector(".v-select:has(.v-label:has-text('Page'))")
                                if page_dropdown:
                                    await page_dropdown.click()
                                    await asyncio.sleep(1)
                                    
                                    active_menu = await watch_page.query_selector(".v-menu__content.v-menu__content--active .v-list")
                                    if active_menu:
                                        page_option = None
                                        options = await active_menu.query_selector_all(".v-list-item .v-list-item__title")
                                        for option in options:
                                            option_text = await option.inner_text()
                                            if option_text == target_page:
                                                page_option = option
                                                break
                                        
                                        if page_option:
                                            await page_option.click()
                                            await asyncio.sleep(3)
                                            print(f"  ✓ Berhasil ganti ke page: {target_page}")
                                        else:
                                            print(f"  ! Page {target_page} tidak ditemukan")
                                            continue
                                    else:
                                        print(f"  ! Dropdown menu tidak terbuka")
                                        continue
                                else:
                                    print(f"  ! Page dropdown tidak ditemukan")
                                    continue
                            except Exception as page_error:
                                print(f"  ! Gagal ganti page: {page_error}")
                                continue

                        # Tunggu episode items
                        try:
                            await watch_page.wait_for_selector(".episode-item", timeout=15000)
                        except Exception as e:
                            print(f"  ! Timeout menunggu episode items: {e}")
                            continue

                        episode_items = await watch_page.query_selector_all(".episode-item")
                        episodes_in_current_page = len(episode_items)
                        
                        print(f"  → Found {episodes_in_current_page} episodes in page {target_page}")

                        # Hitung range episode
                        if '-' in target_page:
                            try:
                                start_ep, end_ep = target_page.split('-')
                                page_start_episode = int(start_ep) - 1
                                page_end_episode = int(end_ep)
                            except:
                                page_start_episode = page_index * episodes_per_page
                                page_end_episode = page_start_episode + episodes_in_current_page
                        else:
                            page_start_episode = page_index * episodes_per_page
                            page_end_episode = page_start_episode + episodes_in_current_page

                        # Process each episode in current page
                        for local_ep_index in range(episodes_in_current_page):
                            if total_scraped_in_this_run >= max_episodes_per_run:
                                break
                                
                            global_ep_index = page_start_episode + local_ep_index
                            
                            # Skip jika episode sudah ada dan success
                            if (global_ep_index < len(episodes_data) and 
                                episodes_data[global_ep_index].get('status') == 'success'):
                                continue

                            try:
                                print(f"\n  --- Memproses Episode {global_ep_index + 1} (Page {target_page}) ---")
                                
                                if local_ep_index >= len(episode_items):
                                    print(f"    × Episode tidak ditemukan di page ini")
                                    continue
                                
                                ep_item = episode_items[local_ep_index]
                                ep_badge = await ep_item.query_selector(".episode-badge .v-chip__content")
                                ep_number = await ep_badge.inner_text() if ep_badge else f"EP {global_ep_index + 1}"
                                
                                # Scrape episode dengan retry mechanism
                                result = await scrape_episode_with_retry(watch_page, ep_item, ep_number, global_ep_index)
                                
                                # Simpan data episode
                                episode_data = {
                                    "number": ep_number,
                                    "iframe": result["iframe_src"] or "Gagal diambil",
                                    "subdub": optimal_subdub or "None",
                                    "status": result["status"],
                                    "error_message": result["error_msg"],
                                    "all_qualities": {"Current": result["iframe_src"]} if result["iframe_src"] else {}
                                }
                                
                                # Update atau tambah episode data
                                if global_ep_index < len(episodes_data):
                                    episodes_data[global_ep_index] = episode_data
                                else:
                                    while len(episodes_data) <= global_ep_index:
                                        episodes_data.append({
                                            "number": f"EP {len(episodes_data) + 1}",
                                            "iframe": "Belum di-scrape",
                                            "subdub": "None",
                                            "status": "pending",
                                            "all_qualities": {}
                                        })
                                    episodes_data[global_ep_index] = episode_data
                                
                                total_scraped_in_this_run += 1
                                
                                if result["success"]:
                                    print(f"    ✓ Episode {ep_number} berhasil di-scrape")
                                else:
                                    print(f"    × Episode {ep_number} gagal: {result['error_msg']}")
                                
                            except Exception as ep_e:
                                print(f"    × Gagal memproses episode {global_ep_index + 1}: {type(ep_e).__name__}: {ep_e}")
                                
                                episode_data = {
                                    "number": f"EP {global_ep_index + 1}",
                                    "iframe": "Gagal diambil",
                                    "subdub": optimal_subdub or "None",
                                    "status": "error",
                                    "error_message": str(ep_e),
                                    "all_qualities": {}
                                }
                                
                                if global_ep_index < len(episodes_data):
                                    episodes_data[global_ep_index] = episode_data
                                else:
                                    episodes_data.append(episode_data)
                                
                                total_scraped_in_this_run += 1

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
                    error_count = sum(1 for ep in episodes_data if ep.get('status') in ['error'])
                    pending_count = sum(1 for ep in episodes_data if ep.get('status') in ['pending'])
                    current_episode_count = success_count + error_count
                    
                    print(f"✓ Data {title} {'diperbarui' if existing_anime else 'ditambahkan'} ({success_count} berhasil, {error_count} error, {pending_count} pending)")
                    print(f"  → Progress: {current_episode_count}/{total_episodes} episode ({current_episode_count/total_episodes*100:.1f}%)")
                    print(f"  → Optimal sub/dub: {optimal_subdub}")
                    print(f"  → Total pages: {len(available_pages)}")
                    
                except Exception as e:
                    print(f"!!! Gagal memproses item #{index + 1}: {type(e).__name__}: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    if existing_anime:
                        scraped_data.append(existing_anime)
                        print(f"  → Tetap menyimpan data existing untuk {existing_anime.get('title')}")
                
                finally:
                    # Tutup pages
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
            error_episodes = sum(1 for anime in scraped_data for ep in anime.get('episodes', []) if ep.get('status') in ['error'])
            
            progress_percentage = (total_scraped_episodes / total_expected_episodes * 100) if total_expected_episodes > 0 else 0
            success_rate = (successful_episodes / total_scraped_episodes * 100) if total_scraped_episodes > 0 else 0
            
            print(f"Progress Episode: {total_scraped_episodes}/{total_expected_episodes} ({progress_percentage:.1f}%)")
            print(f"Success Rate: {successful_episodes}/{total_scraped_episodes} ({success_rate:.1f}%)")
            print(f"Error Count: {error_episodes}")
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
            import traceback
            traceback.print_exc()
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_kickass_anime())
