#!/usr/bin/env python3
"""
Music Recommendation Agent - Main Entry Point

Run this script to get personalized music recommendations based on your Last.fm history.

Usage:
    python main.py                    # Run both recommendation types
    python main.py --new-releases     # Only new releases
    python main.py --classics         # Only classic albums
    python main.py --no-notify        # Don't send notifications
"""

import argparse
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.agent import MusicRecommendationAgent
from src.notifications import NotificationService
from src.web_search import AlbumInfo

console = Console()


def display_recommendations(
    recommendations: list[AlbumInfo],
    title: str,
):
    """Pretty print recommendations using Rich"""

    if not recommendations:
        console.print(f"[yellow]No {title.lower()} found.[/yellow]")
        return

    table = Table(title=title, show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=3)
    table.add_column("Album", style="bold")
    table.add_column("Artist", style="cyan")
    table.add_column("Genre", style="green")
    table.add_column("Why?", style="italic", max_width=40)

    for i, album in enumerate(recommendations, 1):
        table.add_row(
            str(i),
            album.title,
            album.artist,
            album.genre or "-",
            (
                album.why_recommended[:40] + "..."
                if album.why_recommended and len(album.why_recommended) > 40
                else album.why_recommended or "-"
            ),
        )

    console.print(table)


def run_recommendation_workflow(
    get_new_releases: bool = True,
    get_classics: bool = True,
    send_notifications: bool = True,
):
    """
    Run the full recommendation workflow.

    Args:
        get_new_releases: Whether to get new release recommendations
        get_classics: Whether to get classic album recommendations
        send_notifications: Whether to send notifications
    """
    # Load environment variables
    load_dotenv()

    # Validate required env vars
    required_vars = ["LASTFM_API_KEY", "ANTHROPIC_API_KEY"]
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        console.print(f"[red]Missing required environment variables: {', '.join(missing)}[/red]")
        console.print("[yellow]Copy .env.example to .env and fill in your API keys.[/yellow]")
        sys.exit(1)

    username = os.getenv("LASTFM_USERNAME", "raquelbars")
    session_id = f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    console.print(
        Panel.fit(
            f"[bold green]🎵 Music Recommendation Agent[/bold green]\n"
            f"User: {username}\n"
            f"Session: {session_id}",
            border_style="green",
        )
    )

    # Initialize agent
    agent = MusicRecommendationAgent()
    all_recommendations = []

    # Get new release recommendations
    if get_new_releases:
        console.print("\n[bold blue]📀 Fetching new release recommendations...[/bold blue]")
        with console.status("[bold green]Analyzing your listening history..."):
            new_releases = agent.get_new_release_recommendations(
                username=username,
                session_id=session_id,
            )

        display_recommendations(new_releases, "🆕 New Releases This Week")
        all_recommendations.extend(new_releases)

    # Get classic album recommendations
    if get_classics:
        console.print("\n[bold blue]🏛️ Fetching classic album recommendations...[/bold blue]")
        with console.status("[bold green]Finding classics you might have missed..."):
            classics = agent.get_classic_recommendations(
                username=username,
                session_id=session_id,
            )

        display_recommendations(classics, "🏆 Classic Albums For You")
        all_recommendations.extend(classics)

    # Send notifications
    if send_notifications and all_recommendations:
        console.print("\n[bold blue]📬 Sending notifications...[/bold blue]")

        notifier = NotificationService()

        if get_new_releases and new_releases:
            notifier.send_recommendations(
                new_releases,
                title="🆕 New Albums This Week",
            )

        if get_classics and classics:
            notifier.send_recommendations(
                classics,
                title="🏆 Classic Albums For You",
            )

    # Final message
    console.print("\n" + "=" * 60)
    console.print(
        Panel.fit(
            "[bold green]✅ Done![/bold green]\n\n"
            f"Check your Langfuse dashboard for traces:\n"
            f"[link]{os.getenv('LANGFUSE_HOST', 'https://cloud.langfuse.com')}[/link]",
            border_style="green",
        )
    )


def main():
    parser = argparse.ArgumentParser(
        description="Get personalized music recommendations based on your Last.fm history"
    )
    parser.add_argument(
        "--new-releases",
        "-n",
        action="store_true",
        help="Only get new release recommendations",
    )
    parser.add_argument(
        "--classics",
        "-c",
        action="store_true",
        help="Only get classic album recommendations",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Don't send notifications",
    )
    parser.add_argument(
        "--user",
        "-u",
        type=str,
        help="Override Last.fm username",
    )

    args = parser.parse_args()

    # If neither specific flag is set, do both
    get_new = args.new_releases or (not args.new_releases and not args.classics)
    get_classic = args.classics or (not args.new_releases and not args.classics)

    # Override username if provided
    if args.user:
        os.environ["LASTFM_USERNAME"] = args.user

    run_recommendation_workflow(
        get_new_releases=get_new,
        get_classics=get_classic,
        send_notifications=not args.no_notify,
    )


if __name__ == "__main__":
    main()
