
class Storage:
    def __init__(self):
        self.db = {}
        
    def insert(self, doc_id: str, data: str) -> None:
        '''Insert document into storage with WAL logic.'''
        self.wal_sync(doc_id, data)
        self.db[doc_id] = data
        
    def wal_sync(self, doc_id: str, data: str) -> None:
        pass
