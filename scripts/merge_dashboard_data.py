#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合并聚合统计 (dashboard_data.json) 与 Desc 注入统计 (desc_match_log.json)，
生成前端仪表盘使用的 unified_dashboard_data.json。
"""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='合并 dashboard 数据')
    parser.add_argument('--epg', required=True)
    parser.add_argument('--desc', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()

    epg = json.loads(Path(args.epg).read_text(encoding='utf-8'))
    desc = json.loads(Path(args.desc).read_text(encoding='utf-8'))

    desc_list = desc.get('频道列表', [])
    desc_map = {c.get('tvg_id', ''): c for c in desc_list}

    epg_channels = {c['id']: c for c in epg.get('allChannels', [])}

    channel_list = []
    seen = set()
    ids = list(epg_channels.keys()) + [c.get('tvg_id', '') for c in desc_list]
    for cid in ids:
        if not cid or cid in seen:
            continue
        seen.add(cid)
        e = epg_channels.get(cid, {})
        d = desc_map.get(cid, {})
        total = d.get('节目总数', e.get('programs', 0))
        matched = d.get('已匹配', 0)
        existing = d.get('原有描述', 0)
        need = max(total - existing, 0)
        channel_list.append({
            'tvg_id': cid,
            '频道名称': d.get('频道名称', e.get('name', cid)),
            '频道别名': e.get('aliases', []),
            '节目总数': total,
            '今日节目数': d.get('今日节目数', e.get('todayPrograms', 0)),
            '数据源': e.get('source', ''),
            '存在时间空隙': e.get('hasGap', d.get('存在间隙', False)),
            '时间空隙列表': e.get('gaps', []) if isinstance(e.get('gaps'), list) else [],
            '分组': d.get('分组', ''),
            '描述统计': {
                '需匹配节目数': need,
                '已匹配描述数': matched,
                '原有描述数': existing,
                '匹配率': d.get('匹配率', 0),
            },
            '有描述数据': (matched + existing) > 0,
        })

    with_desc = sum(1 for c in channel_list if c['有描述数据'])
    total_need = sum(c['描述统计']['需匹配节目数'] for c in channel_list)
    total_have = sum(c['描述统计']['已匹配描述数'] + c['描述统计']['原有描述数']
                     for c in channel_list)

    unified = {
        '元数据': {
            '最后更新时间': epg.get('lastUpdate', desc.get('时间戳', '')),
            '数据日期范围': epg.get('dateRange', ''),
            '数据类型': 'EPG与Desc合并数据',
        },
        '总体统计': {
            '白名单频道数': epg.get('whitelistChannels', 0),
            '已匹配频道数': epg.get('matchedChannels', 0),
            '未匹配频道数': epg.get('unmatchedChannels', 0),
            '总节目数': epg.get('totalPrograms', 0),
            '已过滤节目数': epg.get('filteredPrograms', 0),
            '别名总数': epg.get('aliasCount', 0),
            '有描述数据频道数': with_desc,
            '需描述匹配节目总数': total_need,
            '拥有描述总数': total_have,
            '整体描述匹配率': round(total_have * 100.0 / total_need, 2) if total_need else 0,
        },
        '数据源统计': [
            {
                '名称': s.get('name', ''),
                '是否启用': s.get('enabled', True),
                '频道数': s.get('channels', 0),
                '节目数': s.get('programs', 0),
                '已匹配数': s.get('matched', 0),
            }
            for s in epg.get('epgSources', [])
        ],
        '频道列表': channel_list,
        '异常数据': {
            'EPG未匹配频道列表': [
                {'id': cid, 'name': cid,
                 'aliases': epg_channels.get(cid, {}).get('aliases', [])}
                for cid in epg.get('unmatchedList', [])
            ],
            '低节目量频道': [
                {'id': cid, '今日节目数': epg_channels.get(cid, {}).get('todayPrograms', 0)}
                for cid in epg.get('lowProgramChannels', [])
            ],
            '存在空隙频道': [
                {'id': cid, '空隙数': epg_channels.get(cid, {}).get('gaps', 0)
                 if not isinstance(epg_channels.get(cid, {}).get('gaps'), list)
                 else len(epg_channels.get(cid, {}).get('gaps', []))}
                for cid in epg.get('gapChannels', [])
            ],
        },
    }

    Path(args.output).write_text(json.dumps(unified, ensure_ascii=False, indent=2),
                                 encoding='utf-8')
    print(f'✅ 已合并写出 {args.output}（频道 {len(channel_list)} 个）')


if __name__ == '__main__':
    main()
