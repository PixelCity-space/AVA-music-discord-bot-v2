from providers.ytdlp_provider import YTDLPProvider


def get_providers(config):
    return [
        YTDLPProvider(
            ytdlp_path=config.ytdlp_path or "yt-dlp",
            user_agent=config.user_agent
        )
    ]

async def resolve_any(url, providers):
    for provider in providers:
        if provider.matches(url):
            return await provider.resolve(url)
    return None
async def resolve_playlist_any(url, providers):
    for provider in providers:
        if provider.matches(url) and provider.is_playlist(url):
            return await provider.resolve_playlist(url)
    return []
