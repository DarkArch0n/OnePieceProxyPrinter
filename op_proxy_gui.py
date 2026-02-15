#!/usr/bin/env python3
"""
One Piece TCG Proxy Printer GUI - Visual interface for creating proxy card sheets.
"""

import os
import re
import sys
import time
import threading
from pathlib import Path
from typing import List, Tuple, Optional
from urllib.parse import quote
from io import BytesIO

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageTk
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Constants
CARD_WIDTH_INCHES = 2.5
CARD_HEIGHT_INCHES = 3.5
DEFAULT_DPI = 300
CARDS_PER_ROW = 3
CARDS_PER_COL = 3
CARDS_PER_PAGE = CARDS_PER_ROW * CARDS_PER_COL

# Preview sizing
PREVIEW_CARD_WIDTH = 120
PREVIEW_CARD_HEIGHT = int(PREVIEW_CARD_WIDTH * (CARD_HEIGHT_INCHES / CARD_WIDTH_INCHES))

# Cache / base directory - works both as script and frozen exe
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / "cache"

# Request headers
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}

# Custom images directory (set via GUI)
CUSTOM_IMAGES_DIR = None


# ---------------------------------------------------------------------------
# Card search / download helpers (carried over from op_proxy.py)
# ---------------------------------------------------------------------------

def setup_cache():
    CACHE_DIR.mkdir(exist_ok=True)


def sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', name.lower().replace(' ', '_'))


def find_local_image(identifier: str) -> Optional[Path]:
    if not CUSTOM_IMAGES_DIR:
        return None
    img_dir = Path(CUSTOM_IMAGES_DIR)
    if not img_dir.exists():
        return None
    card_id = identifier.upper()
    for pattern in [f"{card_id}.*", f"{card_id.lower()}.*", f"{sanitize_filename(identifier)}.*"]:
        for match in img_dir.glob(pattern):
            if match.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
                return match
    return None


def is_card_id(identifier: str) -> bool:
    return bool(re.match(r'^[A-Z]{2,3}\d{2}-\d{3}[A-Z]?$', identifier.upper()))


def parse_card_entry(entry: str) -> Tuple[Optional[str], int]:
    entry = entry.strip()
    if not entry or entry.startswith('#'):
        return None, 0
    match = re.match(r'^(\d+)x?\s*(.+)$', entry, re.IGNORECASE)
    if match:
        return match.group(2).strip(), int(match.group(1))
    return entry, 1


# ---- Sources ---------------------------------------------------------------

def search_card_limitless_cdn(identifier: str, lang: str = "EN") -> Optional[dict]:
    if not is_card_id(identifier):
        return None
    card_id = identifier.upper()
    set_code = card_id.split('-')[0]
    url = f"https://limitlesstcg.nyc3.digitaloceanspaces.com/one-piece/{set_code}/{card_id}_{lang}.webp"
    try:
        resp = requests.head(url, headers=HEADERS, timeout=5)
        if resp.status_code == 200:
            return {'name': identifier, 'image_url': url, 'source': 'Limitless CDN'}
    except Exception:
        pass
    return None


def search_card_opcgdb(identifier: str) -> Optional[dict]:
    try:
        card_id = identifier.upper() if is_card_id(identifier) else identifier
        resp = requests.get(f"https://opcgdb.com/cards/{card_id}", headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            img = soup.select_one('img.card-image, .card img, img[alt*="card"], img[src*="/cards/"]')
            if img:
                src = img.get('src', '') or img.get('data-src', '')
                if src:
                    full = src if src.startswith('http') else f"https://opcgdb.com{src}"
                    return {'name': identifier, 'image_url': full, 'source': 'OPCGDB'}
    except Exception:
        pass
    return None


def search_card_limitless(identifier: str) -> Optional[dict]:
    try:
        url = (f"https://onepiece.limitlesstcg.com/cards/{identifier.upper()}"
               if is_card_id(identifier)
               else f"https://onepiece.limitlesstcg.com/cards?q={quote(identifier)}")
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            img = soup.select_one('img.card, .card-image img, img[src*="/cards/"]')
            if img:
                src = img.get('src', '')
                if src:
                    full = src if src.startswith('http') else f"https://onepiece.limitlesstcg.com{src}"
                    return {'name': identifier, 'image_url': full, 'source': 'Limitless'}
    except Exception:
        pass
    return None


def search_card_onepiecetopdecks(identifier: str) -> Optional[dict]:
    try:
        url = (f"https://onepiecetopdecks.com/card/{identifier.upper()}/"
               if is_card_id(identifier)
               else f"https://onepiecetopdecks.com/?s={quote(identifier)}&post_type=card")
        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            img = soup.select_one('img.card-image, .card-img img, article img[src*="card"], .wp-post-image')
            if img:
                src = img.get('data-src') or img.get('src', '')
                if src and any(k in src.lower() for k in ('card', 'op', 'st')):
                    return {'name': identifier, 'image_url': src, 'source': 'Top Decks'}
    except Exception:
        pass
    return None


def search_card_official(identifier: str) -> Optional[dict]:
    try:
        card_id = identifier.upper() if is_card_id(identifier) else None
        url = (f"https://en.onepiece-cardgame.com/cardlist/?series={card_id[:4]}"
               if card_id
               else f"https://en.onepiece-cardgame.com/cardlist/?freewords={quote(identifier)}")
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for img in soup.select('div.resultCol a img, .cardImg img, img[data-src*="card"]'):
                src = img.get('data-src') or img.get('src', '')
                if card_id and card_id.lower() in src.lower():
                    full = src if src.startswith('http') else f"https://en.onepiece-cardgame.com{src}"
                    return {'name': identifier, 'image_url': full, 'source': 'Official'}
                elif not card_id and src:
                    full = src if src.startswith('http') else f"https://en.onepiece-cardgame.com{src}"
                    return {'name': identifier, 'image_url': full, 'source': 'Official'}
    except Exception:
        pass
    return None


def search_card_direct_cdn(identifier: str, lang: str = "EN") -> Optional[dict]:
    if not is_card_id(identifier):
        return None
    card_id = identifier.upper()
    base = "https://www.onepiece-cardgame.com" if lang == "JP" else "https://en.onepiece-cardgame.com"
    url = f"{base}/images/cardlist/card/{card_id}.png"
    try:
        resp = requests.head(url, headers=HEADERS, timeout=5)
        if resp.status_code == 200:
            return {'name': identifier, 'image_url': url, 'source': 'Official CDN'}
    except Exception:
        pass
    return None


def search_card_tcgplayer(identifier: str) -> Optional[dict]:
    try:
        search_url = f"https://www.tcgplayer.com/search/one-piece-card-game/product?q={quote(f'One Piece {identifier}')}"
        resp = requests.get(search_url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            img = soup.select_one('img.product-image__image, img[data-testid="product-image"]')
            if img:
                src = img.get('src', '')
                if src and 'tcgplayer' in src:
                    return {'name': identifier, 'image_url': src, 'source': 'TCGPlayer'}
    except Exception:
        pass
    return None


def fetch_card_data(identifier: str, lang: str = "EN") -> Optional[dict]:
    """Fetch card data trying sources in priority order."""
    local = find_local_image(identifier)
    if local:
        return {'name': identifier, 'local_path': str(local), 'source': 'Local'}

    card = search_card_limitless_cdn(identifier, lang)
    if card:
        return card

    for _name, fn in [
        ("OPCGDB", search_card_opcgdb),
        ("Limitless", search_card_limitless),
        ("Top Decks", search_card_onepiecetopdecks),
        ("Official", search_card_official),
        ("TCGPlayer", search_card_tcgplayer),
    ]:
        card = fn(identifier)
        if card and card.get('image_url'):
            return card

    card = search_card_direct_cdn(identifier, lang)
    if card:
        return card
    return None


def get_image_url(card_data: dict) -> Optional[str]:
    for field in ('image_url', 'imageUrl', 'image', 'img', 'picture'):
        url = card_data.get(field)
        if url:
            if not url.startswith('http'):
                url = f"https:{url}" if url.startswith('//') else url
            return url
    return None


def download_image(url: str, card_name: str, use_cache: bool = True) -> Optional[Path]:
    filename = sanitize_filename(card_name) + ".png"
    cache_path = CACHE_DIR / filename
    if use_cache and cache_path.exists():
        return cache_path
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        with open(cache_path, 'wb') as f:
            f.write(resp.content)
        return cache_path
    except requests.exceptions.RequestException:
        return None


def resize_card_image(image_path: Path, dpi: int = DEFAULT_DPI) -> Image.Image:
    target_w = int(CARD_WIDTH_INCHES * dpi)
    target_h = int(CARD_HEIGHT_INCHES * dpi)
    img = Image.open(image_path)
    if img.mode in ('RGBA', 'P'):
        bg = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        bg.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
        img = bg
    elif img.mode != 'RGB':
        img = img.convert('RGB')
    r = img.width / img.height
    tr = target_w / target_h
    if r > tr:
        nw, nh = int(target_h * r), target_h
    else:
        nw, nh = target_w, int(target_w / r)
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - target_w) // 2
    top = (nh - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def create_pdf(cards: List[Tuple[str, Image.Image]], output_path: str,
               dpi: int = DEFAULT_DPI):
    pw, ph = LETTER
    cw = CARD_WIDTH_INCHES * 72
    ch = CARD_HEIGHT_INCHES * 72
    gw = CARDS_PER_ROW * cw
    gh = CARDS_PER_COL * ch
    mx = (pw - gw) / 2
    my = (ph - gh) / 2
    c = canvas.Canvas(output_path, pagesize=LETTER)
    idx = 0
    total = len(cards)
    while idx < total:
        for row in range(CARDS_PER_COL):
            for col in range(CARDS_PER_ROW):
                if idx >= total:
                    break
                name, cimg = cards[idx]
                x = mx + col * cw
                y = ph - my - (row + 1) * ch
                tmp = CACHE_DIR / f"temp_{idx}.jpg"
                cimg.save(tmp, "JPEG", quality=95)
                c.drawImage(str(tmp), x, y, width=cw, height=ch)
                tmp.unlink()
                idx += 1
        if idx < total:
            c.showPage()
    c.save()


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class OnePieceProxyGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("One Piece TCG Proxy Printer")
        self.root.geometry("1200x800")
        self.root.minsize(900, 600)

        self.card_images: List[Tuple[str, Image.Image]] = []
        self.preview_images = []
        self.card_photo_refs = []
        self.use_japanese = tk.BooleanVar(value=False)
        self.custom_image_dir = tk.StringVar(value="")

        self.setup_ui()
        setup_cache()

    # ---- UI Setup ----------------------------------------------------------

    def setup_ui(self):
        main = ttk.Frame(self.root, padding="10")
        main.pack(fill=tk.BOTH, expand=True)

        # --- Left panel: decklist -------------------------------------------
        left = ttk.LabelFrame(main, text="Decklist", padding="10")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 5))

        text_frame = ttk.Frame(left)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.decklist_text = tk.Text(text_frame, width=35, height=20, wrap=tk.NONE)
        sy = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.decklist_text.yview)
        sx = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL, command=self.decklist_text.xview)
        self.decklist_text.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.decklist_text.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        text_frame.grid_rowconfigure(0, weight=1)
        text_frame.grid_columnconfigure(0, weight=1)

        example = (
            "# One Piece TCG Decklist\n"
            "# Format: [qty]x Card ID or Name\n"
            "# e.g.  OP01-001, ST01-012\n\n"
            "4x OP01-001\n"
            "4x OP01-002\n"
            "2x ST01-012\n"
            "1x OP01-120\n"
        )
        self.decklist_text.insert(tk.END, example)

        # Buttons
        btn = ttk.Frame(left)
        btn.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btn, text="Load File", command=self.load_file).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn, text="Clear", command=self.clear_decklist).pack(side=tk.LEFT, padx=(0, 5))

        self.fetch_btn = ttk.Button(btn, text="Fetch Cards", command=self.fetch_cards)
        self.fetch_btn.pack(side=tk.RIGHT)

        # Options
        opts = ttk.LabelFrame(left, text="Options", padding="5")
        opts.pack(fill=tk.X, pady=(10, 0))

        ttk.Checkbutton(opts, text="Use Japanese images",
                        variable=self.use_japanese).pack(anchor=tk.W)

        img_row = ttk.Frame(opts)
        img_row.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(img_row, text="Custom images:").pack(side=tk.LEFT)
        ttk.Entry(img_row, textvariable=self.custom_image_dir,
                  width=15).pack(side=tk.LEFT, padx=(5, 5), fill=tk.X, expand=True)
        ttk.Button(img_row, text="Browse",
                   command=self.browse_image_dir).pack(side=tk.LEFT)

        # --- Right panel: preview -------------------------------------------
        right = ttk.LabelFrame(main, text="Card Preview", padding="10")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))

        pcontainer = ttk.Frame(right)
        pcontainer.pack(fill=tk.BOTH, expand=True)

        self.preview_canvas = tk.Canvas(pcontainer, bg='#1a1a2e')
        psy = ttk.Scrollbar(pcontainer, orient=tk.VERTICAL, command=self.preview_canvas.yview)
        psx = ttk.Scrollbar(pcontainer, orient=tk.HORIZONTAL, command=self.preview_canvas.xview)
        self.preview_canvas.configure(yscrollcommand=psy.set, xscrollcommand=psx.set)
        psy.pack(side=tk.RIGHT, fill=tk.Y)
        psx.pack(side=tk.BOTTOM, fill=tk.X)
        self.preview_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.cards_frame = ttk.Frame(self.preview_canvas)
        self.canvas_window = self.preview_canvas.create_window(
            (0, 0), window=self.cards_frame, anchor='nw')

        self.cards_frame.bind('<Configure>', self._on_frame_cfg)
        self.preview_canvas.bind('<Configure>', self._on_canvas_cfg)
        self.preview_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # Bottom bar
        bottom = ttk.Frame(right)
        bottom.pack(fill=tk.X, pady=(10, 0))

        self.progress_var = tk.DoubleVar()
        ttk.Progressbar(bottom, variable=self.progress_var, maximum=100).pack(fill=tk.X, pady=(0, 5))

        self.status_var = tk.StringVar(value="Ready - Enter your decklist and click 'Fetch Cards'")
        ttk.Label(bottom, textvariable=self.status_var).pack(anchor=tk.W)

        export_row = ttk.Frame(bottom)
        export_row.pack(fill=tk.X, pady=(10, 0))
        self.export_btn = ttk.Button(export_row, text="Export PDF",
                                      command=self.export_pdf, state=tk.DISABLED)
        self.export_btn.pack(side=tk.RIGHT)
        self.count_var = tk.StringVar(value="")
        ttk.Label(export_row, textvariable=self.count_var).pack(side=tk.LEFT)

    # ---- Canvas helpers ----------------------------------------------------

    def _on_frame_cfg(self, _):
        self.preview_canvas.configure(scrollregion=self.preview_canvas.bbox("all"))

    def _on_canvas_cfg(self, e):
        self.preview_canvas.itemconfig(self.canvas_window, width=e.width)

    def _on_mousewheel(self, e):
        self.preview_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    # ---- Actions -----------------------------------------------------------

    def browse_image_dir(self):
        d = filedialog.askdirectory(title="Select Custom Card Images Folder")
        if d:
            self.custom_image_dir.set(d)

    def load_file(self):
        fp = filedialog.askopenfilename(
            title="Select Decklist File",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if fp:
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.decklist_text.delete(1.0, tk.END)
                self.decklist_text.insert(tk.END, content)
                self.status_var.set(f"Loaded: {os.path.basename(fp)}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load file: {e}")

    def clear_decklist(self):
        self.decklist_text.delete(1.0, tk.END)
        self.clear_preview()
        self.status_var.set("Decklist cleared")

    def clear_preview(self):
        for w in self.cards_frame.winfo_children():
            w.destroy()
        self.card_images.clear()
        self.preview_images.clear()
        self.card_photo_refs.clear()
        self.export_btn.config(state=tk.DISABLED)
        self.count_var.set("")
        self.progress_var.set(0)

    def parse_decklist(self) -> List[Tuple[str, int]]:
        cards = []
        for line in self.decklist_text.get(1.0, tk.END).split('\n'):
            ident, qty = parse_card_entry(line)
            if ident:
                cards.append((ident, qty))
        return cards

    # ---- Fetch -------------------------------------------------------------

    def fetch_cards(self):
        entries = self.parse_decklist()
        if not entries:
            messagebox.showwarning("No Cards", "Please enter some cards in the decklist.")
            return
        self.clear_preview()
        self.fetch_btn.config(state=tk.DISABLED)
        self.status_var.set("Fetching cards...")

        # Apply custom image dir
        global CUSTOM_IMAGES_DIR
        val = self.custom_image_dir.get().strip()
        CUSTOM_IMAGES_DIR = val if val else None

        t = threading.Thread(target=self._fetch_thread, args=(entries,), daemon=True)
        t.start()

    def _fetch_thread(self, entries: List[Tuple[str, int]]):
        total = sum(q for _, q in entries)
        fetched = 0
        errors = []
        lang = "JP" if self.use_japanese.get() else "EN"

        for identifier, quantity in entries:
            self.root.after(0, lambda n=identifier: self.status_var.set(f"Fetching: {n}..."))
            time.sleep(0.2)

            card_data = fetch_card_data(identifier, lang=lang)
            if not card_data:
                errors.append(identifier)
                fetched += quantity
                self.root.after(0, lambda f=fetched: self.progress_var.set((f / total) * 100))
                continue

            actual_name = card_data.get('name', identifier)
            source = card_data.get('source', '')

            # Resolve image
            if 'local_path' in card_data:
                image_path = Path(card_data['local_path'])
            else:
                img_url = get_image_url(card_data)
                if not img_url:
                    errors.append(identifier)
                    fetched += quantity
                    self.root.after(0, lambda f=fetched: self.progress_var.set((f / total) * 100))
                    continue
                image_path = download_image(img_url, actual_name)
                if not image_path:
                    errors.append(identifier)
                    fetched += quantity
                    self.root.after(0, lambda f=fetched: self.progress_var.set((f / total) * 100))
                    continue

            pdf_img = resize_card_image(image_path)
            preview = Image.open(image_path)
            preview.thumbnail((PREVIEW_CARD_WIDTH, PREVIEW_CARD_HEIGHT), Image.Resampling.LANCZOS)

            label = f"{actual_name} [{source}]" if source else actual_name

            for _ in range(quantity):
                self.card_images.append((actual_name, pdf_img))
                self.root.after(0, lambda img=preview.copy(), nm=label:
                               self._add_preview(img, nm))
                fetched += 1
                self.root.after(0, lambda f=fetched: self.progress_var.set((f / total) * 100))

        self.root.after(0, lambda: self._fetch_done(total, len(errors), errors))

    def _add_preview(self, pil_img: Image.Image, card_name: str):
        photo = ImageTk.PhotoImage(pil_img)
        self.card_photo_refs.append(photo)
        n = len(self.card_photo_refs) - 1
        cpr = max(1, (self.preview_canvas.winfo_width() - 20) // (PREVIEW_CARD_WIDTH + 10))
        if cpr < 1:
            cpr = 5
        fr = ttk.Frame(self.cards_frame)
        fr.grid(row=n // cpr, column=n % cpr, padx=5, pady=5, sticky='nw')
        ttk.Label(fr, image=photo).pack()
        disp = card_name[:22] + "..." if len(card_name) > 22 else card_name
        ttk.Label(fr, text=disp, font=('TkDefaultFont', 8)).pack()
        self.cards_frame.update_idletasks()
        self.preview_canvas.configure(scrollregion=self.preview_canvas.bbox("all"))

    def _fetch_done(self, total, err_count, errors):
        self.fetch_btn.config(state=tk.NORMAL)
        if self.card_images:
            self.export_btn.config(state=tk.NORMAL)
            pages = (len(self.card_images) + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE
            self.count_var.set(f"{len(self.card_images)} cards ({pages} pages)")
        if err_count:
            msg = f"Completed with {err_count} error(s): {', '.join(errors[:5])}"
            if err_count > 5:
                msg += f" and {err_count - 5} more"
            self.status_var.set(msg)
        else:
            self.status_var.set(f"Successfully fetched {total} cards!")

    # ---- Export ------------------------------------------------------------

    def export_pdf(self):
        if not self.card_images:
            messagebox.showwarning("No Cards", "No cards to export. Fetch cards first.")
            return
        fp = filedialog.asksaveasfilename(
            title="Save PDF", defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")])
        if not fp:
            return
        try:
            self.status_var.set("Generating PDF...")
            self.root.update()
            create_pdf(self.card_images, fp)
            pages = (len(self.card_images) + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE
            self.status_var.set(f"PDF saved: {os.path.basename(fp)}")
            messagebox.showinfo(
                "Success",
                f"Created {os.path.basename(fp)}\n"
                f"{len(self.card_images)} cards on {pages} page(s)\n\n"
                f"Print at 100% scale for correct card size.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create PDF: {e}")
            self.status_var.set("PDF export failed")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    root = tk.Tk()
    try:
        root.iconbitmap(default='')
    except Exception:
        pass
    style = ttk.Style()
    if 'clam' in style.theme_names():
        style.theme_use('clam')
    OnePieceProxyGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
