#!/usr/bin/env python3
"""
One Piece TCG Proxy Printer - Fetch and format One Piece cards for printing.
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import List, Tuple, Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from PIL import Image
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

# Constants
CARD_WIDTH_INCHES = 2.5
CARD_HEIGHT_INCHES = 3.5
DEFAULT_DPI = 300
CARDS_PER_ROW = 3
CARDS_PER_COL = 3
CARDS_PER_PAGE = CARDS_PER_ROW * CARDS_PER_COL

# Cache directory
CACHE_DIR = Path(__file__).parent / "cache"

# Custom images directory (for user-provided clean scans)
CUSTOM_IMAGES_DIR = None  # Set via --image-dir

# Request headers
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}


def setup_cache():
    """Create cache directory if it doesn't exist."""
    CACHE_DIR.mkdir(exist_ok=True)


def find_local_image(identifier: str) -> Optional[Path]:
    """Look for a local image file matching the card identifier."""
    if not CUSTOM_IMAGES_DIR:
        return None
    
    img_dir = Path(CUSTOM_IMAGES_DIR)
    if not img_dir.exists():
        return None
    
    # Try various filename patterns
    card_id = identifier.upper()
    patterns = [
        f"{card_id}.*",
        f"{card_id.lower()}.*",
        f"{sanitize_filename(identifier)}.*",
    ]
    
    for pattern in patterns:
        matches = list(img_dir.glob(pattern))
        for match in matches:
            if match.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
                return match
    
    return None


def sanitize_filename(name: str) -> str:
    """Convert card name to safe filename."""
    return re.sub(r'[<>:"/\\|?*]', '_', name.lower().replace(' ', '_'))


def parse_card_entry(entry: str) -> Tuple[str, int]:
    """Parse a card entry like '4x OP01-001' into (identifier, quantity)."""
    entry = entry.strip()
    if not entry or entry.startswith('#'):
        return None, 0
    
    # Match patterns like "4x Card Name", "4 OP01-001", or just "Card Name"
    match = re.match(r'^(\d+)x?\s+(.+)$', entry, re.IGNORECASE)
    if match:
        quantity = int(match.group(1))
        identifier = match.group(2).strip()
    else:
        quantity = 1
        identifier = entry
    
    return identifier, quantity


def is_card_id(identifier: str) -> bool:
    """Check if identifier looks like a card ID (e.g., OP01-001, ST01-012)."""
    return bool(re.match(r'^[A-Z]{2,3}\d{2}-\d{3}[A-Z]?$', identifier.upper()))


def search_card_tcgplayer(identifier: str) -> Optional[dict]:
    """Search for card on TCGPlayer."""
    try:
        search_term = quote(f"One Piece {identifier}")
        search_url = f"https://www.tcgplayer.com/search/one-piece-card-game/product?q={search_term}"
        
        response = requests.get(search_url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # Look for product image
            img = soup.select_one('img.product-image__image, img[data-testid="product-image"]')
            if img:
                img_src = img.get('src', '')
                if img_src and 'tcgplayer' in img_src:
                    return {'name': identifier, 'image_url': img_src}
        return None
    except Exception:
        return None


def search_card_official(identifier: str) -> Optional[dict]:
    """Search on official One Piece card game site."""
    try:
        # The official site uses this card search structure
        card_id = identifier.upper() if is_card_id(identifier) else None
        
        if card_id:
            # Direct card page URL pattern
            search_url = f"https://en.onepiece-cardgame.com/cardlist/?series={card_id[:4]}"
        else:
            search_url = f"https://en.onepiece-cardgame.com/cardlist/?freewords={quote(identifier)}"
        
        response = requests.get(search_url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for card images on the page
            cards = soup.select('div.resultCol a img, .cardImg img, img[data-src*="card"]')
            for card in cards:
                img_src = card.get('data-src') or card.get('src', '')
                # Check if this matches our card ID
                if card_id and card_id.lower() in img_src.lower():
                    full_url = img_src if img_src.startswith('http') else f"https://en.onepiece-cardgame.com{img_src}"
                    return {'name': identifier, 'image_url': full_url}
                elif not card_id and img_src:
                    full_url = img_src if img_src.startswith('http') else f"https://en.onepiece-cardgame.com{img_src}"
                    return {'name': identifier, 'image_url': full_url}
        return None
    except Exception:
        return None


def search_card_onepiecetopdecks(identifier: str) -> Optional[dict]:
    """Search using One Piece Top Decks database."""
    try:
        # This site has a good card database
        if is_card_id(identifier):
            # Format: OP01-001 -> search directly
            search_url = f"https://onepiecetopdecks.com/card/{identifier.upper()}/"
        else:
            search_url = f"https://onepiecetopdecks.com/?s={quote(identifier)}&post_type=card"
        
        response = requests.get(search_url, headers=HEADERS, timeout=15, allow_redirects=True)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for card images
            img = soup.select_one('img.card-image, .card-img img, article img[src*="card"], .wp-post-image')
            if img:
                img_src = img.get('data-src') or img.get('src', '')
                if img_src and ('card' in img_src.lower() or 'op' in img_src.lower() or 'st' in img_src.lower()):
                    return {'name': identifier, 'image_url': img_src}
        return None
    except Exception:
        return None


def search_card_limitless(identifier: str) -> Optional[dict]:
    """Search using Limitless TCG."""
    try:
        search_url = f"https://onepiece.limitlesstcg.com/cards/{identifier.upper()}" if is_card_id(identifier) else f"https://onepiece.limitlesstcg.com/cards?q={quote(identifier)}"
        
        response = requests.get(search_url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for card image
            img = soup.select_one('img.card, .card-image img, img[src*="/cards/"]')
            if img:
                img_src = img.get('src', '')
                if img_src:
                    full_url = img_src if img_src.startswith('http') else f"https://onepiece.limitlesstcg.com{img_src}"
                    return {'name': identifier, 'image_url': full_url}
        return None
    except Exception:
        return None


def search_card_direct_cdn(identifier: str) -> Optional[dict]:
    """Try direct CDN URLs for clean card images (no watermarks)."""
    if not is_card_id(identifier):
        return None
    
    card_id = identifier.upper()
    # Extract set code (e.g., OP01 from OP01-001)
    set_code = card_id.split('-')[0] if '-' in card_id else card_id[:4]
    
    return {'name': identifier, 'card_id': card_id, 'set_code': set_code}


def search_card_limitless_cdn(identifier: str, lang: str = "EN") -> Optional[dict]:
    """Get card from Limitless TCG CDN - high quality scans."""
    if not is_card_id(identifier):
        return None
    
    card_id = identifier.upper()
    set_code = card_id.split('-')[0] if '-' in card_id else card_id[:4]
    
    # Limitless CDN pattern: /one-piece/OP01/OP01-001_EN.webp
    url = f"https://limitlesstcg.nyc3.digitaloceanspaces.com/one-piece/{set_code}/{card_id}_{lang}.webp"
    
    try:
        response = requests.head(url, headers=HEADERS, timeout=5)
        if response.status_code == 200:
            return {'name': identifier, 'image_url': url}
    except Exception:
        pass
    
    return None


def search_card_direct_cdn(identifier: str, lang: str = "EN") -> Optional[dict]:
    """Try direct CDN URLs for card images.
    Note: Official Bandai CDN images have SAMPLE watermarks."""
    if not is_card_id(identifier):
        return None
    
    card_id = identifier.upper()
    
    # These sources may have SAMPLE watermarks but are fallbacks
    if lang == "JP":
        cdn_urls = [
            f"https://www.onepiece-cardgame.com/images/cardlist/card/{card_id}.png",
        ]
    else:
        cdn_urls = [
            f"https://en.onepiece-cardgame.com/images/cardlist/card/{card_id}.png",
        ]
    
    for url in cdn_urls:
        try:
            response = requests.head(url, headers=HEADERS, timeout=5)
            if response.status_code == 200:
                return {'name': identifier, 'image_url': url}
        except Exception:
            continue
    
    return None


def search_card_opcgdb(identifier: str) -> Optional[dict]:
    """Search using opcgdb.com - community database with clean images."""
    try:
        card_id = identifier.upper() if is_card_id(identifier) else identifier
        search_url = f"https://opcgdb.com/cards/{card_id}"
        
        response = requests.get(search_url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for the main card image
            img = soup.select_one('img.card-image, .card img, img[alt*="card"], img[src*="/cards/"]')
            if img:
                img_src = img.get('src', '') or img.get('data-src', '')
                if img_src:
                    full_url = img_src if img_src.startswith('http') else f"https://opcgdb.com{img_src}"
                    return {'name': identifier, 'image_url': full_url}
        return None
    except Exception:
        return None


def fetch_card_data(identifier: str, verbose: bool = False, lang: str = "EN") -> Optional[dict]:
    """Fetch card data from available sources.
    
    Source priority:
    1. Local images (user-provided clean scans) - via --image-dir
    2. Limitless CDN - actual card scans
    3. Other community sources
    4. Official CDN (has SAMPLE watermark)
    """
    # Check for local image first
    local_path = find_local_image(identifier)
    if local_path:
        if verbose:
            print(f"    Source: Local image ({local_path.name})")
        return {'name': identifier, 'local_path': str(local_path), 'source': 'Local'}
    
    # Try Limitless CDN - these are actual card scans
    card = search_card_limitless_cdn(identifier, lang)
    if card and card.get('image_url'):
        card['source'] = "Limitless CDN"
        if verbose:
            print(f"    Source: Limitless CDN ({lang})")
        return card
    
    # Fallback sources (may have watermarks)
    fallback_sources = [
        ("OPCGDB", lambda x: search_card_opcgdb(x)),
        ("Limitless Site", lambda x: search_card_limitless(x)),
        ("Top Decks", lambda x: search_card_onepiecetopdecks(x)),
        ("Official Site", lambda x: search_card_official(x)),
        ("Official CDN", lambda x: search_card_direct_cdn(x, lang)),
        ("TCGPlayer", lambda x: search_card_tcgplayer(x)),
    ]
    
    for source_name, search_func in fallback_sources:
        card = search_func(identifier)
        if card and card.get('image_url'):
            card['source'] = source_name
            if verbose:
                print(f"    Source: {source_name} (may have SAMPLE watermark)")
            return card
    
    print(f"  ⚠ Card not found: {identifier}")
    return None


def get_image_url(card_data: dict) -> Optional[str]:
    """Extract image URL from card data."""
    # Check various possible fields
    for field in ['image_url', 'imageUrl', 'image', 'img', 'picture']:
        if field in card_data and card_data[field]:
            url = card_data[field]
            # Ensure it's a full URL
            if not url.startswith('http'):
                url = f"https:{url}" if url.startswith('//') else url
            return url
    return None


def download_image(url: str, card_name: str, use_cache: bool = True) -> Optional[Path]:
    """Download card image and return local path."""
    filename = sanitize_filename(card_name) + ".png"
    cache_path = CACHE_DIR / filename
    
    # Check cache first
    if use_cache and cache_path.exists():
        return cache_path
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        
        with open(cache_path, 'wb') as f:
            f.write(response.content)
        
        return cache_path
    except requests.exceptions.RequestException as e:
        print(f"  ⚠ Failed to download image for '{card_name}': {e}")
        return None


def resize_card_image(image_path: Path, dpi: int = DEFAULT_DPI) -> Image.Image:
    """Resize card image to standard TCG dimensions at specified DPI."""
    target_width = int(CARD_WIDTH_INCHES * dpi)
    target_height = int(CARD_HEIGHT_INCHES * dpi)
    
    img = Image.open(image_path)
    
    # Convert to RGB if necessary (for PNG with transparency)
    if img.mode in ('RGBA', 'P'):
        background = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')
    
    # Resize maintaining aspect ratio, then crop/pad to exact size
    img_ratio = img.width / img.height
    target_ratio = target_width / target_height
    
    if img_ratio > target_ratio:
        # Image is wider than target
        new_height = target_height
        new_width = int(new_height * img_ratio)
    else:
        # Image is taller than target
        new_width = target_width
        new_height = int(new_width / img_ratio)
    
    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    # Center crop to exact dimensions
    left = (new_width - target_width) // 2
    top = (new_height - target_height) // 2
    img = img.crop((left, top, left + target_width, top + target_height))
    
    return img


def create_pdf(cards: List[Tuple[str, Image.Image]], output_path: str, dpi: int = DEFAULT_DPI):
    """Create PDF with cards arranged in a grid."""
    page_width, page_height = LETTER
    
    # Calculate card dimensions in points (72 points per inch)
    card_width_pts = CARD_WIDTH_INCHES * 72
    card_height_pts = CARD_HEIGHT_INCHES * 72
    
    # Calculate margins to center the grid
    grid_width = CARDS_PER_ROW * card_width_pts
    grid_height = CARDS_PER_COL * card_height_pts
    margin_x = (page_width - grid_width) / 2
    margin_y = (page_height - grid_height) / 2
    
    c = canvas.Canvas(output_path, pagesize=LETTER)
    
    card_index = 0
    total_cards = len(cards)
    
    while card_index < total_cards:
        # Draw cards for this page
        for row in range(CARDS_PER_COL):
            for col in range(CARDS_PER_ROW):
                if card_index >= total_cards:
                    break
                
                card_name, card_img = cards[card_index]
                
                # Calculate position (bottom-left origin in PDF)
                x = margin_x + col * card_width_pts
                y = page_height - margin_y - (row + 1) * card_height_pts
                
                # Save image temporarily for PDF embedding
                temp_path = CACHE_DIR / f"temp_{card_index}.jpg"
                card_img.save(temp_path, "JPEG", quality=95)
                
                c.drawImage(str(temp_path), x, y, 
                           width=card_width_pts, height=card_height_pts)
                
                # Clean up temp file
                temp_path.unlink()
                
                card_index += 1
        
        # Add new page if more cards remain
        if card_index < total_cards:
            c.showPage()
    
    c.save()


def load_decklist(filepath: str) -> List[Tuple[str, int]]:
    """Load card list from file."""
    cards = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                identifier, qty = parse_card_entry(line)
                if identifier:
                    cards.append((identifier, qty))
    except FileNotFoundError:
        print(f"Error: File not found: {filepath}")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)
    
    return cards


def main():
    parser = argparse.ArgumentParser(
        description="Fetch One Piece TCG card images and create printable proxy sheets."
    )
    parser.add_argument(
        'cards', 
        nargs='*', 
        help="Card names or IDs (use quotes for multi-word names)"
    )
    parser.add_argument(
        '-f', '--file',
        help="Read card names/IDs from a text file"
    )
    parser.add_argument(
        '-o', '--output',
        default='proxies.pdf',
        help="Output PDF filename (default: proxies.pdf)"
    )
    parser.add_argument(
        '--dpi',
        type=int,
        default=DEFAULT_DPI,
        help=f"Print DPI (default: {DEFAULT_DPI})"
    )
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help="Don't use cached images"
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help="Show detailed source information"
    )
    parser.add_argument(
        '--jp', '--japanese',
        action='store_true',
        dest='japanese',
        help="Use Japanese card images (may have cleaner scans)"
    )
    parser.add_argument(
        '--image-dir',
        help="Directory containing your own card images (for clean scans without SAMPLE watermark). Images should be named by card ID, e.g., OP01-001.png"
    )
    
    args = parser.parse_args()
    
    # Collect card entries
    card_entries = []
    
    if args.file:
        card_entries.extend(load_decklist(args.file))
    
    for card in args.cards:
        identifier, qty = parse_card_entry(card)
        if identifier:
            card_entries.append((identifier, qty))
    
    if not card_entries:
        print("No cards specified. Use --help for usage information.")
        sys.exit(1)
    
    # Setup
    setup_cache()
    use_cache = not args.no_cache
    lang = "JP" if args.japanese else "EN"
    
    # Set custom images directory
    global CUSTOM_IMAGES_DIR
    if args.image_dir:
        CUSTOM_IMAGES_DIR = args.image_dir
        print(f"  Using custom images from: {args.image_dir}")
    
    # Process cards
    print(f"Processing {sum(qty for _, qty in card_entries)} cards...")
    if args.japanese:
        print("  Using Japanese card images")
    processed_cards = []
    
    for identifier, quantity in card_entries:
        print(f"  Fetching: {identifier} (x{quantity})")
        
        # Rate limiting
        time.sleep(0.2)
        
        card_data = fetch_card_data(identifier, verbose=args.verbose, lang=lang)
        if not card_data:
            continue
        
        actual_name = card_data.get('name', identifier)
        
        # Check if we have a local image
        if 'local_path' in card_data:
            image_path = Path(card_data['local_path'])
        else:
            image_url = get_image_url(card_data)
            
            if not image_url:
                print(f"  ⚠ No image available for: {actual_name}")
                continue
            
            image_path = download_image(image_url, actual_name, use_cache)
            if not image_path:
                continue
        
        # Resize and add to list (repeated for quantity)
        resized_img = resize_card_image(image_path, args.dpi)
        for _ in range(quantity):
            processed_cards.append((actual_name, resized_img))
        
        print(f"  ✓ {actual_name}")
    
    if not processed_cards:
        print("No cards were successfully processed.")
        sys.exit(1)
    
    # Generate PDF
    print(f"\nGenerating PDF: {args.output}")
    create_pdf(processed_cards, args.output, args.dpi)
    
    pages = (len(processed_cards) + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE
    print(f"✓ Created {args.output} with {len(processed_cards)} cards on {pages} page(s)")
    print(f"  Print at 100% scale, no margins, for correct card size.")


if __name__ == "__main__":
    main()
