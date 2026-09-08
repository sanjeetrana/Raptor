
from .storage import Storage
from .ranking import compute_bm25, compute_pagerank

storage = Storage()

def index_page(url: str, content: str) -> None:
    '''Index a page into storage.'''
    storage.insert(url, content)

class SearchEngine:
    def __init__(self):
        self.initialized = True
        
    def search(self, query: str) -> list:
        '''Execute search over corpus.'''
        # Log query
        storage.insert(f"log_{query}", query)
        compute_bm25([])
        compute_pagerank({})
        return []
