"""Scrapers package — re-exports all platform scraper classes."""

from src.scrapers.baidu_baijiahao import BaiduBaijiahaoScraper
from src.scrapers.base import BaseScraper
from src.scrapers.bilibili import BilibiliScraper
from src.scrapers.douban import DoubanScraper
from src.scrapers.huxiu import HuxiuScraper
from src.scrapers.juejin import JuejinScraper
from src.scrapers.kr36 import Kr36Scraper
from src.scrapers.maimai import MaimaiScraper
from src.scrapers.rss_generic import RssGenericScraper
from src.scrapers.toutiao import ToutiaoScraper
from src.scrapers.weixin_sogou import WeixinSogouScraper
from src.scrapers.xiaohongshu import XiaohongshuScraper
from src.scrapers.zhihu import ZhihuScraper

__all__ = [
    "BaseScraper",
    "BaiduBaijiahaoScraper",
    "BilibiliScraper",
    "DoubanScraper",
    "HuxiuScraper",
    "JuejinScraper",
    "Kr36Scraper",
    "MaimaiScraper",
    "RssGenericScraper",
    "ToutiaoScraper",
    "WeixinSogouScraper",
    "XiaohongshuScraper",
    "ZhihuScraper",
]