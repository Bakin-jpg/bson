import asyncio
from playwright.async_api import async_playwright
import json
from urllib.parse import urljoin
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
            processed_urls = set()

            for index, item in enumerate(anime_items):
                print(f"\n--- Memproses Item #{index + 1} ---")
                detail_page = None
                watch_page = None
                
                try:
                    # Ambil URL Poster
                    await item.scroll_into_view_if_needed()
                    poster_url = "Tidak tersedia"
                    for attempt in range(3):
                        poster_div = await item.query_selector(".v-image__image--cover")
                        if poster_div:
                            poster_style = await poster_div.get_attribute("style")
                            if poster_style and 'url("' in poster_style:
                                parts = poster_style.split('url("')
                                if len(parts) > 1:
                                    poster_url_path = parts[1].split('")')[0]
                                    poster_url = urljoin(base_url, poster_url_path)
                                    break
                        await asyncio.sleep(0.3)

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
                            
                            # Cek apakah perlu update
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
                        processed_urls.add(full_detail_url)
                        continue

                    # Buka halaman detail
                    detail_page = await context.new_page()
                    await detail_page.goto(full_detail_url, timeout=60000)
                    await detail_page.wait_for_selector(".anime-info-card", timeout=20000)
                    
                    # Scrape informasi dasar
                    title_element = await detail_page.query_selector(".anime-info-card .v-card__title span")
                    title = await title_element.inner_text() if title_element else "Judul tidak ditemukan"

                    print(f"URL Poster: {poster_url}")
                    print(f"Memproses: {title}")

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

                    # Tutup detail page sebelum buka watch page
                    await detail_page.close()
                    detail_page = None

                    # Buka halaman watch untuk scrape iframe dan episode
                    watch_page = await context.new_page()
                    await watch_page.goto(first_episode_url, timeout=60000)
                    await watch_page.wait_for_selector(".player-container", timeout=20000)
                    
                    # **PERBAIKAN: Deteksi sub/dub yang tersedia - HANYA ambil bahasa**
                    available_subdub = []
                    optimal_subdub = None
                    
                    try:
                        # Cari dropdown sub/dub
                        subdub_dropdown = await watch_page.query_selector(".v-select:has(.v-label:has-text('Sub/Dub'))")
                        
                        if subdub_dropdown:
                            # Dapatkan sub/dub saat ini
                            current_selection = await subdub_dropdown.query_selector(".v-select__selection.v-select__selection--comma")
                            if current_selection:
                                current_subdub = await current_selection.inner_text()
                                optimal_subdub = current_subdub
                                print(f"  → Sub/Dub saat ini: {current_subdub}")
                            
                            # Buka dropdown untuk mendapatkan opsi
                            await subdub_dropdown.click()
                            await asyncio.sleep(1)
                            
                            # Ambil semua opsi dan FILTER hanya yang berisi bahasa
                            all_options = await watch_page.query_selector_all(".v-list-item .v-list-item__title")
                            for option in all_options:
                                option_text = await option.inner_text()
                                # Hanya ambil yang mengandung kata kunci bahasa
                                if any(keyword in option_text.lower() for keyword in 
                                      ['japanese', 'english', 'spanish', 'chinese', 'french', 'german', 'sub', 'dub']):
                                    available_subdub.append(option_text)
                            
                            # Jika tidak ada yang terdeteksi, gunakan semua kecuali menu navigasi
                            if not available_subdub:
                                menu_navs = ['Home', 'Trending', 'Schedule', 'Anime', 'Popular Shows', 'Random']
                                for option in all_options:
                                    option_text = await option.inner_text()
                                    if option_text and option_text not in menu_navs:
                                        available_subdub.append(option_text)
                            
                            print(f"  → Tersedia sub/dub: {available_subdub}")
                            
                            # Tutup dropdown
                            await watch_page.keyboard.press("Escape")
                            await asyncio.sleep(0.5)
                        else:
                            print("  → Dropdown sub/dub tidak ditemukan, menggunakan default")
                            available_subdub = ["Japanese (SUB)", "English (DUB)"]
                            optimal_subdub = "Japanese (SUB)"
                    except Exception as e:
                        print(f"  → Error detect sub/dub: {e}")
                        available_subdub = ["Japanese (SUB)", "English (DUB)"]
                        optimal_subdub = "Japanese (SUB)"

                    # **PERBAIKAN: Deteksi page selector - HANYA ambil format angka**
                    available_pages = []
                    current_page = "01-100"
                    
                    try:
                        # Cari dropdown page
                        page_dropdown = await watch_page.query_selector(".v-select:has(.v-label:has-text('Page'))")
                        
                        if page_dropdown:
                            # Dapatkan page saat ini
                            current_selection = await page_dropdown.query_selector(".v-select__selection.v-select__selection--comma")
                            if current_selection:
                                current_page = await current_selection.inner_text()
                                print(f"  → Page saat ini: {current_page}")
                            
                            # Buka dropdown untuk mendapatkan semua page
                            await page_dropdown.click()
                            await asyncio.sleep(1)
                            
                            # Ambil semua opsi page dan FILTER hanya format angka
                            all_options = await watch_page.query_selector_all(".v-list-item .v-list-item__title")
                            for option in all_options:
                                page_text = await option.inner_text()
                                # Hanya ambil yang berformat: 01-100, 101-200, dll atau angka tunggal
                                if ('-' in page_text and 
                                    page_text.replace('-', '').replace(' ', '').isdigit()):
                                    available_pages.append(page_text)
                                elif page_text.isdigit():
                                    available_pages.append(page_text)
                            
                            print(f"  → Tersedia pages: {available_pages}")
                            
                            # Hitung total episodes berdasarkan page terakhir
                            if available_pages:
                                last_page = available_pages[-1]
                                if '-' in last_page:
                                    try:
                                        start_ep, end_ep = last_page.split('-')
                                        total_episodes = int(end_ep)
                                        print(f"  → Total episodes: {total_episodes}")
                                    except:
                                        total_episodes = len(available_pages) * 100
                                        print(f"  → Estimated total episodes: {total_episodes}")
                                else:
                                    total_episodes = int(last_page)
                                    print(f"  → Total episodes: {total_episodes}")
                            else:
                                total_episodes = 100
                                print(f"  → Single page, estimated episodes: {total_episodes}")
                            
                            # Tutup dropdown
                            await watch_page.keyboard.press("Escape")
                            await asyncio.sleep(0.5)
                        else:
                            print("  → Dropdown page tidak ditemukan, single page")
                            total_episodes = 5
                    except Exception as e:
                        print(f"  → Error detect page: {e}")
                        total_episodes = 5

                    # **SIMPLE EPISODE SCRAPING - hanya ambil beberapa episode**
                    episodes_data = existing_anime.get('episodes', []) if existing_anime else []
                    
                    # Untuk testing, hanya scrape 3 episode pertama yang belum ada
                    episodes_to_scrape = []
                    for i in range(min(3, total_episodes)):
                        if i >= len(episodes_data) or episodes_data[i].get('status') in ['error', 'pending']:
                            episodes_to_scrape.append(i)

                    if not episodes_to_scrape:
                        print("  → Semua episode sudah di-scrape, skip scraping episode")
                    else:
                        print(f"  → Akan scrape {len(episodes_to_scrape)} episode")

                        for ep_index in episodes_to_scrape:
                            try:
                                print(f"  --- Memproses Episode {ep_index + 1} ---")
                                
                                # Tunggu episode items
                                await watch_page.wait_for_selector(".episode-item", timeout=10000)
                                episode_items = await watch_page.query_selector_all(".episode-item")
                                
                                if ep_index >= len(episode_items):
                                    print(f"    × Episode tidak ditemukan")
                                    continue
                                
                                ep_item = episode_items[ep_index]
                                
                                # Klik episode
                                await ep_item.scroll_into_view_if_needed()
                                await asyncio.sleep(0.5)
                                await ep_item.click()
                                await asyncio.sleep(2)
                                
                                # Cari iframe
                                iframe_src = None
                                iframe_element = await watch_page.query_selector("iframe.player:not([src=''])")
                                if iframe_element:
                                    iframe_src = await iframe_element.get_attribute("src")
                                
                                # Simpan data episode
                                episode_data = {
                                    "number": f"EP {ep_index + 1}",
                                    "iframe": iframe_src or "Gagal diambil",
                                    "subdub": optimal_subdub or "None",
                                    "status": "success" if iframe_src else "error",
                                    "all_qualities": {"Current": iframe_src} if iframe_src else {}
                                }
                                
                                # Update episodes data
                                if ep_index < len(episodes_data):
                                    episodes_data[ep_index] = episode_data
                                else:
                                    episodes_data.append(episode_data)
                                
                                print(f"    ✓ Episode {ep_index + 1} berhasil di-scrape")
                                
                            except Exception as ep_e:
                                print(f"    × Gagal episode {ep_index + 1}: {ep_e}")
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
                        "last_updated": time.time()
                    }
                    
                    # Update atau tambah data baru
                    if existing_anime:
                        existing_anime.update(anime_info)
                        scraped_data.append(existing_anime)
                    else:
                        scraped_data.append(anime_info)
                    
                    processed_urls.add(full_detail_url)
                    
                    success_count = sum(1 for ep in episodes_data if ep.get('status') in ['success'])
                    current_episode_count = len([ep for ep in episodes_data if ep.get('status') != 'pending'])
                    
                    print(f"✓ Data {title} {'diperbarui' if existing_anime else 'ditambahkan'} ({success_count}/{current_episode_count} berhasil)")

                except Exception as e:
                    print(f"!!! Gagal memproses item #{index + 1}: {type(e).__name__}: {e}")
                    if existing_anime:
                        scraped_data.append(existing_anime)
                        processed_urls.add(full_detail_url)
                        print(f"  → Tetap menyimpan data existing untuk {existing_anime.get('title')}")
                    
                finally:
                    # PASTIKAN page ditutup dengan benar
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

            # **PERBAIKAN: Gabungkan data existing yang tidak diproses**
            for existing_anime in existing_data:
                if existing_anime.get('url_detail') not in processed_urls:
                    scraped_data.append(existing_anime)

            print(f"\nTotal data setelah scraping: {len(scraped_data)} anime")

            # Hitung statistik
            total_scraped_episodes = sum(len(anime.get('episodes', [])) for anime in scraped_data)
            total_expected_episodes = sum(anime.get('total_episodes', 0) for anime in scraped_data)
            successful_episodes = sum(1 for anime in scraped_data for ep in anime.get('episodes', []) if ep.get('status') in ['success'])
            
            progress_percentage = (total_scraped_episodes / total_expected_episodes * 100) if total_expected_episodes > 0 else 0
            success_rate = (successful_episodes / total_scraped_episodes * 100) if total_scraped_episodes > 0 else 0
            
            print("\n" + "="*50)
            print(f"HASIL SCRAPING SELESAI. Total {len(scraped_data)} data berhasil diambil/diperbarui.")
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
