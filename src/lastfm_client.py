"""
Last.fm API Client

Handles fetching user listening data from Last.fm API.
"""

import os
import time
from collections import Counter
from datetime import datetime, timedelta

import httpx
from pydantic import BaseModel


class Track(BaseModel):
    """A scrobbled track from Last.fm"""

    name: str
    artist: str
    album: str | None = None
    timestamp: datetime | None = None


class ArtistStats(BaseModel):
    """Aggregated stats for an artist"""

    name: str
    play_count: int
    top_tracks: list[str]


class TasteProfile(BaseModel):
    """User's musical taste profile based on listening history"""

    top_artists: list[ArtistStats]
    top_genres: list[str]  # Inferred from artist tags
    total_scrobbles: int
    period_days: int
    raw_artist_counts: dict[str, int]


class LastFMClient:
    """Client for Last.fm API interactions"""

    BASE_URL = "https://ws.audioscrobbler.com/2.0/"

    def __init__(self, api_key: str, username: str):
        self.api_key = api_key
        self.username = username
        self.client = httpx.Client(
            timeout=30.0, headers={"User-Agent": "MusicRecommenderAgent/1.0"}
        )

    def _request(self, method: str, **params) -> dict:
        """Make a request to the Last.fm API"""
        params.update(
            {
                "method": method,
                "api_key": self.api_key,
                "format": "json",
            }
        )

        response = self.client.get(self.BASE_URL, params=params)
        response.raise_for_status()
        return response.json()

    def get_recent_tracks(self, days: int = 30, limit_per_page: int = 200) -> list[Track]:
        """
        Fetch recent tracks from the last N days.

        Args:
            days: Number of days to look back
            limit_per_page: Max tracks per API call (max 200)

        Returns:
            List of Track objects
        """
        # Calculate Unix timestamp for 'from' parameter
        from_time = int((datetime.now() - timedelta(days=days)).timestamp())

        tracks = []
        page = 1
        total_pages = 1

        while page <= total_pages:
            data = self._request(
                "user.getRecentTracks",
                user=self.username,
                limit=limit_per_page,
                page=page,
                **{"from": from_time},  # 'from' is a reserved keyword
                extended=1,
            )

            recent_tracks = data.get("recenttracks", {})
            total_pages = int(recent_tracks.get("@attr", {}).get("totalPages", 1))

            for track in recent_tracks.get("track", []):
                # Skip "now playing" tracks (they don't have a date)
                if "@attr" in track and track["@attr"].get("nowplaying") == "true":
                    continue

                tracks.append(
                    Track(
                        name=track.get("name", ""),
                        artist=track.get("artist", {}).get("name", "")
                        if isinstance(track.get("artist"), dict)
                        else track.get("artist", ""),
                        album=track.get("album", {}).get("#text", "")
                        if isinstance(track.get("album"), dict)
                        else None,
                        timestamp=datetime.fromtimestamp(int(track["date"]["uts"]))
                        if "date" in track
                        else None,
                    )
                )

            page += 1
            time.sleep(0.2)  # Rate limiting

        return tracks

    def get_top_artists(
        self,
        period: str = "1month",  # 7day, 1month, 3month, 6month, 12month, overall
        limit: int = 50,
    ) -> list[ArtistStats]:
        """Fetch user's top artists for a given period"""
        data = self._request(
            "user.getTopArtists",
            user=self.username,
            period=period,
            limit=limit,
        )

        artists = []
        for artist in data.get("topartists", {}).get("artist", []):
            artists.append(
                ArtistStats(
                    name=artist.get("name", ""),
                    play_count=int(artist.get("playcount", 0)),
                    top_tracks=[],
                )
            )
        return artists

    def get_artist_tags(self, artist: str, limit: int = 5) -> list[str]:
        """Get genre tags for an artist"""
        try:
            data = self._request(
                "artist.getTopTags",
                artist=artist,
                limit=limit,
            )
            return [tag["name"].lower() for tag in data.get("toptags", {}).get("tag", [])]
        except Exception:
            return []

    def build_taste_profile(self, days: int = 30) -> TasteProfile:
        """
        Build a comprehensive taste profile from recent listening.

        This aggregates recent tracks into artist statistics and
        infers genre preferences from artist tags.
        """
        tracks = self.get_recent_tracks(days=days)

        # Aggregate by artist
        artist_counts = Counter(t.artist for t in tracks)
        artist_tracks = {}
        for track in tracks:
            if track.artist not in artist_tracks:
                artist_tracks[track.artist] = []
            if track.name not in artist_tracks[track.artist]:
                artist_tracks[track.artist].append(track.name)

        # Build artist stats for top artists
        top_artists = []
        genre_counts = Counter()

        for artist, count in artist_counts.most_common(20):
            # Get tags for genre inference
            tags = self.get_artist_tags(artist)
            for tag in tags[:3]:  # Top 3 tags per artist
                genre_counts[tag] += count

            top_artists.append(
                ArtistStats(
                    name=artist,
                    play_count=count,
                    top_tracks=artist_tracks.get(artist, [])[:5],
                )
            )
            time.sleep(0.1)  # Rate limiting

        return TasteProfile(
            top_artists=top_artists,
            top_genres=[g for g, _ in genre_counts.most_common(10)],
            total_scrobbles=len(tracks),
            period_days=days,
            raw_artist_counts=dict(artist_counts),
        )

    def get_all_time_top_artists(self, limit: int = 100) -> list[ArtistStats]:
        """Get user's all-time top artists"""
        return self.get_top_artists(period="overall", limit=limit)

    def close(self):
        """Close the HTTP client"""
        self.client.close()


# Convenience function for quick testing
def quick_test():
    """Test the client with your credentials"""
    from dotenv import load_dotenv

    load_dotenv()

    api_key = os.getenv("LASTFM_API_KEY")
    if not api_key:
        print("Error: LASTFM_API_KEY environment variable not set")
        return

    client = LastFMClient(
        api_key=api_key,
        username=os.getenv("LASTFM_USERNAME", "raquelbars"),
    )

    print("Building taste profile for last 30 days...")
    profile = client.build_taste_profile(days=30)

    print(f"\n📊 Total scrobbles: {profile.total_scrobbles}")
    print("\n🎤 Top Artists:")
    for artist in profile.top_artists[:10]:
        print(f"  - {artist.name}: {artist.play_count} plays")

    print(f"\n🎵 Top Genres: {', '.join(profile.top_genres[:5])}")

    client.close()


if __name__ == "__main__":
    quick_test()
