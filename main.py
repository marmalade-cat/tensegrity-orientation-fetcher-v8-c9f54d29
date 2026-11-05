#!/usr/bin/env python3
"""
Prototype: search URLs for CSV/JSON supplement files, download, validate, normalize to a standard JSON time-series schema, and write provenance.
Uses only Python standard library.
"""
import sys
import urllib.request
import urllib.parse
import urllib.error
import io
import csv
import json
import re
from datetime import datetime

# Standard JSON schema per this prototype:
# {"source_url":..., "retrieved_at":..., "modules": {module_id: [{"t":..., "orientation": [x,y,z,w] or value}, ...]}}

HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)

provenance = []
normalized_count = 0

def fetch_url(url):
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            content = r.read()
            info = r.info()
            return content, info.get_content_type(), None
    except urllib.error.HTTPError as e:
        return None, None, f'HTTP {e.code} {e.reason}'
    except Exception as e:
        return None, None, str(e)

def find_links_from_html(base_url, html_bytes):
    try:
        text = html_bytes.decode('utf-8', errors='ignore')
    except Exception:
        text = str(html_bytes)
    found = []
    for m in HREF_RE.finditer(text):
        href = m.group(1)
        absu = urllib.parse.urljoin(base_url, href)
        # heuristic: likely useful if ends with csv or json or contains 'supplement' or 'SI'
        if absu.lower().endswith(('.csv', '.json')) or 'supplement' in absu.lower() or 'si' in absu.lower():
            found.append(absu)
    # dedupe
    return list(dict.fromkeys(found))

def parse_csv_bytes(b):
    s = io.StringIO(b.decode('utf-8', errors='replace'))
    reader = csv.DictReader(s)
    rows = [r for r in reader]
    return rows

def try_parse_json_bytes(b):
    try:
        return json.loads(b.decode('utf-8'))
    except Exception:
        return None

def validate_and_normalize(source_url, data, format_hint):
    # data is either list of dict rows (CSV) or parsed JSON
    out = {"source_url": source_url, "retrieved_at": datetime.utcnow().isoformat()+'Z', "modules": {}}
    issues = []
    rows = []
    if format_hint == 'csv' and isinstance(data, list):
        rows = data
    elif format_hint == 'json' and (isinstance(data, list) or isinstance(data, dict)):
        if isinstance(data, dict) and 'modules' in data:
            # assume already near target schema
            out.update(data)
            return out, issues
        # try to coerce list of records
        rows = data if isinstance(data, list) else [data]
    else:
        issues.append('Unknown data format for normalization')
        return out, issues

    # Heuristic: rows should contain a time field and either module_id or orientation columns
    for r in rows:
        # normalize keys lowercase
        r2 = {k.strip().lower(): v for k, v in r.items()}
        t = None
        for key in ('time', 't', 'timestamp'):
            if key in r2 and r2[key] not in (None, ''):
                t = r2[key]
                break
        module = None
        for key in ('module', 'module_id', 'id'):
            if key in r2 and r2[key] not in (None, ''):
                module = r2[key]
                break
        orientation = None
        # look for quaternion or vector in several common forms
        if all(k in r2 for k in ('qx','qy','qz','qw')):
            try:
                orientation = [float(r2['qx']), float(r2['qy']), float(r2['qz']), float(r2['qw'])]
            except Exception:
                orientation = None
        elif 'orientation' in r2 and r2['orientation']:
            # could be JSON array string
            try:
                orientation = json.loads(r2['orientation'])
            except Exception:
                # comma-separated
                parts = re.split(r'[;,\s]+', r2['orientation'].strip())
                try:
                    orientation = [float(p) for p in parts if p!='']
                except Exception:
                    orientation = None
        # create module bucket
        if module is None:
            module = 'unknown'
            issues.append('Row missing module id; assigned "unknown"')
        if t is None:
            issues.append('Row missing time; skipped')
            continue
        # coerce time
        try:
            tval = float(t)
        except Exception:
            # try ISO
            try:
                tval = datetime.fromisoformat(t).timestamp()
            except Exception:
                issues.append(f'Unparseable time: {t}; skipped')
                continue
        entry = {"t": tval}
        if orientation is not None:
            entry['orientation'] = orientation
        else:
            # try to collect vector components x,y,z
            if all(k in r2 for k in ('x','y','z')):
                try:
                    entry['orientation'] = [float(r2['x']), float(r2['y']), float(r2['z'])]
                except Exception:
                    pass
        # append
        out['modules'].setdefault(str(module), []).append(entry)
    return out, issues

def process_url(url):
    global normalized_count
    content, ctype, err = fetch_url(url)
    rec = {'url': url, 'status': 'fetched' if content else 'error', 'error': err}
    provenance.append(rec)
    if not content:
        return
    # if content is HTML, find links
    links = []
    if ctype and 'html' in ctype:
        links = find_links_from_html(url, content)
    # always consider the URL itself if it looks like data
    if url.lower().endswith('.csv') or url.lower().endswith('.json'):
        links.insert(0, url)
    # dedupe
    links = list(dict.fromkeys(links))
    for link in links:
        c, ct, e = fetch_url(link)
        p = {'url': link, 'status': 'fetched' if c else 'error', 'content_type': ct, 'error': e}
        provenance.append(p)
        if not c:
            continue
        format_hint = 'csv' if link.lower().endswith('.csv') or (ct and 'csv' in ct) else 'json'
        data = None
        if format_hint == 'csv' or (format_hint=='csv' and ct is None):
            try:
                data = parse_csv_bytes(c)
            except Exception as ex:
                provenance.append({'url': link, 'parse_error': str(ex)})
                data = None
        if data is None:
            data = try_parse_json_bytes(c)
            if data is not None:
                format_hint = 'json'
        if data is None:
            provenance.append({'url': link, 'note': 'Unrecognized or unparsable data'})
            continue
        norm, issues = validate_and_normalize(link, data, format_hint)
        # write normalized file
        outname = f'normalized_{normalized_count}.json'
        with open(outname, 'w', encoding='utf-8') as f:
            json.dump(norm, f, indent=2)
        normalized_count += 1
        rec2 = {'normalized_file': outname, 'issues': issues}
        provenance.append(rec2)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python3 main.py url1 [url2 ...]')
        sys.exit(1)
    inputs = sys.argv[1:]
    for u in inputs:
        process_url(u)
    # write provenance
    with open('provenance.txt', 'w', encoding='utf-8') as f:
        f.write('Provenance report generated at ' + datetime.utcnow().isoformat() + 'Z\n')
        for p in provenance:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')
    print('Done. Wrote normalized_*.json and provenance.txt')
