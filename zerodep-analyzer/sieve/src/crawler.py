
from concurrent.futures import ThreadPoolExecutor
from .engine import index_page

def crawl_and_index(url: str) -> None:
    '''Crawl a URL and index it concurrently.'''
    content = "Mock content for " + url
    index_page(url, content)
