import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
import requests

# Edit these settings to change the Markdown filters and entry layout.
MARKDOWN_RAID_LEVELS = {5}
MARKDOWN_EXCLUDED_SECTIONS = {
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
RAID_LINE = '- **{name}** — Max CP: {max_cp} | Boosted: {max_boosted_cp}'
RESEARCH_LINE = '- **{name}** — {task} | Max CP: {max_cp}'

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


def export_markdown(json_dir=None, output_path=None):
    """Read all JSON files, filter entries, and overwrite the Markdown notes."""
    json_dir = Path(json_dir) if json_dir is not None else Path(__file__).with_name('json')
    output_path = Path(output_path) if output_path is not None else Path(__file__).with_name('notes.md')
    raids = []
    research = {}
    for path in sorted(json_dir.glob('*.json')):
        for entry in json.loads(path.read_text(encoding='utf-8')):
            if path.name == 'raids.json':
                if entry['raid_level'] in MARKDOWN_RAID_LEVELS:
                    raids.append(entry)
            elif entry['section'].casefold() not in MARKDOWN_EXCLUDED_SECTIONS:
                research.setdefault(entry['section'], []).append(entry)

    def format_line(template, entry):
        # Keep each entry on one line, even when source text contains newlines.
        fields = {
            key: ' '.join(value.split()) if isinstance(value, str) else value
            for key, value in entry.items()
        }
        return template.format_map(fields)

    lines = ['# PoGo Notes', '', '## Raids', '']
    lines.extend(format_line(RAID_LINE, entry) for entry in raids)
    lines.extend(['', '## Research', ''])
    for section, entries in research.items():
        lines.extend([f"### {' '.join(section.split())}", ''])
        lines.extend(format_line(RESEARCH_LINE, entry) for entry in entries)
        lines.append('')
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
    markdown_path = export_markdown()
    print(f'Saved Markdown notes to {markdown_path}')
