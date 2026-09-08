
from .engine import SearchEngine

engine = SearchEngine()

class DummyRequest:
    def __init__(self, query):
        self.query = query

def do_GET(request: DummyRequest) -> str:
    '''Handle HTTP GET request for search.'''
    results = engine.search(request.query)
    return str(results)
