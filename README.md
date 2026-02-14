# One Piece TCG Proxy Printer

A Python tool to fetch One Piece Trading Card Game images and format them for printing proxies.

## Features

- Fetch card images from multiple sources (Limitless TCG, community databases)
- Resize cards to standard TCG size (2.5" x 3.5")
- Generate print-ready PDF sheets (3x3 grid per page)
- Support for card lists via text file input
- Search by card name or card ID (e.g., OP01-001)
- **Use your own card scans** for clean images without watermarks
- Automatic image caching to avoid re-downloading

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage

```bash
# Single card by ID
python op_proxy.py "OP01-001"

# Multiple cards with quantities
python op_proxy.py "4x OP01-001" "2x ST01-001"

# From a decklist file
python op_proxy.py --file decklist.txt

# Use Japanese card images
python op_proxy.py "OP01-001" --jp
```

### Using Your Own Clean Images

Official card images have "SAMPLE" watermarks. For clean proxies, provide your own scans:

```bash
# Use images from a local folder
python op_proxy.py "OP01-001" --image-dir ./my_scans/

# Images should be named by card ID: OP01-001.png, OP01-002.jpg, etc.
```

### All Options

```bash
--file, -f       Read card names/IDs from a text file
--output, -o     Output PDF filename (default: proxies.pdf)
--dpi            Print DPI (default: 300)
--no-cache       Don't use cached images
--verbose, -v    Show which source each card image comes from
--jp             Use Japanese card images
--image-dir      Directory with your own card image scans
```

### Decklist Format

Create a text file with card IDs, optionally with quantities:

```
4x OP01-001
2x OP02-001
1x ST01-012
OP03-001
```

## About SAMPLE Watermarks

Bandai adds "SAMPLE" watermarks to official card images to prevent counterfeiting. To get clean proxies, you can:

1. **Use your own scans** - Scan real cards and use `--image-dir`
2. **Find community scans** - Some communities share clean scans
3. **Use Japanese cards** - Try `--jp` flag (text will be in Japanese)

## Output

The tool generates a PDF with cards arranged in a 3x3 grid, sized for standard letter paper (8.5" x 11"). Print at 100% scale and cut along the grid lines for proper card dimensions.

## Legal Notice

This tool is for personal, non-commercial use only. One Piece is a trademark of Shueisha/Toei Animation. One Piece Card Game is produced by Bandai. Card images are for personal reference only. Do not sell proxies made with this tool.

## License

MIT License - See LICENSE file
