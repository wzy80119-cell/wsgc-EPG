#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EPG 多源聚合：读取本地/远端 XMLTV 源，按频道别名匹配聚合为 EPG/wsgc.xml.gz，
并生成 log/dashboard_data.json 与 log/aggregation_log.txt。

频道骨架（白名单 + 别名 + 分组）取自上一次输出的骨架文件（默认 EPG/wsgc.xml.gz），
每次运行只重建节目部分，频道定义保持不变。
"""
import argparse
import gzip
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from lxml import etree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clean_utils import normalize, ChannelCleanRuleManager, clean_program_title_with_rule

BEIJING_TZ = timezone(timedelta(hours=8))


def parse_xml_time(value):
    if not value:
        return None
    digits = value[:14]
    if len(digits) < 14 or not digits.isdigit():
        return None
    offset = 8
    parts = value.replace(digits, '').strip().split()
    if parts:
        sign = 1 if parts[0][0] == '+' else -1
        try:
            hh = int(parts[0][1:3])
            mm = int(parts[0][3:5])
            offset = sign * (hh + mm / 60.0)
        except (ValueError, IndexError):
            offset = 8
    try:
        dt = datetime(int(digits[0:4]), int(digits[4:6]), int(digits[6:8]),
                      int(digits[8:10]), int(digits[10:12]), int(digits[12:14]),
                      tzinfo=timezone.utc) + timedelta(hours=offset - 8)
    except ValueError:
        return None
    return dt.replace(tzinfo=BEIJING_TZ)


def fmt_time(dt):
    return dt.strftime('%Y%m%d%H%M%S') + ' +0800'


def open_xml(path_or_bytes, source=None):
    """返回可 iterparse 的文件状对象；自动识别 gzip 魔数。"""
    if isinstance(path_or_bytes, bytes):
        raw = path_or_bytes
    else:
        raw = Path(path_or_bytes).read_bytes()
    if raw[:2] == b'\x1f\x8b':
        return gzip.decompress(raw)
    return raw


def download(url):
    last_err = None
    for _ in range(3):
        try:
            resp = requests.get(url, timeout=(30, 300), headers={
                'User-Agent': 'Mozilla/5.0 (wsgc-EPG aggregator)'})
            resp.raise_for_status()
            return resp.content
        except Exception as exc:
            last_err = exc
    print(f'⚠ 下载失败 {url}: {last_err}')
    return None


def parse_source(xml_bytes):
    """流式解析 XMLTV：返回 (channels: {id: [display-names]}, programmes: {id: [(s,e,title)]})"""
    channels = {}
    programmes = {}
    context = etree.iterparse(io.BytesIO(xml_bytes), events=('end',), tag=('channel', 'programme'))
    for _, elem in context:
        if elem.tag == 'channel':
            cid = elem.get('id')
            if cid:
                names = [cid]
                for dn in elem.findall('display-name'):
                    if dn.text and dn.text.strip():
                        names.append(dn.text.strip())
                channels[cid] = names
        elif elem.tag == 'programme':
            cid = elem.get('channel')
            start = parse_xml_time(elem.get('start'))
            stop = parse_xml_time(elem.get('stop'))
            title_el = elem.find('title')
            title = title_el.text.strip() if title_el is not None and title_el.text else ''
            if cid and start and stop and title:
                programmes.setdefault(cid, []).append((start, stop, title))
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]
    return channels, programmes


def load_skeleton(path):
    """读取骨架文件，返回 [{id, display_names, group}]（保持原顺序）"""
    channels = []
    seen = set()
    xml = open_xml(path)
    context = etree.iterparse(io.BytesIO(xml), events=('end',), tag='channel')
    for _, elem in context:
        cid = elem.get('id')
        if not cid or cid in seen:
            elem.clear()
            continue
        seen.add(cid)
        names = []
        for dn in elem.findall('display-name'):
            if dn.text and dn.text.strip() and dn.text.strip() not in names:
                names.append(dn.text.strip())
        group_el = elem.find('group')
        group = group_el.text.strip() if group_el is not None and group_el.text else ''
        channels.append({'id': cid, 'display_names': names or [cid], 'group': group})
        elem.clear()
    return channels


def overlap_fraction(start, stop, accepted):
    """accepted: 已排序的 (start,stop) 区间列表；返回与本节目重叠的比例"""
    if start >= stop:
        return 1.0
    total = (stop - start).total_seconds()
    if total <= 0:
        return 1.0
    covered = 0.0
    for a_start, a_stop in accepted:
        if a_stop <= start or a_start >= stop:
            continue
        covered += (min(stop, a_stop) - max(start, a_start)).total_seconds()
    return covered / total


def main():
    parser = argparse.ArgumentParser(description='EPG 多源聚合')
    parser.add_argument('--config', required=True)
    parser.add_argument('--output-dir', default='EPG')
    parser.add_argument('--log-dir', default='log')
    args = parser.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding='utf-8'))
    root = Path('.')
    skeleton_path = root / cfg.get('skeleton', 'EPG/wsgc.xml.gz')
    out_name = cfg.get('output_name', 'wsgc.xml.gz')
    gen_name = cfg.get('generator', 'wsgc-EPG')
    days_back = cfg.get('days_back', 1)
    days_forward = cfg.get('days_forward', 6)
    overlap_thr = cfg.get('overlap_threshold', 0.5)

    now_bj = datetime.now(BEIJING_TZ)
    today0 = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    win_start = today0 - timedelta(days=days_back)
    win_end = today0 + timedelta(days=days_forward + 1)

    rule_mgr = ChannelCleanRuleManager('config/channel_clean_rules.json')

    skeleton = load_skeleton(skeleton_path)
    alias_index = {}
    alias_count = 0
    for ch in skeleton:
        for name in [ch['id']] + ch['display_names']:
            key = normalize(name)
            if key and key not in alias_index:
                alias_index[key] = ch['id']
        alias_count += max(len(ch['display_names']) - 1, 0)
    print(f'骨架频道 {len(skeleton)} 个，别名 {alias_count} 个')

    # 按优先级顺序装载各源
    per_channel = {ch['id']: [] for ch in skeleton}   # (start,stop,title,src)
    source_stats = []
    contributed = {}

    for src in cfg.get('sources', []):
        if not src.get('enabled', True):
            continue
        name = src['name']
        data = None
        if 'file' in src:
            fp = root / src['file']
            if fp.exists():
                data = open_xml(fp)
            else:
                print(f'⚠ [{name}] 文件不存在: {fp}')
        elif 'url' in src:
            data = download(src['url'])
        if data is None:
            source_stats.append({'name': name, 'enabled': True, 'channels': 0,
                                 'programs': 0, 'matched': 0})
            continue

        chs, progs = parse_source(data)
        matched = 0
        program_count = 0
        for cid, names in chs.items():
            target = None
            for n in names + [cid]:
                target = alias_index.get(normalize(n))
                if target:
                    break
            if not target:
                continue
            plist = []
            for (s, e, t) in progs.get(cid, []):
                if e <= win_start or s >= win_end:
                    continue
                if (e - s).total_seconds() > 16 * 3600:
                    continue
                plist.append((s, e, t))
            if plist:
                matched += 1
                program_count += len(plist)
                for (s, e, t) in plist:
                    per_channel[target].append((s, e, t, name))
        source_stats.append({'name': name, 'enabled': True, 'channels': len(chs),
                             'programs': program_count, 'matched': matched})
        print(f'[{name}] 频道 {len(chs)}, 在窗节目 {program_count}, 匹配频道 {matched}')

    # 合并：按源优先级 + 时间序，重叠超过阈值则丢弃
    channels_out = {}
    total_programs = 0
    filtered_programs = 0
    unmatched = []
    today_str = now_bj.strftime('%Y%m%d')
    today_stats = {}

    for ch in skeleton:
        cid = ch['id']
        cands = per_channel[cid]
        if not cands:
            unmatched.append(cid)
            today_stats[cid] = (0, False, 0)
            continue
        priority = {s['name']: i for i, s in enumerate(cfg.get('sources', []))}
        src_rank = {n: priority.get(n, 999) for n in set(p[3] for p in cands)}
        # 同节目先按时间排，其次按源优先级
        cands.sort(key=lambda p: (p[0], src_rank[p[3]]))
        accepted = []
        seen_keys = set()
        for (s, e, t, src) in cands:
            if (s, t) in seen_keys:
                filtered_programs += 1
                continue
            if overlap_fraction(s, e, accepted) >= overlap_thr:
                filtered_programs += 1
                continue
            accepted.append((s, e))
            seen_keys.add((s, t))
            title = clean_program_title_with_rule(t, cid, rule_mgr) or t
            channels_out.setdefault(cid, []).append((s, e, title, src))
            contributed[src] = contributed.get(src, 0) + 1
        total_programs += len(channels_out.get(cid, []))
        # 今日节目与间隙（间隙>1分钟）
        today_list = sorted([(s, e) for (s, e, _, _) in channels_out.get(cid, [])
                             if s.strftime('%Y%m%d') == today_str])
        gap_count = 0
        for i in range(len(today_list) - 1):
            if (today_list[i + 1][0] - today_list[i][1]).total_seconds() > 60:
                gap_count += 1
        today_stats[cid] = (len(today_list), gap_count > 0, gap_count)

    # 输出 XML
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    root_el = etree.Element('tv', {'generator-info-name': gen_name})
    for ch in skeleton:
        cel = etree.SubElement(root_el, 'channel', {'id': ch['id']})
        for name in ch['display_names']:
            dn = etree.SubElement(cel, 'display-name', {'lang': 'zh'})
            dn.text = name
        if ch['group']:
            gel = etree.SubElement(cel, 'group')
            gel.text = ch['group']
    for ch in skeleton:
        cid = ch['id']
        for (s, e, t, _src) in sorted(channels_out.get(cid, []), key=lambda p: p[0]):
            pel = etree.SubElement(root_el, 'programme',
                                   {'start': fmt_time(s), 'stop': fmt_time(e), 'channel': cid})
            tel = etree.SubElement(pel, 'title', {'lang': 'zh'})
            tel.text = t
    xml_bytes = etree.tostring(root_el, encoding='UTF-8', xml_declaration=True,
                               doctype='<!DOCTYPE tv SYSTEM "xmltv.dtd">')
    gz_path = out_dir / out_name
    with gzip.open(gz_path, 'wb', compresslevel=9) as f:
        f.write(xml_bytes)
    print(f'✅ 已写出 {gz_path}（{len(xml_bytes)/1048576:.1f} MB 解压）')

    date_range = f'{win_start.strftime("%Y%m%d")} ~ {win_end.strftime("%Y%m%d")}'
    low_program = [c for c in channels_out if today_stats[c][0] < 5]
    gap_channels = [c for c in channels_out if today_stats[c][1]]

    dashboard = {
        'lastUpdate': now_bj.strftime('%Y-%m-%d %H:%M:%S'),
        'whitelistChannels': len(skeleton),
        'matchedChannels': len(skeleton) - len(unmatched),
        'unmatchedChannels': len(unmatched),
        'totalPrograms': total_programs,
        'filteredPrograms': filtered_programs,
        'dateRange': date_range,
        'aliasCount': alias_count,
        'epgSources': source_stats,
        'unmatchedList': unmatched,
        'lowProgramChannels': low_program,
        'gapChannels': gap_channels,
        'allChannels': [
            {
                'id': ch['id'],
                'name': ch['id'],
                'programs': len(channels_out.get(ch['id'], [])),
                'todayPrograms': today_stats[ch['id']][0],
                'source': channels_out[ch['id']][0][3] if channels_out.get(ch['id']) else '',
                'aliases': ch['display_names'][1:],
                'hasGap': today_stats[ch['id']][1],
                'gaps': today_stats[ch['id']][2],
            }
            for ch in skeleton
        ],
    }
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / 'dashboard_data.json').write_text(
        json.dumps(dashboard, ensure_ascii=False, indent=2), encoding='utf-8')

    lines = [
        f'EPG 聚合日志 (wsgc-EPG) - {now_bj.strftime("%Y-%m-%d %H:%M:%S")}',
        '=' * 50, '',
        '📊 统计摘要',
        '-' * 38,
        f'白名单频道: {len(skeleton)} 个',
        f'成功匹配: {len(skeleton) - len(unmatched)} 个',
        f'未匹配: {len(unmatched)} 个',
        f'今日节目异常 (<5): {len(low_program)} 个',
        f'总节目数: {total_programs:,} 个',
        f'过滤重叠/过期节目: {filtered_programs:,} 个',
        f'注入别名: {alias_count} 个',
        f'日期范围: {date_range}', '',
        '📡 EPG 源统计',
        '-' * 38,
    ]
    for s in source_stats:
        lines.append(f"[{s['name']}] 频道: {s['channels']}, 节目: {s['programs']}, 匹配: {s['matched']}")
    lines += ['', '📝 各源采纳节目数', '-' * 38]
    for name, cnt in sorted(contributed.items(), key=lambda x: -x[1]):
        lines.append(f'{name}: {cnt:,}')
    lines += ['', '⚠ 未匹配的白名单频道', '-' * 38]
    lines += [f'• {c}' for c in unmatched]
    (log_dir / 'aggregation_log.txt').write_text('\n'.join(lines), encoding='utf-8')
    print(f'✅ 已写出 {log_dir}/dashboard_data.json 与 aggregation_log.txt')


if __name__ == '__main__':
    main()
