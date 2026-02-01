"""
Web Search Module for Album Discovery

Uses DuckDuckGo search to find new album releases and classic album lists.
"""

from ddgs import DDGS
from pydantic import BaseModel


class AlbumInfo(BaseModel):
    """Information about an album"""

    title: str
    artist: str
    release_date: str | None = None
    genre: str | None = None
    source_url: str | None = None
    description: str | None = None
    why_recommended: str | None = None


class SearchResult(BaseModel):
    """Raw search result"""

    title: str
    url: str
    body: str


class WebSearcher:
    """Handles web searches for music discovery"""

    def __init__(self):
        self.ddgs = DDGS()

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Perform a web search and return results"""
        try:
            results = self.ddgs.text(
                query,
                max_results=max_results,
                timelimit="w",  # Last week
            )
            return [
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("href", ""),
                    body=r.get("body", ""),
                )
                for r in results
            ]
        except Exception as e:
            print(f"Search error: {e}")
            return []

    def search_new_releases(
        self,
        genres: list[str] | None = None,
        artists: list[str] | None = None,
    ) -> list[SearchResult]:
        """
        Search for new album releases from curated music publications.

        Sources:
            - Pitchfork
            - Stereogum
            - Consequence of Sound
            - Resident Advisor
            - Jenesaispop (Spanish music)

        Args:
            genres: List of genres to focus on
            artists: List of similar artists to look for
        """
        results = []

        # Curated sources for new releases
        sources = [
            ("site:pitchfork.com", "new album review"),
            ("site:stereogum.com", "album of the week"),
            ("site:consequence.net", "new album stream"),
            ("site:residentadvisor.net", "new album review"),
            ("site:jenesaispop.com", "nuevo disco"),
            ("site:lesinrocks.com", "nouvel album"),
            ("site:nova.fr", "nouvel album"),
            ("site:thelineofbestfit.com", "album review"),
        ]

        queries = []
        for site, search_term in sources:
            queries.append(f"{site} {search_term} 2025")

        # Add genre-specific searches on Pitchfork/Stereogum
        if genres:
            for genre in genres[:2]:
                queries.append(f"site:pitchfork.com {genre} album review 2025")
                queries.append(f"site:stereogum.com {genre} new album 2025")

        # Search for similar artists' new releases
        if artists:
            for artist in artists[:3]:
                queries.append(f'"{artist}" new album 2025')

        seen_urls = set()
        for query in queries:
            for result in self.search(query, max_results=5):
                if result.url not in seen_urls:
                    results.append(result)
                    seen_urls.add(result.url)

        return results

    def search_classic_albums(
        self,
        exclude_artists: list[str] | None = None,
    ) -> list[SearchResult]:
        """
        Search for classic/greatest albums of all time.

        Args:
            exclude_artists: Artists the user already knows well
        """
        queries = [
            "greatest albums of all time list",
            "best albums ever made rolling stone",
            "classic albums everyone should hear",
            "essential albums music history",
            "critically acclaimed albums all genres",
            "hidden gem classic albums underrated",
        ]

        results = []
        seen_urls = set()

        for query in queries:
            for result in self.search(query, max_results=5):
                if result.url not in seen_urls:
                    results.append(result)
                    seen_urls.add(result.url)

        return results

    def search_album_info(self, artist: str, album: str) -> list[SearchResult]:
        """Get more information about a specific album"""
        query = f'"{artist}" "{album}" album review'
        return self.search(query, max_results=3)


# Quick test
def quick_test():
    searcher = WebSearcher()

    print("🔍 Searching for new releases...")
    results = searcher.search_new_releases(
        genres=["indie", "electronic"],
        artists=["Rosalía", "Bad Bunny"],
    )

    for r in results[:5]:
        print(f"\n📀 {r.title}")
        print(f"   {r.url}")
        print(f"   {r.body[:100]}...")


if __name__ == "__main__":
    quick_test()
