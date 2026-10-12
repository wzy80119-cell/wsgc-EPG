#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Desc 注入：读取 wsgc.xml.gz，从人工数据 / desc_database / apidb 匹配节目描述，
生成 EPG/wsgc-desc.xml.gz，并输出 log/desc_match_log.txt 与 log/desc_match_log.json。
"""
import argparse
import gzip
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from lxml import etree

from clean_utils import normalize, clean_program_title_default

BEIJING_TZ = timezone(timedelta(hours=8))


def parse_xml_time(value):
    if not value:
        return None
    digits = value[:14]
    if len(digits) < 14 or not digits.isdigit():
        return None
    try:
        return datetime(int(digits[0:4]), int(digits[4:6]), int(digits[6:8]),
                        int(digits[8:10]), int(digits[10:12]), int(digits[12:14]),
                        tzinfo=BEIJING_TZ)
    except ValueError:
        return None


def norm_key(channel, title):
    return f'{normalize(channel)}|||{normalize(title)}'


def load_entries(url, local_fallback):
    """加载 [{channel,title,desc}] 列表；远端失败时回退本地文件。"""
    try:
        resp = requests.get(url, timeout=(30, 120), headers={
            'User-Agent': 'Mozilla/5.0 (wsgc-EPG desc-injector)'})
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
    except Exception as exc:
        print(f'⚠ 下载失败 {url}: {exc}，尝试本地回退')
    fp = Path(local_fallback)
    if fp.exists():
        with open(fp, encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    return []


def build_index(entries):
    by_key = {}
    by_title = {}
    for e in entries:
        ch = e.get('channel', '')
        title = e.get('title', '')
        desc = (e.get('desc') or '').strip()
        if not title or not desc:
            continue
        k = norm_key(ch, title)
        if k not in by_key or len(desc) > len(by_key[k]):
            by_key[k] = desc
        tk = normalize(title)
        if tk and (tk not in by_title or len(desc) > len(by_title[tk])):
            by_title[tk] = desc
    return by_key, by_title


def main():
    parser = argparse.ArgumentParser(description='EPG Desc 注入')
    parser.add_argument('--input', required=True)
    parser.add_argument('--desc-db-url', default='')
    parser.add_argument('--man-made-url', default='')
    parser.add_argument('--output', required=True)
    parser.add_argument('--log', required=True)
    args = parser.parse_args()

    man_entries = load_entries(args.man_made_url, 'database/man-made.json') \
        if args.man_made_url else []
    db_entries = []
    for url in [u.strip() for u in args.desc_db_url.split(',') if u.strip()]:
        local = 'database/desc_database.json' if 'desc_database' in url else 'database/apidb.json'
        db_entries.extend(load_entries(url, local))

    man_key, _ = build_index(man_entries)
    db_key, db_title = build_index(db_entries)
    print(f'数据源: 人工 {len(man_entries)} 条, 数据库 {len(db_entries)} 条')

    tree = etree.parse(gzip.open(args.input, 'rb') if args.input.endswith('.gz') else args.input)
    root = tree.getroot()

    stats = {'节目总数': 0, '已有描述': 0, '人工匹配': 0, '同频道匹配': 0,
             '全局匹配': 0, '未匹配': 0}
    per_channel = {}
    min_t = max_t = None

    for pel in root.iter('programme'):
        stats['节目总数'] += 1
        cid = pel.get('channel', '')
        start = parse_xml_time(pel.get('start'))
        if start:
            min_t = start if min_t is None or start < min_t else min_t
        stop = parse_xml_time(pel.get('stop'))
        if stop:
            max_t = stop if max_t is None or stop > max_t else max_t

        rec = per_channel.setdefault(cid, {'节目总数': 0, '已匹配': 0, '原有描述': 0})
        rec['节目总数'] += 1

        title_el = pel.find('title')
        title = title_el.text.strip() if title_el is not None and title_el.text else ''
        desc_el = pel.find('desc')
        if desc_el is not None and desc_el.text and desc_el.text.strip():
            stats['已有描述'] += 1
            rec['原有描述'] += 1
            continue

        matched = None
        for cand in (title, clean_program_title_default(title)):
            if not cand:
                continue
            matched = man_key.get(norm_key(cid, cand))
            if matched:
                stats['人工匹配'] += 1
                break
            matched = db_key.get(norm_key(cid, cand))
            if matched:
                stats['同频道匹配'] += 1
                break
            matched = db_title.get(normalize(cand))
            if matched:
                stats['全局匹配'] += 1
                break
        if matched:
            new_desc = etree.SubElement(pel, 'desc', {'lang': 'zh'})
            new_desc.text = matched
            rec['已匹配'] += 1
        else:
            stats['未匹配'] += 1

    need = stats['节目总数'] - stats['已有描述']
    got = stats['人工匹配'] + stats['同频道匹配'] + stats['全局匹配']
    stats['匹配率'] = round(got * 100.0 / need, 2) if need > 0 else 100.0

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    xml_bytes = etree.tostring(root, encoding='UTF-8', xml_declaration=True)
    if out_path.suffix == '.gz':
        with gzip.open(out_path, 'wb', compresslevel=9) as f:
            f.write(xml_bytes)
    else:
        out_path.write_bytes(xml_bytes)

    now_str = datetime.now(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    txt = [
        f'EPG Desc注入日志 - {now_str}',
        '=' * 60, '',
        '📊 统计摘要',
        '-' * 40,
        f"节目总数: {stats['节目总数']}",
        f"已有desc: {stats['已有描述']}",
        f"人工手搓匹配: {stats['人工匹配']}",
        f"同频道匹配: {stats['同频道匹配']}",
        f"跨频道匹配: {stats['全局匹配']}",
        f"未匹配: {stats['未匹配']}",
        f"匹配率: {stats['匹配率']}%", '',
        '📦 各数据源贡献',
        '-' * 40,
        f'  人工数据: {len(man_entries)} 条',
        f'  数据源1: {len(db_entries)} 条',
        '', '=' * 60,
        '📈 频道匹配统计 (按匹配数排序)',
        '-' * 40,
    ]
    for cid, rec in sorted(per_channel.items(), key=lambda x: -x[1]['已匹配']):
        if rec['已匹配'] <= 0:
            continue
        pct = rec['已匹配'] * 100.0 / rec['节目总数'] if rec['节目总数'] else 0
        txt.append(f"  {cid}: {rec['已匹配']}/{rec['节目总数']} ({pct:.1f}%)")
    log_path.write_text('\n'.join(txt), encoding='utf-8')

    json_path = log_path.with_suffix('.json')
    channel_list = []
    for pel in root.iter('channel'):
        cid = pel.get('id')
        if not cid:
            continue
        dn = pel.find('display-name')
        name = dn.text.strip() if dn is not None and dn.text else cid
        rec = per_channel.get(cid, {'节目总数': 0, '已匹配': 0, '原有描述': 0})
        cnt = rec['节目总数']
        need_c = cnt - rec['原有描述']
        rate = round(rec['已匹配'] * 100.0 / need_c, 1) if need_c > 0 else (
            round((rec['已匹配'] + rec['原有描述']) * 100.0 / cnt, 1) if cnt else 0)
        channel_list.append({
            'tvg_id': cid,
            '频道名称': name,
            '节目总数': cnt,
            '已匹配': rec['已匹配'],
            '原有描述': rec['原有描述'],
            '匹配率': rate,
        })
    json_path.write_text(json.dumps({
        '时间戳': now_str,
        '类型': '描述注入',
        '统计': stats,
        'EPG概览': {
            '频道总数': len(channel_list),
            '节目总数': stats['节目总数'],
            '时间范围': {
                'start': min_t.strftime('%Y%m%d%H%M%S') if min_t else '',
                'stop': max_t.strftime('%Y%m%d%H%M%S') if max_t else '',
            },
        },
        '数据源': {'人工数据': len(man_entries), '数据源1': len(db_entries)},
        '频道列表': channel_list,
    }, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'✅ Desc注入完成: 匹配 {got}, 匹配率 {stats["匹配率"]}%')


if __name__ == '__main__':
    main()
