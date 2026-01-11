#!/usr/bin/env python3
import os
import re
import sys
import time
import datetime
from urllib.parse import urljoin
from typing import List, Dict, Any
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# --------------- 工具 ---------------
def log(msg):
    print(f"[renew] {msg}", flush=True)

def now_utc_str():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

def now_bjt_str():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S (UTC+8)")

# --------------- Playwright 便捷函数 ---------------
def fill_first_visible(page, selectors, value, timeout=8000):
    for s in selectors:
        try:
            loc = page.locator(s).first
            loc.wait_for(state="visible", timeout=timeout)
            try:
                loc.click(timeout=2000)
            except Exception:
                pass
            loc.fill(value, timeout=timeout)
            return True
        except Exception:
            continue
    return False

def click_any(page, selectors, timeout=8000):
    for s in selectors:
        try:
            loc = page.locator(s).first
            loc.wait_for(state="visible", timeout=timeout)
            loc.scroll_into_view_if_needed(timeout=2000)
            loc.click(timeout=timeout)
            return True
        except Exception:
            continue
    return False

def click_by_text_candidates(page, patterns, timeout=8000):
    for pat in patterns:
        regex = re.compile(pat, re.I)
        candidates = [
            page.get_by_role("button", name=regex).first,
            page.get_by_role("link", name=regex).first,
            page.get_by_text(regex).first,
        ]
        for loc in candidates:
            try:
                loc.wait_for(state="visible", timeout=timeout)
                loc.scroll_into_view_if_needed(timeout=2000)
                loc.click(timeout=timeout)
                return True
            except Exception:
                continue
    return False

def wait_for_any(page, selectors, state="visible", timeout=10000):
    deadline = time.time() + timeout/1000.0
    last_err = None
    for s in selectors:
        try:
            page.locator(s).first.wait_for(state=state, timeout=timeout)
            return True
        except Exception as e:
            last_err = e
            if time.time() > deadline:
                break
    if last_err:
        log(f"wait_for_any last error: {last_err}")
    return False

# --------------- 页面流程 ---------------
def login(page, base_url, email, password):
    login_url = f"{base_url.rstrip('/')}/login"
    log(f"访问登录页: {login_url}")
    page.goto(login_url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=20000)

    email_selectors = [
        'input[name="email"]',
        'input[type="email"]',
        'input#email',
        'input[placeholder*="Email" i]',
        'input[placeholder*="Correo" i]',
        'input[name*="user" i]',
        'input[name*="correo" i]',
    ]
    pwd_selectors = [
        'input[name="password"]',
        'input[type="password"]',
        'input#password',
        'input[placeholder*="Password" i]',
        'input[placeholder*="Contraseña" i]',
    ]

    ok_email = fill_first_visible(page, email_selectors, email)
    ok_pwd = fill_first_visible(page, pwd_selectors, password)
    if not (ok_email and ok_pwd):
        log("未找到邮箱/密码输入框，可能需要更新选择器。")
        return False

    login_clicked = click_any(page, [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Login")',
        'button:has-text("Log in")',
        'button:has-text("Sign in")',
        'button:has-text("Acceder")',
        'button:has-text("Iniciar")',
        'button:has-text("Entrar")',
        'text=Login',
        'text=Sign in',
        'text=Acceder',
        'text=Iniciar sesión',
    ], timeout=8000)

    if not login_clicked:
        try:
            page.locator(pwd_selectors[0]).first.press("Enter", timeout=2000)
        except Exception:
            pass

    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except PWTimeout:
        pass

    login_ok = False
    try:
        if "/login" not in page.url:
            login_ok = True
    except Exception:
        pass

    if not login_ok:
        login_ok = wait_for_any(page, [
            'a:has-text("Contracts")',
            'text=Contracts',
            'a:has-text("Contratos")',
            'text=Contratos',
        ], timeout=8000)

    log(f"登录状态: {'成功' if login_ok else '失败'}")
    return login_ok

def goto_contracts(page):
    log("进入 Contracts 页面")
    ok = click_by_text_candidates(page, [
        r'\bContracts?\b',
        r'\bContratos?\b',
        r'合同|合约',
    ], timeout=8000)

    if not ok:
        ok = click_any(page, [
            'a[href*="contract"]',
            'a[href*="contrato"]',
            'a[href*="/contracts"]',
        ], timeout=6000)

    if not ok:
        log("未找到 Contracts 入口")
        return False

    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        pass
    return True

def renew_plus_12h(page):
    log("尝试点击 Renew +12h")
    def on_dialog(dialog):
        log(f"弹窗: {dialog.message}")
        try:
            dialog.accept()
        except Exception:
            pass
    page.on("dialog", on_dialog)

    patterns = [
        r'renew\s*\+?\s*12\s*h',
        r'renew\s*\+?\s*12\s*hour',
        r'renovar.*\+?\s*12',
        r'extend.*\+?\s*12',
        r'extender.*\+?\s*12',
        r'续.*12',
        r'延长.*12',
        r'\+?\s*12\s*(hours?|h)\b',
    ]

    ok = click_by_text_candidates(page, patterns, timeout=8000)
    if not ok:
        ok = click_any(page, [
            'button:has-text("+12")',
            'a:has-text("+12")',
            'button:has-text("Renew")',
            'a:has-text("Renew")',
            'button:has-text("Renovar")',
            'a:has-text("Renovar")',
        ], timeout=8000)

    if ok:
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PWTimeout:
            pass
    return ok

def detect_renew_success(page) -> bool:
    patterns = [
        r'\brenew(ed|al).*(success|complete|done)\b',
        r'\bsuccess(fully)?\b.*\b(renew|extend)',
        r'\b(renewed|extended)\b',
        r'renovad[oa]',
        r'续期成功|已续期|延长成功|已延长',
    ]
    try:
        body_text = page.text_content("body") or ""
        for pat in patterns:
            if re.search(pat, body_text, re.I):
                return True
    except Exception:
        pass
    return False

# --------------- 详情链接/点击兜底 ---------------
def collect_detail_urls(page, max_items: int = 0) -> List[str]:
    urls: List[str] = []

    def add_from_locator(locator) -> bool:
        try:
            cnt = locator.count()
        except Exception:
            cnt = 0
        for i in range(cnt):
            try:
                href = locator.nth(i).get_attribute("href")
                if not href:
                    continue
                absu = urljoin(page.url, href)
                if absu not in urls:
                    urls.append(absu)
                    if max_items and len(urls) >= max_items:
                        return True
            except Exception:
                continue
        return False

    patterns = [
        page.get_by_role("link", name=re.compile(r'view\s*details?', re.I)),
        page.get_by_role("link", name=re.compile(r'\bdetails?\b', re.I)),
        page.get_by_role("link", name=re.compile(r'ver\s*detalles?', re.I)),
        page.locator('a:has-text("View Details")'),
        page.locator('a:has-text("View")'),
        page.locator('a:has-text("Details")'),
        page.locator('a:has-text("Ver")'),
        page.locator('a[href*="detail"]'),
        page.locator('a[href*="/contract"]'),
        page.locator('a[href*="/contracts"]'),
    ]

    for loc in patterns:
        try:
            if add_from_locator(loc):
                break
        except Exception:
            continue

    return urls

def process_by_clicking_on_list(page, count_target: int) -> List[Dict[str, Any]]:
    # 当列表没有明显的链接 href 时，逐条点击进入详情 → 续期 → 返回列表
    results: List[Dict[str, Any]] = []
    if count_target <= 0:
        return results

    for idx in range(count_target):
        # 每次重新定位首个“详情”按钮，避免索引变化
        details_locator = page.locator(
            'a:has-text("View Details"), button:has-text("View Details"), '
            'a:has-text("View"), button:has-text("View"), '
            'a:has-text("Details"), button:has-text("Details"), '
            'a:has-text("Ver"), button:has-text("Ver")'
        )
        try:
            if details_locator.count() == 0:
                log("在列表页未找到可点击的详情按钮。")
                break
            details_locator.first.scroll_into_view_if_needed(timeout=3000)
            details_locator.first.click(timeout=8000)
        except Exception as e:
            log(f"点击详情按钮失败: {e}")
            break

        # 到了详情页，执行续期
        try:
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PWTimeout:
                pass
            clicked = renew_plus_12h(page)
            success = detect_renew_success(page) if clicked else False
            results.append({
                "clicked": clicked,
                "success": success,
                "message": "ok" if success else ("clicked" if clicked else "no_button"),
            })
        finally:
            # 返回 Contracts 列表
            try:
                page.go_back(wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                # 兜底再点回菜单
                goto_contracts(page)
    return results

# --------------- README 写入（仅显示成功与时间） ---------------
def update_readme_on_success_multi(readme_path: str):
    section_title = "## Greathost 续期状态"
    start_marker = "<!-- GREATHOST-RENEW-STATUS:START -->"
    end_marker = "<!-- GREATHOST-RENEW-STATUS:END -->"
    success_line = f"✅ 续期成功 | 时间: {now_utc_str()} / {now_bjt_str()}"

    block = (
        f"{section_title}\n\n"
        f"{start_marker}\n"
        f"{success_line}\n"
        f"{end_marker}\n"
    )

    if not os.path.exists(readme_path):
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(f"# README\n\n{block}\n")
        log("README 不存在，已创建并写入成功状态。")
        return

    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    if start_marker in content and end_marker in content:
        pattern = re.compile(rf"{re.escape(start_marker)}.*?{re.escape(end_marker)}", re.S)
        new_content = pattern.sub(f"{start_marker}\n{success_line}\n{end_marker}", content)
    else:
        new_content = content.rstrip() + "\n\n" + block + "\n"

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    log("已将续期成功写入 README.md（仅显示状态与时间）")

# --------------- 主流程（单账号，最多两台） ---------------
def main():
    base_url = os.getenv("BASE_URL", "https://greathost.es").rstrip("/")
    headless = os.getenv("HEADLESS", "1") != "0"
    readme_path = os.getenv("README_PATH", "README.md")
    try:
        max_servers = int(os.getenv("MAX_SERVERS", "2"))
    except Exception:
        max_servers = 2
    require_all_success = os.getenv("REQUIRE_ALL_SUCCESS", "1") == "1"

    email = os.getenv("GREATHOST_EMAIL", "").strip()
    password = os.getenv("GREATHOST_PASSWORD", "")

    if not email or not password:
        log("请设置 GREATHOST_EMAIL / GREATHOST_PASSWORD")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118 Safari/537.36",
            locale="en-US",
            timezone_id="UTC",
        )
        page = context.new_page()
        page.set_default_timeout(30000)

        try:
            if not login(page, base_url, email, password):
                log("登录失败")
                sys.exit(2)

            if not goto_contracts(page):
                log("进入 Contracts 失败")
                sys.exit(3)

            # 优先：收集详情链接并逐个新页处理
            detail_urls = collect_detail_urls(page, max_items=max_servers if max_servers > 0 else 0)
            results: List[Dict[str, Any]] = []

            if detail_urls:
                log(f"发现 {len(detail_urls)} 个详情链接，准备续期。")
                for i, url in enumerate(detail_urls, 1):
                    pg = context.new_page()
                    pg.set_default_timeout(30000)
                    info = {"clicked": False, "success": False, "message": ""}
                    try:
                        pg.goto(url, wait_until="domcontentloaded")
                        try:
                            pg.wait_for_load_state("networkidle", timeout=15000)
                        except PWTimeout:
                            pass
                        clicked = renew_plus_12h(pg)
                        success = detect_renew_success(pg) if clicked else False
                        info.update({"clicked": clicked, "success": success, "message": "ok" if success else ("clicked" if clicked else "no_button")})
                    finally:
                        try: pg.close()
                        except Exception: pass
                    results.append(info)
            else:
                # 兜底：列表页逐个点击进入详情
                target = max_servers if max_servers > 0 else 2
                log(f"未收集到链接，改为在列表页逐个点击处理，目标 {target} 台。")
                results = process_by_clicking_on_list(page, target)

            succ = [r for r in results if r.get("success")]
            log(f"续期结果：成功 {len(succ)}/{len(results)}")

            # 控制 README 更新策略
            should_update = (len(results) > 0) and (
                all(r.get("success") for r in results) if require_all_success else any(r.get("success") for r in results)
            )

            if should_update:
                update_readme_on_success_multi(readme_path)
                sys.exit(0)
            else:
                log("本次未达到写入 README 的条件（可能按钮未开放或冷却中）。")
                sys.exit(5)

        finally:
            try: context.close()
            except Exception: pass
            try: browser.close()
            except Exception: pass

if __name__ == "__main__":
    main()
