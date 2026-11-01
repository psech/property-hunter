import httpx

from hunter.sources.web import Fetcher


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
