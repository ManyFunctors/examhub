"""Scrapy crawlers for the catalogue and its feeds.

Run from the repository root:

    scrapy list
    scrapy crawl feeds                 # every active feed -> data/harvest/notices.jsonl
    scrapy crawl feeds -a body=in-upsc # one body
    scrapy crawl verify                # health of every body website and feed URL
    scrapy crawl seed-ssc              # proposals from an official exam list

Pages whose content is rendered client-side are fetched with headless
Firefox (``render = "browser"`` on the feed), never with Playwright.
"""
