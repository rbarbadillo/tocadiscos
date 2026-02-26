"""
Music Recommendation Agent

LangGraph workflow for personalized album recommendations with Langfuse tracing.
"""

import os
from datetime import datetime
from typing import Annotated, Any, Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_mistralai import ChatMistralAI
from braintrust import init_logger
from braintrust_langchain import BraintrustCallbackHandler
from langfuse.langchain import CallbackHandler
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from src.lastfm_client import LastFMClient, TasteProfile
from src.web_search import AlbumInfo, SearchResult, WebSearcher

# ============================================================================
# State Definition
# ============================================================================


class AgentState(TypedDict):
    """State that flows through the graph"""

    # User info
    username: str

    # Taste profile from Last.fm
    taste_profile: TasteProfile | None

    # Search results
    search_results: list[SearchResult]

    # Final recommendations
    recommendations: list[AlbumInfo]

    # Messages for LLM interactions
    messages: Annotated[list, add_messages]

    # Workflow control
    recommendation_type: Literal["new_releases", "classics"]
    error: str | None


# ============================================================================
# Structured Output Models
# ============================================================================


class RecommendationList(BaseModel):
    """Structured output for album recommendations"""

    albums: list[AlbumInfo] = Field(description="List of recommended albums")
    summary: str = Field(description="Brief summary of the recommendations")


# ============================================================================
# Node Functions
# ============================================================================


def fetch_listening_data(state: AgentState) -> dict:
    """
    Node 1: Fetch user's listening history from Last.fm
    """
    print("📊 Fetching listening data from Last.fm...")

    try:
        api_key = os.getenv("LASTFM_API_KEY")
        if not api_key:
            return {
                "error": "LASTFM_API_KEY environment variable not set",
                "taste_profile": None,
            }
        client = LastFMClient(
            api_key=api_key,
            username=state["username"],
        )

        # Build taste profile from last 30 days
        profile = client.build_taste_profile(days=30)
        client.close()

        # Create a summary message for the LLM
        top_artists = ", ".join([a.name for a in profile.top_artists[:10]])
        top_genres = ", ".join(profile.top_genres[:5])

        summary = f"""
User's listening profile (last 30 days):
- Total scrobbles: {profile.total_scrobbles}
- Top artists: {top_artists}
- Top genres: {top_genres}
"""

        return {
            "taste_profile": profile,
            "messages": [HumanMessage(content=summary)],
        }

    except Exception as e:
        return {
            "error": f"Failed to fetch Last.fm data: {str(e)}",
            "taste_profile": None,
        }


def search_new_releases(state: AgentState) -> dict:
    """
    Node 2a: Search for new album releases based on taste profile
    """
    print("🔍 Searching for new releases...")

    profile = state.get("taste_profile")
    if not profile:
        return {"search_results": [], "error": "No taste profile available"}

    searcher = WebSearcher()

    # Extract genres and artist names for targeted search
    genres = profile.top_genres[:5]
    artists = [a.name for a in profile.top_artists[:10]]

    results = searcher.search_new_releases(
        genres=genres,
        artists=artists,
    )

    # Format results for LLM
    results_text = "\n\n".join([f"**{r.title}**\n{r.url}\n{r.body}" for r in results[:15]])

    return {
        "search_results": results,
        "messages": [HumanMessage(content=f"Search results for new releases:\n\n{results_text}")],
    }


def search_classic_albums(state: AgentState) -> dict:
    """
    Node 2b: Search for classic albums the user might not have heard
    """
    print("🔍 Searching for classic albums...")

    profile = state.get("taste_profile")

    searcher = WebSearcher()
    results = searcher.search_classic_albums(
        exclude_artists=[a.name for a in (profile.top_artists if profile else [])]
    )

    results_text = "\n\n".join([f"**{r.title}**\n{r.url}\n{r.body}" for r in results[:15]])

    return {
        "search_results": results,
        "messages": [HumanMessage(content=f"Search results for classic albums:\n\n{results_text}")],
    }


def generate_recommendations(state: AgentState) -> dict:
    """
    Node 3: Use LLM to analyze search results and generate personalized recommendations
    """
    print("🤖 Generating recommendations with LLM...")

    profile = state.get("taste_profile")
    search_results = state.get("search_results", [])
    rec_type = state.get("recommendation_type", "new_releases")

    if not search_results:
        return {
            "recommendations": [],
            "error": "No search results to analyze",
        }

    # Build the prompt
    if rec_type == "new_releases":
        task = """Based on the user's listening profile and the search results about new album releases,
recommend 5 NEW albums (released in the last week) that would match their taste.

IMPORTANT: Only recommend albums that were ACTUALLY released this week/month.
For each album, explain WHY it matches the user's taste based on their listening history."""
    else:
        task = """Based on the user's listening profile and the search results about classic albums,
recommend 5 CLASSIC albums that the user likely hasn't listened to yet.

IMPORTANT:
- Exclude artists the user already listens to frequently
- Choose albums from diverse genres
- Pick albums considered essential/influential
For each album, explain WHY this classic would appeal to them based on their listening patterns."""

    # Create system message
    system_msg = SystemMessage(
        content=f"""You are a knowledgeable music curator. Your task is to analyze
a user's listening habits and recommend albums they would enjoy.

{task}

User's taste profile:
- Top artists: {", ".join([a.name for a in profile.top_artists[:10]]) if profile else "Unknown"}
- Top genres: {", ".join(profile.top_genres[:5]) if profile else "Unknown"}
- Recent listening: {profile.total_scrobbles if profile else 0} scrobbles in last 30 days

Respond with a JSON object containing:
{{
  "albums": [
    {{
      "title": "Album Name",
      "artist": "Artist Name",
      "release_date": "Release date if known",
      "genre": "Primary genre",
      "why_recommended": "Why this matches the user's taste"
    }}
  ],
  "summary": "Brief overview of your recommendations"
}}
"""
    )

    # Prepare search context
    search_context = "\n\n".join(
        [f"Source: {r.title}\nURL: {r.url}\nContent: {r.body}" for r in search_results[:10]]
    )

    user_msg = HumanMessage(
        content=f"""Here are the search results to analyze:

{search_context}

Based on this information and the user's taste profile, provide your album recommendations as JSON."""
    )

    # Get LLM provider from environment (default: mistral)
    llm_provider = os.getenv("LLM_PROVIDER", "mistral").lower()

    if llm_provider == "anthropic":
        llm = ChatAnthropic(
            model_name="claude-opus-4-5-20251101",
            temperature=0.7,
        )
    else:  # Default to Mistral
        llm = ChatMistralAI(
            model="mistral-large-latest",
            temperature=0.7,
        )

    response = llm.invoke([system_msg, user_msg])

    # Parse response
    try:
        import json

        # Extract JSON from response
        raw_content = response.content
        content = raw_content if isinstance(raw_content, str) else str(raw_content)
        # Handle markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        data = json.loads(content.strip())

        recommendations = [
            AlbumInfo(
                title=album.get("title", "Unknown"),
                artist=album.get("artist", "Unknown"),
                release_date=album.get("release_date"),
                genre=album.get("genre"),
                why_recommended=album.get("why_recommended"),
            )
            for album in data.get("albums", [])
        ]

        return {
            "recommendations": recommendations,
            "messages": [AIMessage(content=data.get("summary", "Here are your recommendations!"))],
        }

    except Exception as e:
        print(f"Error parsing LLM response: {e}")
        return {
            "recommendations": [],
            "error": f"Failed to parse recommendations: {str(e)}",
            "messages": [AIMessage(content=response.content)],
        }


def route_search_type(state: AgentState) -> str:
    """Router: decide which search to perform"""
    rec_type = state.get("recommendation_type", "new_releases")
    if rec_type == "classics":
        return "search_classics"
    return "search_new"


# ============================================================================
# Graph Construction
# ============================================================================


def build_recommendation_graph() -> CompiledStateGraph:
    """Build the LangGraph workflow"""

    # Create the graph
    graph: StateGraph = StateGraph(AgentState)  # type: ignore[arg-type]

    # Add nodes
    graph.add_node("fetch_listening_data", fetch_listening_data)
    graph.add_node("search_new_releases", search_new_releases)
    graph.add_node("search_classic_albums", search_classic_albums)
    graph.add_node("generate_recommendations", generate_recommendations)

    # Add edges
    graph.add_edge(START, "fetch_listening_data")

    # Conditional routing based on recommendation type
    graph.add_conditional_edges(
        "fetch_listening_data",
        route_search_type,
        {
            "search_new": "search_new_releases",
            "search_classics": "search_classic_albums",
        },
    )

    graph.add_edge("search_new_releases", "generate_recommendations")
    graph.add_edge("search_classic_albums", "generate_recommendations")
    graph.add_edge("generate_recommendations", END)

    return graph.compile()


# ============================================================================
# Main Agent Class
# ============================================================================


class MusicRecommendationAgent:
    """
    Main agent class with Langfuse integration
    """

    def __init__(self):
        self.graph = build_recommendation_graph()
        # CallbackHandler reads from LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY,
        # and LANGFUSE_HOST environment variables automatically
        self.langfuse_handler = CallbackHandler()
        init_logger(project="tocadiscos")
        self.braintrust_handler = BraintrustCallbackHandler()

    def get_new_release_recommendations(
        self,
        username: str = "raquelbars",
        session_id: str | None = None,
    ) -> list[AlbumInfo]:
        """
        Get new album recommendations based on recent listening.

        Args:
            username: Last.fm username
            session_id: Optional session ID for Langfuse grouping

        Returns:
            List of recommended albums
        """
        # Configure Langfuse handler with metadata
        metadata: dict[str, Any] = {
            "recommendation_type": "new_releases",
            "username": username,
        }
        if session_id:
            metadata["langfuse_session_id"] = session_id

        config: dict[str, Any] = {
            "callbacks": [self.langfuse_handler, self.braintrust_handler],
            "metadata": metadata,
        }

        # Initial state
        initial_state = {
            "username": username,
            "recommendation_type": "new_releases",
            "messages": [],
            "taste_profile": None,
            "search_results": [],
            "recommendations": [],
            "error": None,
        }

        # Run the graph (langgraph accepts dict as config)
        result = self.graph.invoke(initial_state, config=config)  # type: ignore[arg-type]

        return result.get("recommendations", [])

    def get_classic_recommendations(
        self,
        username: str = "raquelbars",
        session_id: str | None = None,
    ) -> list[AlbumInfo]:
        """
        Get classic album recommendations based on all-time listening.
        """
        metadata: dict[str, Any] = {
            "recommendation_type": "classics",
            "username": username,
        }
        if session_id:
            metadata["langfuse_session_id"] = session_id

        config: dict[str, Any] = {
            "callbacks": [self.langfuse_handler, self.braintrust_handler],
            "metadata": metadata,
        }

        initial_state = {
            "username": username,
            "recommendation_type": "classics",
            "messages": [],
            "taste_profile": None,
            "search_results": [],
            "recommendations": [],
            "error": None,
        }

        result = self.graph.invoke(initial_state, config=config)  # type: ignore[arg-type]

        return result.get("recommendations", [])


# ============================================================================
# CLI Testing
# ============================================================================


def main():
    """Test the agent"""
    from dotenv import load_dotenv

    load_dotenv()

    print("🎵 Music Recommendation Agent")
    print("=" * 50)

    agent = MusicRecommendationAgent()

    print("\n📀 Getting NEW RELEASE recommendations...")
    new_albums = agent.get_new_release_recommendations(
        username=os.getenv("LASTFM_USERNAME", "raquelbars"),
        session_id=f"test-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
    )

    print("\n🆕 New Release Recommendations:")
    print("-" * 40)
    for album in new_albums:
        print(f"\n🎵 {album.title} by {album.artist}")
        if album.genre:
            print(f"   Genre: {album.genre}")
        if album.release_date:
            print(f"   Released: {album.release_date}")
        if album.why_recommended:
            print(f"   Why: {album.why_recommended}")

    print("\n" + "=" * 50)
    print("✅ Check Langfuse dashboard for traces!")
    print(f"   {os.getenv('LANGFUSE_HOST', 'https://cloud.langfuse.com')}")


if __name__ == "__main__":
    main()
