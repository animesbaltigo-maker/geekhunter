"""Automate or assist Mercado Livre affiliate link generation.

This script uses a persistent browser profile so you only need to log in once.

Commands:
  python affiliate_panel.py open
  python affiliate_panel.py generate --product-url https://www.mercadolivre.com.br/...
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

AFFILIATE_HOME = "https://afiliados.mercadolivre.com.br/"
MELI_RE = re.compile(r"https://meli\.la/[A-Za-z0-9]+")
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Assistente do painel de afiliados Mercado Livre.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("open", help="Abre o painel para login/configuracao manual.")
    gen = sub.add_parser("generate", help="Tenta gerar/capturar um link meli.la para um produto.")
    gen.add_argument("--product-url", required=True, help="URL do produto do Mercado Livre.")
    args = parser.parse_args()

    if args.cmd == "open":
        open_panel()
    else:
        generate_link(args.product_url)


def open_panel() -> None:
    with browser_context() as page:
        page.goto(AFFILIATE_HOME, wait_until="domcontentloaded")
        print("\nPainel aberto.")
        print("Faca login se precisar e navegue ate 'Gerar link / ID de produto'.")
        input("Quando terminar, pressione Enter aqui para fechar o navegador...")


def generate_link(product_url: str) -> None:
    with browser_context() as page:
        page.goto(AFFILIATE_HOME, wait_until="domcontentloaded")
        print("\nTentando localizar o gerador de links...")

        if not try_auto_generate(page, product_url):
            print("\nNao consegui automatizar todos os cliques ainda.")
            print("No navegador aberto, va ate 'Gerar link / ID de produto', cole este produto e gere o link:")
            print(product_url)
            print("\nDepois deixe o link meli.la visivel na tela.")
            input("Quando o link aparecer, pressione Enter aqui para eu capturar...")

        link = find_meli_link(page)
        if link:
            print(f"\nLINK_AFILIADO={link}")
            return

        print("\nNao encontrei link https://meli.la/... na pagina.")
        print("Clique no botao de copiar link no painel e cole aqui manualmente por enquanto.")


def try_auto_generate(page, product_url: str) -> bool:
    """Best-effort automation for the current panel UI.

    The affiliate panel is not a public API, so this tries common labels/buttons
    and falls back to manual capture when the UI changes.
    """
    maybe_click_text(page, "Gerar link")
    maybe_click_text(page, "ID de produto")
    maybe_click_text(page, "Gerar link / ID de produto")

    inputs = page.locator("input, textarea")
    try:
        count = inputs.count()
    except PlaywrightTimeoutError:
        return False

    filled = False
    for index in range(min(count, 8)):
        field = inputs.nth(index)
        try:
            if not field.is_visible(timeout=1000):
                continue
            value = field.input_value(timeout=1000) if field.evaluate("el => 'value' in el") else ""
            placeholder = field.get_attribute("placeholder") or ""
            label_hint = f"{value} {placeholder}".lower()
            if value and "http" not in label_hint:
                continue
            field.fill(product_url, timeout=3000)
            filled = True
            break
        except Exception:
            continue

    if not filled:
        return False

    for text in ("Gerar", "Criar", "Adicionar", "Confirmar"):
        if maybe_click_text(page, text):
            page.wait_for_timeout(2500)
            return bool(find_meli_link(page))
    return False


def maybe_click_text(page, text: str) -> bool:
    loc = page.get_by_text(text, exact=False)
    try:
        count = loc.count()
        if count == 0:
            return False
        loc.first.click(timeout=3000)
        page.wait_for_timeout(800)
        return True
    except Exception:
        return False


def find_meli_link(page) -> str | None:
    page.wait_for_timeout(1000)

    candidates: list[str] = []
    try:
        text = page.locator("body").inner_text(timeout=5000)
        candidates.extend(MELI_RE.findall(text))
    except Exception:
        pass

    try:
        values = page.locator("input, textarea").evaluate_all(
            "els => els.map(el => el.value || el.textContent || '').filter(Boolean)"
        )
        for value in values:
            candidates.extend(MELI_RE.findall(value))
    except Exception:
        pass

    return candidates[-1] if candidates else None


def browser_context():
    class BrowserSession:
        def __enter__(self):
            profile_dir = Path(os.getenv("BROWSER_PROFILE_DIR", "browser_profile/ml_affiliate"))
            profile_dir.mkdir(parents=True, exist_ok=True)
            self.playwright = sync_playwright().start()
            chrome_path = next((path for path in CHROME_PATHS if Path(path).exists()), None)
            headless = os.getenv("BROWSER_HEADLESS", "").strip().lower() in {"1", "true", "yes", "sim", "on"}
            try:
                launch_args = {
                    "headless": headless,
                    "viewport": {"width": 1280, "height": 900},
                    "args": ["--no-sandbox", "--disable-dev-shm-usage"],
                }
                if chrome_path:
                    launch_args["executable_path"] = chrome_path
                else:
                    launch_args["channel"] = "chrome"
                self.context = self.playwright.chromium.launch_persistent_context(
                    str(profile_dir),
                    **launch_args,
                )
            except Exception:
                self.context = self.playwright.chromium.launch_persistent_context(
                    str(profile_dir),
                    headless=headless,
                    viewport={"width": 1280, "height": 900},
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            return self.page

        def __exit__(self, exc_type, exc, tb):
            self.context.close()
            self.playwright.stop()

    return BrowserSession()


if __name__ == "__main__":
    main()
