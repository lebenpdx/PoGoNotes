import json
import re
from html import escape
from pathlib import Path

from bs4 import BeautifulSoup
import requests

# Edit these settings to change the HTML filters and entry layout.
HTML_RAID_LEVELS = {5}
HTML_EXCLUDED_SECTIONS = {
    'exploring tasks',
    'catching tasks',
    'buddy tasks',
    'buddy & friendship tasks',
    'team rocket tasks',
    'team go rocket tasks',
    'battling tasks',
    'throwing tasks',
    'training tasks',
}
RAID_LINE = '<li><strong>{name}</strong> &mdash; Max CP: {max_cp} | Boosted: {max_boosted_cp}</li>'
RESEARCH_LINE = '<li><strong>{name}</strong> &mdash; {task} | Max CP: {max_cp}</li>'
HTML_STYLE = '''
body { font-family: system-ui, sans-serif; max-width: 960px; margin: 0 auto; padding: 24px; color: #202124; background: #fafafa; }
h1, h2, h3 { line-height: 1.3; }
h2 { margin-top: 28px; border-bottom: 2px solid #ddd; padding-bottom: 8px; }
ul { list-style: none; padding: 0; overflow-x: auto; }
li { padding: 10px 0; border-bottom: 1px solid #ddd; white-space: nowrap; }
'''

def scrape_research(url):
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')
    elements = soup.select(':has(> .cp-values)')
    data = []
    for element in elements:
        task_list = element.find_parent(class_='task-list')
        heading = task_list.find_previous_sibling('h2') if task_list else element.find_previous('h2')
        task_item = element.find_parent(class_='task-item')
        task_text = task_item.select_one('.task-text') if task_item else None
        cp_values = element.find(class_='cp-values', recursive=False)
        image = element.select_one('.reward-image')
        data.append({
            'name': element.select_one('.reward-label').get_text(' ', strip=True),
            'section': heading.get_text(' ', strip=True) if heading else None,
            'task': task_text.get_text(' ', strip=True) if task_text else None,
            'min_cp': int(cp_values.select_one('.min-cp').get_text(' ', strip=True).removeprefix('Min CP').strip()),
            'max_cp': int(cp_values.select_one('.max-cp').get_text(' ', strip=True).removeprefix('Max CP').strip()),
            'can_be_shiny': element.select_one('.shiny-badge') is not None,
            'image_url': image.get('src') if image else None,
        })
    return data

def scrape_raids(url):
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')
    elements = soup.select('.card:has(> .cp-range)')
    if not elements:
        raise ValueError('No raid cards found; check the URL or page structure.')
    data = []
    for element in elements:
        tier = element.find_parent(class_='tier')
        raid_level = tier.select_one('[data-tier]')['data-tier']
        image = element.select_one('.boss-img img')
        cp_values = element.find(class_='cp-range', recursive=False)
        cp_range = re.search(r'(\d[\d,]*)\s*[-\u2013]\s*(\d[\d,]*)', cp_values.get_text(' ', strip=True))
        if cp_range is None:
            raise ValueError(f'Unrecognized raid CP range: {cp_values.get_text(" ", strip=True)}')
        boosted_values = element.select_one('.boosted-cp')
        boosted_text = boosted_values.get_text(' ', strip=True) if boosted_values else ''
        boosted_range = re.search(r'(\d[\d,]*)\s*[-\u2013]\s*(\d[\d,]*)', boosted_text)
        if boosted_range is None:
            raise ValueError(f'Missing or unrecognized boosted raid CP range: {boosted_text}')
        data.append({
            'name': element.select_one('.name').get_text(' ', strip=True),
            'max_cp': int(cp_range.group(2).replace(',', '')),
            'max_boosted_cp': int(boosted_range.group(2).replace(',', '')),
            'raid_level': int(raid_level) if raid_level.isdigit() else raid_level,
            'image_url': image.get('src') if image else None,
        })
    return data

def clean(data):
    """Return unique records, comparing all fields and keeping the first occurrence."""
    records = {}
    for record in data:
        key = json.dumps(record, sort_keys=True)
        records.setdefault(key, record)
    return list(records.values())


def save_research_sections(data):
    """Write one JSON file per section and return the output paths."""
    output_dir = Path(__file__).with_name('json')
    output_dir.mkdir(exist_ok=True)
    sections = {}
    for record in data:
        section = record.get('section') or 'Uncategorized'
        sections.setdefault(section, []).append(record)

    paths = []
    used_names = {'raids.json'}
    for section, records in sections.items():
        stem = re.sub(r'[^\w]+', '_', section.lower()).strip('_') or 'section'
        filename = f'{stem}.json'
        suffix = 2
        while filename in used_names:
            filename = f'{stem}_{suffix}.json'
            suffix += 1
        used_names.add(filename)
        output_path = output_dir / filename
        output_path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        paths.append(output_path)
    return paths


def export_html(json_dir=None, output_path=None):
    """Read all JSON files, filter entries, and overwrite the HTML notes."""
    json_dir = Path(json_dir) if json_dir is not None else Path(__file__).with_name('json')
    output_path = Path(output_path) if output_path is not None else Path(__file__).with_name('notes.html')
    raids = []
    research = {}
    for path in sorted(json_dir.glob('*.json')):
        for entry in json.loads(path.read_text(encoding='utf-8')):
            if path.name == 'raids.json':
                if entry['raid_level'] in HTML_RAID_LEVELS:
                    raids.append(entry)
            elif entry['section'].casefold() not in HTML_EXCLUDED_SECTIONS:
                research.setdefault(entry['section'], []).append(entry)

    def format_line(template, entry):
        # Keep each entry on one line, even when source text contains newlines.
        fields = {
            key: escape(' '.join(value.split())) if isinstance(value, str) else value
            for key, value in entry.items()
        }
        return template.format_map(fields)

    lines = [
        '<!DOCTYPE html>', '<html lang="en">', '<head>',
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<title>PoGo Notes</title>', f'<style>{HTML_STYLE}</style>',
        '</head>', '<body>', '<main>', '<h1>PoGo Notes</h1>',
        '<section>', '<h2>Raids</h2>', '<ul>',
    ]
    lines.extend(format_line(RAID_LINE, entry) for entry in raids)
    lines.extend(['</ul>', '</section>', '<section>', '<h2>Research</h2>'])
    for section, entries in research.items():
        lines.extend([f"<h3>{escape(' '.join(section.split()))}</h3>", '<ul>'])
        lines.extend(format_line(RESEARCH_LINE, entry) for entry in entries)
        lines.append('</ul>')
    lines.extend(['</section>', '</main>', '</body>', '</html>'])
    output_path.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
    return output_path


if __name__ == "__main__":
    data = clean(scrape_research("https://leekduck.com/research/"))
    raid_data = clean(scrape_raids("https://leekduck.com/raid-bosses/"))
    output_dir = Path(__file__).with_name('json')
    output_dir.mkdir(exist_ok=True)
    raid_output_path = output_dir / 'raids.json'
    raid_output_path.write_text(json.dumps(raid_data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Saved {len(raid_data)} raids to {raid_output_path}')
    research_paths = save_research_sections(data)
    print(f'Saved {len(data)} research results across {len(research_paths)} files in json')
    html_path = export_html()
    print(f'Saved HTML notes to {html_path}')
