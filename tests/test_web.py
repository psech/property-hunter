from urllib.robotparser import RobotFileParser

import httpx

from hunter.sources.web import MAX_CRAWL_DELAY_S, Fetcher


def proxy_of(fetcher: Fetcher, url: str):
    transport = fetcher.http._transport_for_url(httpx.URL(url))
    return getattr(transport._pool, "_proxy_url", None)


def test_only_listed_hosts_go_through_the_proxy():
    fetcher = Fetcher(proxy="http://100.64.0.1:8888", proxied_hosts={"www.pulseproperty.com.au"})
    try:
        assert proxy_of(fetcher, "https://www.pulseproperty.com.au/wp-json/api/listings/all") is not None
        assert proxy_of(fetcher, "https://raywhitesutherlandshire.com.au/api") is None
    finally:
        fetcher.close()


def test_without_a_proxy_everything_goes_direct():
    fetcher = Fetcher(proxy=None, proxied_hosts={"www.pulseproperty.com.au"})
    try:
        assert fetcher.proxied_hosts == set()
        assert proxy_of(fetcher, "https://www.pulseproperty.com.au/") is None
    finally:
        fetcher.close()


def test_crawl_delay_from_robots_txt_is_honoured_up_to_a_cap():
    fetcher = Fetcher(delay_s=1.5)
    try:
        for host, rules in {
            "slow.example": "User-agent: *\nCrawl-delay: 10\n",
            "glacial.example": "User-agent: *\nCrawl-delay: 600\n",
            "other-bot.example": "User-agent: bingbot\nCrawl-delay: 15\n\nUser-agent: *\nDisallow: /wp-admin/\n",
        }.items():
            parser = RobotFileParser()
            parser.parse(rules.splitlines())
            fetcher._robots[host] = parser

        assert fetcher.delay_for("https://slow.example/buy") == 10
        assert fetcher.delay_for("https://glacial.example/buy") == MAX_CRAWL_DELAY_S
        assert fetcher.delay_for("https://other-bot.example/buy") == 1.5
        assert fetcher.delay_for("https://unseen.example/buy") == 1.5
    finally:
        fetcher.close()
