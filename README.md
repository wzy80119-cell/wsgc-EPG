# wsgc-EPG
> 往事如风的 IPTV 指南 —— 汇聚 EPG 数据管理与 M3U 频道编辑的一站式平台

## 项目简介

wsgc-EPG 是一个 IPTV 电子节目指南（EPG）聚合与管理项目。它自动抓取多个来源的 EPG 数据，经清洗合并后生成标准 XMLTV 格式的 EPG 文件，供 IPTV 播放器直接订阅使用。项目通过 GitHub Actions 每日自动运行，无需服务器，前端面板部署在 GitHub Pages 上，打开即用。

## 功能特性

- **多源 EPG 聚合**：聚合 山东移动、山东广电、山东联通、海南移动、电视猫 等多源数据
- **Desc 描述注入**：提取 → 刮削 → 注入节目描述，让节目单信息更丰富
- **自动清洗**：频道名清洗、栏目前缀删除、续集编号保护等规则化处理
- **每日自动更新**：GitHub Actions 定时聚合、注入并提交

## 前端面板

主页部署在 GitHub Pages，提供三个工具入口：

| 入口 | 路径 | 说明 |
|------|------|------|
| 📺 EPG 仪表盘 | `dashboard/` | EPG 数据概览、频道列表、节目单预览、下载地址 |
| 🔄 频道管理工具 | `m3u/` | M3U 列表转换、编辑、排序、Logo 匹配、添加频道 |
| 🔬 EPG 解析工具 | `epg-parser/` | XML/GZ 节目单解析，频道与节目数据浏览分析 |

### 仪表盘功能

- **总体概览**：频道总数、节目总数、匹配率、EPG 时间范围、更新时间
- **频道列表**：分组筛选（央视 / 卫视 / 收费 / 省份等）、搜索、多种排序方式
- **节目单预览**：点击频道查看详细节目单，自动定位当前播出节目
- **匹配率统计**：展示各频道 Desc 描述的匹配情况
- **间隙检测**：检测节目时间轴间隙，只统计当天
- **EPG 下载地址**：面板内提供直连与加速下载链接，一键复制 / 下载

## EPG 下载地址

> 路径：`EPG/` · 分支：`main` · 加速前缀：`https://gh-proxy.org/`

### 带 Desc 描述（推荐）

| 方式 | 地址 |
|------|------|
| 直连 | `https://github.com/wzy80119-cell/wsgc-EPG/raw/main/EPG/wsgc-desc.xml.gz` |
| 加速 | `https://gh-proxy.org/https://github.com/wzy80119-cell/wsgc-EPG/raw/main/EPG/wsgc-desc.xml.gz` |

### 不带描述

| 方式 | 地址 |
|------|------|
| 直连 | `https://github.com/wzy80119-cell/wsgc-EPG/raw/main/EPG/wsgc.xml.gz` |
| 加速 | `https://gh-proxy.org/https://github.com/wzy80119-cell/wsgc-EPG/raw/main/EPG/wsgc.xml.gz` |

### 通用地址模板

```
直连：https://github.com/wzy80119-cell/wsgc-EPG/raw/main/EPG/{文件名}
加速：https://gh-proxy.org/https://github.com/wzy80119-cell/wsgc-EPG/raw/main/EPG/{文件名}
```

将 `{文件名}` 替换为 `EPG/` 目录下的任意文件即可（如 `sdm.xml.gz`、`tvmao.xml.gz` 等）。

## 文件结构

```
EPG/                 # EPG 输出文件
  wsgc-desc.xml.gz      # 带描述（推荐）
  wsgc.xml.gz           # 不带描述
dashboard/            # EPG 仪表盘前端
m3u/                  # 频道管理工具前端
epg-parser/           # EPG 解析工具前端
database/             # Desc 数据库与匹配日志
config/               # 清洗规则配置
scripts/              # 处理脚本
.github/workflows/    # GitHub Actions 工作流
```
