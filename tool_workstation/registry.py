"""
Tool Workstation registry — 120 client-side utilities (image, PDF, productivity).
Single source for routes, SEO, and front-end JSON bootstrap.
"""
from __future__ import annotations

import json
from copy import deepcopy


def _seo(name: str, category: str, extra: str = '') -> dict:
    intro = (
        f'{name} is a privacy-first utility that runs entirely in your browser within Fleet Management. '
        f'No files are uploaded to a server; processing happens on your device using modern Web APIs. '
        f'{extra}'
    ).strip()
    return {
        'title': f'{name} | Fleet Tool Workstation',
        'h1': name,
        'intro': intro,
        'steps': [
            'Open this tool from the Tool Workstation dashboard or search.',
            'Provide input (file, text, or paste) in the workspace panel.',
            'Adjust options using the controls provided for this utility.',
            'Download or copy the result — your data never leaves this browser session.',
        ],
        'faq': [
            {
                'q': 'Are my files uploaded to the cloud?',
                'a': 'No. All processing is client-side in your browser. Fleet servers only deliver the application code.',
            },
            {
                'q': 'Which browsers are supported?',
                'a': 'Recent Chrome, Edge, Firefox, and Safari on desktop and mobile are recommended for best results.',
            },
            {
                'q': f'Is {name} free to use?',
                'a': f'Yes. This {category} tool is included for authorized Fleet administration users.',
            },
        ],
    }


def _tool(num: int, slug: str, name: str, category: str, engine: str, method: str, icon: str, **kw) -> dict:
    t = {
        'id': num,
        'slug': slug,
        'name': name,
        'category': category,
        'engine': engine,
        'method': method,
        'icon': icon,
        'keywords': kw.get('keywords', [name.lower(), slug.replace('-', ' ')]),
    }
    t.update(_seo(name, category.replace('-', ' '), kw.get('seo_extra', '')))
    return t


_IMAGE = [
    (1, 'jpg-to-png', 'JPG to PNG Converter', 'image-convert', 'fa-file-image'),
    (2, 'png-to-jpg', 'PNG to JPG Converter', 'image-convert', 'fa-file-image'),
    (3, 'webp-converter', 'WebP Converter', 'image-convert', 'fa-file-image'),
    (4, 'image-compressor', 'Image Compressor', 'image-compress', 'fa-compress'),
    (5, 'svg-to-png', 'SVG to PNG Rasterizer', 'svg-raster', 'fa-vector-square'),
    (6, 'ico-generator', 'ICO Favicon Generator', 'ico-gen', 'fa-star'),
    (7, 'gif-frames', 'GIF to Frames Extractor', 'gif-frames', 'fa-film'),
    (8, 'base64-to-image', 'Base64 to Image Decoder', 'base64-decode', 'fa-code'),
    (9, 'image-to-base64', 'Image to Base64 Encoder', 'base64-encode', 'fa-code'),
    (10, 'aspect-cropper', 'Aspect-Ratio Image Cropper', 'aspect-crop', 'fa-crop'),
    (11, 'image-resizer', 'Pixel-Perfect Resizer', 'resize', 'fa-expand'),
    (12, 'image-rotator', 'Image Rotator', 'rotate', 'fa-rotate-right'),
    (13, 'image-flipper', 'Image Flipper', 'flip', 'fa-arrows-left-right'),
    (14, 'gaussian-blur', 'Gaussian Blur Tool', 'blur', 'fa-droplet'),
    (15, 'image-sharpener', 'Image Sharpener', 'sharpen', 'fa-wand-magic-sparkles'),
    (16, 'brightness-contrast', 'Brightness & Contrast', 'brightness-contrast', 'fa-sun'),
    (17, 'hue-saturation', 'Hue & Saturation', 'hue-saturation', 'fa-palette'),
    (18, 'palette-extractor', 'Dominant Color Palette', 'palette', 'fa-swatchbook'),
    (19, 'watermark-overlay', 'Watermark Overlay', 'watermark', 'fa-copyright'),
    (20, 'grayscale-filter', 'Grayscale Filter', 'grayscale', 'fa-circle-half-stroke'),
    (21, 'sepia-tone', 'Sepia Tone', 'sepia', 'fa-image'),
    (22, 'color-invert', 'Color Inversion', 'invert', 'fa-adjust'),
    (23, 'retro-pixelator', '8-Bit Pixelator', 'pixelate', 'fa-th'),
    (24, 'film-grade', 'Vintage Film Grading', 'film-grade', 'fa-clapperboard'),
    (25, 'dither-pattern', 'Dithered Dot Pattern', 'dither', 'fa-braille'),
    (26, 'vignette', 'Vignette Shadow', 'vignette', 'fa-circle-dot'),
    (27, 'ascii-art', 'Pixel to ASCII Art', 'ascii-art', 'fa-terminal'),
    (28, 'exif-viewer', 'EXIF Metadata Viewer', 'exif-view', 'fa-circle-info'),
    (29, 'exif-stripper', 'EXIF Privacy Stripper', 'exif-strip', 'fa-shield'),
    (30, 'meme-generator', 'Meme Generator', 'meme', 'fa-face-laugh'),
    (31, 'grid-splitter', 'Social Media Grid Splitter', 'grid-split', 'fa-table-cells'),
    (32, 'photo-collage', 'Photo Collage Maker', 'collage', 'fa-table-cells-large'),
    (33, 'round-corners', 'Round Corners Masker', 'round-corners', 'fa-square'),
    (34, 'placeholder-generator', 'Color Placeholder Mock', 'placeholder', 'fa-square-full'),
    (35, 'chroma-key', 'Chroma Key Background Remover', 'chroma-key', 'fa-scissors'),
    (36, 'sprite-sheet', 'Sprite Sheet Generator', 'sprite-sheet', 'fa-layer-group'),
    (37, 'film-grain', 'Film Grain Generator', 'film-grain', 'fa-snowflake'),
    (38, 'barcode-qr', 'Barcode & QR Generator', 'barcode-qr', 'fa-qrcode'),
    (39, 'color-picker', 'Loupe Color Picker', 'color-picker', 'fa-eyedropper'),
    (40, 'before-after', 'Before/After Slider', 'before-after', 'fa-sliders'),
]

_PDF = [
    (41, 'pdf-encrypt', 'PDF Password Encrypter', 'pdf-encrypt', 'fa-lock'),
    (42, 'pdf-decrypt', 'PDF Password Stripper', 'pdf-decrypt', 'fa-lock-open'),
    (43, 'pdf-compress', 'PDF Compressor', 'pdf-compress', 'fa-compress'),
    (44, 'pdf-metadata', 'PDF Metadata Editor', 'pdf-metadata', 'fa-tag'),
    (45, 'pdf-watermark', 'PDF Watermark Stamp', 'pdf-watermark', 'fa-droplet'),
    (46, 'pdf-page-numbers', 'PDF Page Numberer', 'pdf-page-numbers', 'fa-list-ol'),
    (47, 'pdf-merge', 'PDF Merger', 'pdf-merge', 'fa-object-group'),
    (48, 'pdf-split', 'PDF Splitter', 'pdf-split', 'fa-scissors'),
    (49, 'pdf-delete-pages', 'Delete PDF Pages', 'pdf-delete-pages', 'fa-trash'),
    (50, 'pdf-rotate', 'PDF Page Rotator', 'pdf-rotate', 'fa-rotate-right'),
    (51, 'pdf-reorder', 'PDF Page Reorder', 'pdf-reorder', 'fa-arrow-down-up-across-line'),
    (52, 'pdf-text-extract', 'PDF Text Extractor', 'pdf-text-extract', 'fa-file-lines'),
    (53, 'pdf-to-images-zip', 'PDF to Images ZIP', 'pdf-to-images', 'fa-images'),
    (54, 'pdf-crop', 'PDF Page Crop', 'pdf-crop', 'fa-crop'),
    (55, 'pdf-blank-page', 'Insert Blank PDF Page', 'pdf-blank', 'fa-file-circle-plus'),
    (56, 'jpg-to-pdf', 'JPG to PDF', 'images-to-pdf', 'fa-file-pdf'),
    (57, 'png-to-pdf', 'PNG to PDF', 'images-to-pdf', 'fa-file-pdf'),
    (58, 'text-to-pdf', 'Text to PDF', 'text-to-pdf', 'fa-file-pdf'),
    (59, 'html-to-pdf', 'HTML to PDF', 'html-to-pdf', 'fa-file-pdf'),
    (60, 'markdown-to-pdf', 'Markdown to PDF', 'markdown-to-pdf', 'fa-file-pdf'),
    (61, 'docx-to-pdf', 'DOCX to PDF', 'docx-to-pdf', 'fa-file-word'),
    (62, 'csv-to-pdf', 'CSV to PDF Table', 'csv-to-pdf', 'fa-file-csv'),
    (63, 'epub-to-pdf', 'EPUB to PDF', 'epub-to-pdf', 'fa-book'),
    (64, 'pdf-to-jpg', 'PDF to JPG', 'pdf-to-jpg', 'fa-file-image'),
    (65, 'pdf-to-png', 'PDF to PNG', 'pdf-to-png', 'fa-file-image'),
    (66, 'pdf-to-webp', 'PDF to WebP', 'pdf-to-webp', 'fa-file-image'),
    (67, 'pdf-to-text', 'PDF to Plain Text', 'pdf-to-text', 'fa-file-lines'),
    (68, 'pdf-to-docx', 'PDF to Word Layout', 'pdf-to-docx', 'fa-file-word'),
    (69, 'pdf-to-xlsx', 'PDF to Excel Grid', 'pdf-to-xlsx', 'fa-file-excel'),
    (70, 'pdf-to-html', 'PDF to HTML Mock', 'pdf-to-html', 'fa-code'),
    (71, 'pdf-images-zip', 'PDF Images ZIP Pack', 'pdf-to-images', 'fa-file-zipper'),
    (72, 'pdf-signature', 'Signature Stamper', 'pdf-signature', 'fa-signature'),
    (73, 'pdf-form-reader', 'Fillable PDF Reader', 'pdf-form-read', 'fa-rectangle-list'),
    (74, 'pdf-flatten', 'Flatten PDF Forms', 'pdf-flatten', 'fa-layer-group'),
    (75, 'pdf-viewer', 'PDF Viewer', 'pdf-viewer', 'fa-eye'),
    (76, 'pdf-annotate', 'PDF Highlighter', 'pdf-annotate', 'fa-highlighter'),
    (77, 'pdf-text-place', 'PDF Text Placer', 'pdf-text-place', 'fa-font'),
    (78, 'invoice-pdf', 'Invoice PDF Generator', 'invoice-pdf', 'fa-file-invoice'),
    (79, 'resume-pdf', 'Resume PDF Builder', 'resume-pdf', 'fa-id-card'),
    (80, 'certificate-batch', 'Certificate Batch PDF', 'certificate-batch', 'fa-award'),
]

_UTILITY = [
    (81, 'json-validator', 'JSON Validator', 'json-validate', 'fa-brackets-curly'),
    (82, 'url-encoder', 'URL Encoder', 'url-encode', 'fa-link'),
    (83, 'url-decoder', 'URL Decoder', 'url-decode', 'fa-link'),
    (84, 'md5-hash', 'MD5 Hash Generator', 'md5', 'fa-hashtag'),
    (85, 'sha256-hash', 'SHA-256 Hash Generator', 'sha256', 'fa-hashtag'),
    (86, 'jwt-decoder', 'JWT Decoder', 'jwt-decode', 'fa-key'),
    (87, 'regex-tester', 'Regex Tester', 'regex-test', 'fa-code'),
    (88, 'lorem-ipsum', 'Lorem Ipsum Generator', 'lorem', 'fa-paragraph'),
    (89, 'case-converter', 'String Case Converter', 'case-convert', 'fa-text-height'),
    (90, 'diff-checker', 'Text Diff Checker', 'diff', 'fa-code-compare'),
    (91, 'markdown-preview', 'Markdown Preview', 'markdown-preview', 'fa-markdown'),
    (92, 'unix-timestamp', 'Unix Timestamp Converter', 'timestamp', 'fa-clock'),
    (93, 'uuid-generator', 'UUID Generator', 'uuid', 'fa-fingerprint'),
    (94, 'password-generator', 'Password Generator', 'password-gen', 'fa-key'),
    (95, 'css-box-shadow', 'CSS Box-Shadow Generator', 'box-shadow', 'fa-square'),
    (96, 'color-converter', 'Color Code Converter', 'color-convert', 'fa-palette'),
    (97, 'xml-to-json', 'XML to JSON', 'xml-to-json', 'fa-right-left'),
    (98, 'json-to-xml', 'JSON to XML', 'json-to-xml', 'fa-right-left'),
    (99, 'html-encode', 'HTML Entity Encoder', 'html-encode', 'fa-code'),
    (100, 'html-decode', 'HTML Entity Decoder', 'html-decode', 'fa-code'),
    (101, 'base64-encode-text', 'Base64 Text Encoder', 'b64-text-encode', 'fa-code'),
    (102, 'base64-decode-text', 'Base64 Text Decoder', 'b64-text-decode', 'fa-code'),
    (103, 'word-counter', 'Word & Character Counter', 'word-count', 'fa-calculator'),
    (104, 'dedupe-lines', 'Remove Duplicate Lines', 'dedupe-lines', 'fa-list'),
    (105, 'sort-lines', 'Sort Lines', 'sort-lines', 'fa-sort-alpha-down'),
    (106, 'random-number', 'Random Number Generator', 'random-number', 'fa-dice'),
    (107, 'percentage-calc', 'Percentage Calculator', 'percentage', 'fa-percent'),
    (108, 'bmi-calculator', 'BMI Calculator', 'bmi', 'fa-weight-scale'),
    (109, 'unit-converter', 'Length Unit Converter', 'unit-length', 'fa-ruler'),
    (110, 'luhn-validator', 'Credit Card Luhn Check', 'luhn', 'fa-credit-card'),
    (111, 'iban-validator', 'IBAN Validator', 'iban', 'fa-building-columns'),
    (112, 'cron-explainer', 'Cron Expression Helper', 'cron', 'fa-calendar'),
    (113, 'hash-compare', 'Hash Compare', 'hash-compare', 'fa-equals'),
    (114, 'hmac-generator', 'HMAC Generator', 'hmac', 'fa-lock'),
    (115, 'binary-to-text', 'Binary to Text', 'binary-decode', 'fa-0'),
    (116, 'text-to-binary', 'Text to Binary', 'binary-encode', 'fa-1'),
    (117, 'hex-to-text', 'Hex to Text', 'hex-decode', 'fa-hashtag'),
    (118, 'text-to-hex', 'Text to Hex', 'hex-encode', 'fa-hashtag'),
    (119, 'slug-generator', 'URL Slug Generator', 'slug', 'fa-link'),
    (120, 'whitespace-normalizer', 'Whitespace Normalizer', 'whitespace', 'fa-align-left'),
]


def _build_tools():
    out = []
    for num, slug, name, method, icon in _IMAGE:
        out.append(_tool(num, slug, name, 'image', 'image', method, icon))
    for num, slug, name, method, icon in _PDF:
        out.append(_tool(num, slug, name, 'pdf', 'pdf', method, icon))
    for num, slug, name, method, icon in _UTILITY:
        out.append(_tool(num, slug, name, 'utility', 'text', method, icon))
    return out


TOOLS: list[dict] = _build_tools()
TOOLS_BY_SLUG: dict[str, dict] = {t['slug']: t for t in TOOLS}
CATEGORY_LABELS = {
    'image': 'Image Processing Studio',
    'pdf': 'Document & PDF Engine',
    'utility': 'Productivity & Developer Utilities',
}


def get_tool(slug: str) -> dict | None:
    return TOOLS_BY_SLUG.get(slug)


def tools_for_category(category: str) -> list[dict]:
    return [t for t in TOOLS if t['category'] == category]


def tools_json() -> str:
    """Minimal payload for client search/grid."""
    payload = [
        {
            'id': t['id'],
            'slug': t['slug'],
            'name': t['name'],
            'category': t['category'],
            'categoryLabel': CATEGORY_LABELS[t['category']],
            'icon': t['icon'],
            'keywords': t['keywords'],
        }
        for t in TOOLS
    ]
    return json.dumps(payload, ensure_ascii=False)


def tool_public(t: dict) -> dict:
    """Full tool for template + JS bootstrap."""
    return deepcopy(t)
