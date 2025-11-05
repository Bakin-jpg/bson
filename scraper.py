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
    FOKUS HANYA PADA SATU TARGET UNTUK DEBUGGING.
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
            target_anime_url = "https://kickass-anime.ru/one-piece-0948"
            print(f"--- MEMULAI MODE DEBUG: HANYA MEMPROSES {target_anime_url} ---")
            
            existing_data = []
            if os.path.exists('anime_data.json'):
                try:
                    with open('anime_data.json', 'r', encoding='utf-8') as f:
                        file_content = f.read().strip()
                        if file_content:
                            existing_data = json.loads(file_content)
                            print(f"Data existing ditemukan: {len(existing_data)} anime")
                except Exception as e:
                    print(f"Error membaca anime_data.json: {e}")
            
            scraped_data = []

            # ============================================================
            # FUNGSI-FUNGSI HELPER (SAMA SEPERTI SEBELUMNYA, TIDAK DIUBAH)
            # ============================================================
            
            async def get_available_subdub_from_dropdown(watch_page):
                subdub_options = []
                try:
                    dropdown = None
                    all_dropdowns = await watch_page.query_selector_all(".episode-list .v-select")
                    for d in all_dropdowns:
                        label_el = await d.query_selector(".v-label")
                        if label_el and "Sub/Dub" in await label_el.inner_text():
                            dropdown = d; print("Dropdown Sub/Dub ditemukan."); break
                    if not dropdown: print("Dropdown Sub/Dub tidak ditemukan."); return []
                    await dropdown.click()
                    await watch_page.wait_for_selector(".v-menu__content--active", timeout=5000)
                    print("Menu Sub/Dub berhasil dibuka.")
                    option_elements = await watch_page.query_selector_all(".v-menu__content--active .v-list-item__title")
                    if option_elements:
                        for option in option_elements:
                            option_text = await option.inner_text()
                            if option_text and option_text.strip(): subdub_options.append(option_text.strip())
                    await watch_page.keyboard.press("Escape"); await asyncio.sleep(1)
                    print(f"Sub/Dub tersedia dari dropdown: {subdub_options}")
                    return list(set(subdub_options))
                except Exception as e:
                    print(f"Gagal membaca dropdown sub/dub: {type(e).__name__}: {e}")
                    await watch_page.keyboard.press("Escape"); return []

            async def change_subdub_from_dropdown(watch_page, target_subdub):
                try:
                    dropdown = None
                    all_dropdowns = await watch_page.query_selector_all(".episode-list .v-select")
                    for d in all_dropdowns:
                        label_el = await d.query_selector(".v-label")
                        if label_el and "Sub/Dub" in await label_el.inner_text(): dropdown = d; break
                    if not dropdown: return False
                    await dropdown.click()
                    await watch_page.wait_for_selector(".v-menu__content--active", timeout=5000)
                    target_option = await watch_page.query_selector(f"//div[contains(@class, 'v-menu__content--active')]//div[contains(@class, 'v-list-item__title') and contains(normalize-space(), '{target_subdub}')]")
                    if target_option:
                        await target_option.click(); await asyncio.sleep(4)
                        print(f"✓ Berhasil ganti ke: {target_subdub}"); return True
                    else:
                        print(f"✗ Opsi {target_subdub} tidak ditemukan"); await watch_page.keyboard.press("Escape"); return False
                except Exception as e:
                    print(f"Gagal mengganti sub/dub ke {target_subdub}: {e}"); await watch_page.keyboard.press("Escape"); return False

            async def is_iframe_valid(iframe_src):
                if not iframe_src or any(s in iframe_src for s in ["Iframe tidak ditemukan", "Iframe tidak tersedia", "Iframe tidak valid"]): return False
                return any(pattern in iframe_src for pattern in ["krussdomi.com", "vidstream", "cat-player"])

            async def get_all_subdub_iframes(watch_page, episode_number):
                available_subdub = await get_available_subdub_from_dropdown(watch_page)
                if not available_subdub:
                    print("  Gagal membaca Sub/Dub, mencoba lagi..."); await asyncio.sleep(3)
                    available_subdub = await get_available_subdub_from_dropdown(watch_page)
                if not available_subdub:
                    print("  Tetap tidak ada pilihan sub/dub, gunakan iframe default")
                    iframe_element = await watch_page.query_selector("iframe.player")
                    current_iframe = await iframe_element.get_attribute("src") if iframe_element else "Iframe tidak ditemukan"
                    return { "iframe_url": current_iframe, "subdub_used": "Default", "status": "success" if await is_iframe_valid(current_iframe) else "error", "all_subdub_iframes": {"Default": current_iframe} }
                
                all_iframes = {}
                for subdub_to_try in available_subdub:
                    print(f"  Mencoba Sub/Dub: {subdub_to_try}")
                    if await change_subdub_from_dropdown(watch_page, subdub_to_try):
                        await asyncio.sleep(4)
                        iframe_element = await watch_page.query_selector("iframe.player")
                        iframe_src = await iframe_element.get_attribute("src") if iframe_element else "Iframe tidak ditemukan"
                        if await is_iframe_valid(iframe_src): all_iframes[subdub_to_try] = iframe_src; print(f"    ✓ Iframe valid ditemukan untuk {subdub_to_try}")
                        else: all_iframes[subdub_to_try] = "Iframe tidak valid"; print(f"    ✗ Iframe tidak valid untuk {subdub_to_try}")
                    else: all_iframes[subdub_to_try] = "Gagal ganti Sub/Dub"
                
                primary_iframe, primary_subdub, status = "Iframe tidak ditemukan", "None", "error"
                for subdub, iframe_url in all_iframes.items():
                    if await is_iframe_valid(iframe_url): primary_iframe, primary_subdub, status = iframe_url, subdub, "success"; break
                return { "iframe_url": primary_iframe, "subdub_used": primary_subdub, "status": status, "all_subdub_iframes": all_iframes }

            async def detect_pages_and_episodes(watch_page):
                print("  → Mendeteksi pages dan episodes...")
                try:
                    await watch_page.wait_for_selector(".episode-list-container", timeout=15000)
                    available_pages, page_dropdown = [], None
                    all_dropdowns = await watch_page.query_selector_all(".episode-list .v-select")
                    for dropdown in all_dropdowns:
                        label_el = await dropdown.query_selector(".v-label")
                        if label_el and "Page" in await label_el.inner_text(): page_dropdown = dropdown; print("  → Dropdown 'Page' yang benar ditemukan."); break
                    if page_dropdown:
                        await page_dropdown.click(); await watch_page.wait_for_selector(".v-menu__content--active", timeout=5000)
                        option_elements = await watch_page.query_selector_all(".v-menu__content--active .v-list-item__title")
                        for option in option_elements:
                            text = await option.inner_text()
                            if text and re.match(r'^\s*(\d+-\d+)\s*$', text.strip()): available_pages.append(text.strip())
                        await watch_page.keyboard.press("Escape"); print(f"  → Halaman yang tersedia: {available_pages}")
                    
                    episode_items = await watch_page.query_selector_all(".episode-item"); total_episodes = 0
                    if available_pages and len(available_pages) > 1:
                        _, end_ep_str = available_pages[-1].split('-'); total_episodes = int(end_ep_str)
                    else:
                        total_episodes = len(episode_items)
                        if total_episodes > 0 and not available_pages: available_pages = [f"01-{total_episodes:02d}"]
                    print(f"  → Final - Pages: {available_pages}, Total episodes: {total_episodes}")
                    return { "available_pages": available_pages, "total_episodes": total_episodes, "has_multiple_pages": len(available_pages) > 1 }
                except Exception as e:
                    print(f"  → Error dalam detect_pages_and_episodes: {e}"); return { "available_pages": [], "total_episodes": 0, "has_multiple_pages": False }

            async def navigate_to_page(watch_page, target_page):
                try:
                    page_dropdown = None
                    all_dropdowns = await watch_page.query_selector_all(".episode-list .v-select")
                    for dropdown in all_dropdowns:
                        if "Page" in await (await dropdown.query_selector(".v-label")).inner_text(): page_dropdown = dropdown; break
                    if not page_dropdown: return False
                    await page_dropdown.click(); await watch_page.wait_for_selector(".v-menu__content--active", timeout=5000)
                    page_option = await watch_page.query_selector(f"//div[contains(@class, 'v-menu__content--active')]//div[contains(text(), '{target_page}')]")
                    if page_option: await page_option.click(); await asyncio.sleep(4); print(f"  ✓ Berhasil ganti ke page: {target_page}"); return True
                    else: await watch_page.keyboard.press("Escape"); return False
                except Exception as e: print(f"  ! Gagal navigasi ke page {target_page}: {e}"); return False

            async def get_fresh_episode_items(watch_page):
                try: await asyncio.sleep(2); await watch_page.wait_for_selector(".episode-item", timeout=10000); return await watch_page.query_selector_all(".episode-item")
                except: return []

            async def scrape_episodes_with_pages(watch_page, page_info, existing_episodes=[]):
                # (Sama seperti sebelumnya)
                available_pages = page_info["available_pages"]; total_episodes = page_info["total_episodes"]; has_multiple_pages = page_info["has_multiple_pages"]
                episodes_data = existing_episodes.copy(); total_scraped = 0; max_episodes_per_run = 20
                pages_to_scrape = available_pages if available_pages else []
                for page_index, target_page in enumerate(pages_to_scrape):
                    if total_scraped >= max_episodes_per_run: break
                    print(f"\n  📄 Memproses Page: {target_page}")
                    if has_multiple_pages and page_index > 0:
                        if not await navigate_to_page(watch_page, target_page): continue
                    episode_items = await get_fresh_episode_items(watch_page)
                    if not episode_items: continue
                    try: start_ep, _ = map(int, target_page.split('-')); page_start_index = start_ep - 1
                    except: page_start_index = 0
                    for local_ep_index in range(len(episode_items)):
                        global_ep_index = page_start_index + local_ep_index
                        if total_scraped >= max_episodes_per_run: break
                        if (global_ep_index < len(episodes_data) and episodes_data[global_ep_index].get('status') == 'success'): continue
                        try:
                            print(f"\n  --- Memproses Episode {global_ep_index + 1} ---")
                            episode_items = await get_fresh_episode_items(watch_page)
                            if local_ep_index >= len(episode_items): continue
                            ep_item = episode_items[local_ep_index]
                            ep_badge = await ep_item.query_selector(".episode-badge .v-chip__content")
                            ep_number = await ep_badge.inner_text() if ep_badge else f"EP {global_ep_index + 1}"
                            await ep_item.scroll_into_view_if_needed(); await ep_item.click()
                            await watch_page.wait_for_selector("iframe.player[src*='krussdomi']", timeout=15000)
                            await asyncio.sleep(2)
                            iframe_info = await get_all_subdub_iframes(watch_page, ep_number)
                            episode_data = { "number": ep_number, **iframe_info }
                            if global_ep_index < len(episodes_data): episodes_data[global_ep_index] = episode_data
                            else: episodes_data.append(episode_data)
                            total_scraped += 1
                            print(f"    ✓ Episode {ep_number} {'berhasil' if episode_data['status'] == 'success' else 'gagal'} di-scrape")
                        except Exception as ep_e:
                            print(f"    × Gagal memproses episode {global_ep_index + 1}: {type(ep_e).__name__}: {ep_e}")
                            episode_data = {"number": f"EP {global_ep_index + 1}", "status": "error"}
                            if global_ep_index < len(episodes_data): episodes_data[global_ep_index] = episode_data
                            else: episodes_data.append(episode_data)
                            total_scraped += 1
                return episodes_data, total_scraped
            
            # ============================================================
            # LOOP UTAMA (DIMODIFIKASI UNTUK DEBUGGING)
            # ============================================================
            
            detail_page = None
            watch_page = None
            
            try:
                full_detail_url = target_anime_url
                existing_anime = next((anime for anime in existing_data if anime.get('url_detail') == full_detail_url), None)
                
                detail_page = await context.new_page()
                await detail_page.goto(full_detail_url, timeout=90000)
                await detail_page.wait_for_selector(".anime-info-card", timeout=30000)
                
                title = await (await detail_page.query_selector(".anime-info-card .v-card__title span")).inner_text()
                print(f"Mulai memproses anime: {title}")

                watch_button = await detail_page.query_selector('a.v-btn[href*="/ep-"]')
                if not watch_button: raise Exception("Tombol 'Watch Now' tidak ditemukan.")
                
                first_episode_url = urljoin(base_url, await watch_button.get_attribute("href"))
                print(f"URL Episode Pertama: {first_episode_url}")
                
                watch_page = await context.new_page()
                
                # --- PERBAIKAN STRATEGI PEMUATAN HALAMAN ---
                print("Membuka halaman episode, menunggu hingga DOM dimuat...")
                await watch_page.goto(first_episode_url, timeout=90000, wait_until="domcontentloaded")
                print("DOM dimuat. Menunggu elemen player dan episode list...")
                await watch_page.wait_for_selector(".player-container", timeout=30000)
                await watch_page.wait_for_selector(".episode-list-container", timeout=30000)
                print("Elemen kunci ditemukan. Halaman episode berhasil dimuat.")
                # --- AKHIR PERBAIKAN ---
                
                page_info = await detect_pages_and_episodes(watch_page)
                available_subdub = await get_available_subdub_from_dropdown(watch_page)
                
                existing_episodes = existing_anime.get('episodes', []) if existing_anime else []
                episodes_data, total_scraped = await scrape_episodes_with_pages(watch_page, page_info, existing_episodes)

                anime_info = { "title": title.strip(), "url_detail": full_detail_url, "total_episodes": page_info["total_episodes"], "episodes": episodes_data, "available_subdub": available_subdub, "has_multiple_pages": page_info["has_multiple_pages"], "last_updated": time.time() }
                
                found = False
                for i, an in enumerate(existing_data):
                    if an.get('url_detail') == full_detail_url: existing_data[i] = anime_info; found = True; break
                if not found: existing_data.append(anime_info)

                print("\n" + "="*50 + "\nHASIL SCRAPING SELESAI\n" + "="*50)
                
                with open('anime_data.json', 'w', encoding='utf-8') as f:
                    json.dump(existing_data, f, ensure_ascii=False, indent=4)
                print("\nData berhasil disimpan ke anime_data.json")

            except Exception as e:
                print(f"!!! GAGAL MEMPROSES TARGET ANIME: {type(e).__name__}: {e}")
            finally:
                if watch_page and not watch_page.is_closed(): await watch_page.close()
                if detail_page and not detail_page.is_closed(): await detail_page.close()

        except Exception as e:
            print(f"Terjadi kesalahan fatal: {type(e).__name__}: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_kickass_anime())
